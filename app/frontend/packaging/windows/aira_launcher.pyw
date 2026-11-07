"""AIRA для Windows (пилотная сборка): запускает локальную базу и сервер, открывает AIRA в браузере.

Раскладка установки ({app} — папка программы):
    {app}\\python\\            Python 3.12 с зависимостями бэкенда и модели
    {app}\\pgsql\\             PostgreSQL 18 (bin, lib, share)
    {app}\\app\\backend\\      бэкенд без изменений + ml_bundle (модель)
    {app}\\app\\frontend\\     фронтенд и aira_host.py
    {app}\\launcher\\          этот файл и иконка

Данные пользователя: %LOCALAPPDATA%\\AIRA (база, рабочие файлы проверки, журналы).
Лицензирования в пилотной сборке нет. Окно управления остаётся открытым, пока работает AIRA:
«Выйти» штатно останавливает сервер и базу.
"""

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
PY = APP / "python"
PG_BIN = APP / "pgsql" / "bin"
FRONTEND = APP / "app" / "frontend"
MODEL = APP / "app" / "backend" / "ml_bundle"
DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIRA"
PGDATA, RUNTIME, LOGS, STATE = DATA / "pgdata", DATA / "runtime", DATA / "logs", DATA / "state.json"
APP_PORT, PG_PORT = 47017, 47432          # постоянный адрес — чтобы браузер помнил настройки AIRA
NO_WINDOW = 0x08000000
MUTEX = "AIRA-Launcher"


# ---------- журнал: у pythonw нет консоли ----------
def open_log():
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / "aira.log"
    if log.exists() and log.stat().st_size > 5_000_000:
        log.replace(LOGS / "aira.1.log")
    stream = open(log, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = stream
    print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} AIRA start, app={APP}", flush=True)
    return log


def run(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], creationflags=NO_WINDOW, stdout=sys.stdout, stderr=sys.stdout,
                          stdin=subprocess.DEVNULL, **kw)


def port_free(port):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(preferred):
    if port_free(preferred):
        return preferred
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------- PostgreSQL ----------
def pg_running():
    return run([PG_BIN / "pg_ctl.exe", "status", "-D", PGDATA]).returncode == 0


def pg_port_from_pid():
    try:
        return int((PGDATA / "postmaster.pid").read_text().splitlines()[3])
    except Exception:
        return None


def start_postgres(say):
    if not (PGDATA / "PG_VERSION").exists():
        say("Первый запуск: готовим базу данных…")
        r = run([PG_BIN / "initdb.exe", "-D", PGDATA, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"])
        if r.returncode:
            raise LaunchError("Не удалось создать базу данных AIRA.")
    if pg_running():
        port = pg_port_from_pid()
        if port:
            return port
        run([PG_BIN / "pg_ctl.exe", "stop", "-D", PGDATA, "-m", "fast", "-w"])
    say("Запускаем базу данных…")
    port = pick_port(PG_PORT)
    r = run([PG_BIN / "pg_ctl.exe", "start", "-D", PGDATA, "-w", "-t", "90", "-l", LOGS / "postgres.log",
             "-o", f"-p {port} -c listen_addresses=127.0.0.1"])
    if r.returncode:
        raise LaunchError("Не удалось запустить базу данных AIRA.")
    import psycopg

    with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="postgres", autocommit=True) as c:
        if not c.execute("select 1 from pg_database where datname='aira'").fetchone():
            c.execute("create database aira")
    return port


def stop_postgres():
    if (PGDATA / "PG_VERSION").exists() and pg_running():
        run([PG_BIN / "pg_ctl.exe", "stop", "-D", PGDATA, "-m", "fast", "-w", "-t", "60"])


class LaunchError(Exception):
    pass


# ---------- снятие блокировки после сбоя проверки ----------
def stuck_failed_run(pg_port):
    """Проверка упала, а отметка «воркер занят» осталась (сервер тогда не стартует).
    Снимать её безопасно, только если тот запуск уже завершён."""
    import psycopg

    with psycopg.connect(host="127.0.0.1", port=pg_port, user="postgres", dbname="aira") as c:
        row = c.execute("select s.run_id from docx_analysis_supervisor s join docx_analysis_runs r on r.id = s.run_id "
                        "where s.slot_key = 1 and s.phase = 'armed' "
                        "and r.status in ('succeeded','failed','cancelled','timed_out')").fetchone()
        return row[0] if row else None


def clear_stuck_run(pg_port, run_id):
    import psycopg

    with psycopg.connect(host="127.0.0.1", port=pg_port, user="postgres", dbname="aira") as c:
        c.execute("update docx_analysis_supervisor set phase='clean', revision=revision+1, launch_id=null, document_id=null, "
                  "run_id=null, attempt_id=null, worker_instance_id=null, claim_fence=null "
                  "where slot_key=1 and phase='armed' and run_id=%s", (run_id,))
        print("cleared stuck analysis fence for run", run_id, flush=True)


# ---------- сервер ----------
class Server:
    def __init__(self):
        self.server = self.thread = self.url = None
        self.error = None

    def start(self, pg_port, say):
        sys.executable = str(PY / "python.exe")  # воркер анализа — обычный python.exe (запускается без окна)
        sys.path.insert(0, str(FRONTEND))
        import uvicorn

        import aira_host

        port = pick_port(APP_PORT)
        self.url = f"http://127.0.0.1:{port}/aira/"
        analysis = "model" if (MODEL / "models" / "manifest.json").exists() else "fixture"
        say("Загружаем модель…" if analysis == "model" else "Запускаем сервер…")
        ready = threading.Event()
        app = aira_host.build_app(database_url=f"postgresql+psycopg://postgres@127.0.0.1:{pg_port}/aira",
                                  runtime_root=RUNTIME, port=port, analysis=analysis, initialize=True,
                                  on_ready=ready.set)
        config = uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="info")
        self.server = uvicorn.Server(config)

        def serve():
            try:
                self.server.run()
            except BaseException as e:  # noqa: BLE001
                self.error = e
                traceback.print_exc()

        self.thread = threading.Thread(target=serve, name="aira-server", daemon=True)
        self.thread.start()
        while not self.server.started:
            if not self.thread.is_alive():
                raise self.error or LaunchError("Сервер AIRA не запустился.")
            time.sleep(0.1)
        STATE.write_text(json.dumps({"url": self.url, "pid": os.getpid()}), encoding="utf-8")
        return self.url

    def stop(self):
        if self.server and self.thread and self.thread.is_alive():
            self.server.should_exit = True
            self.thread.join(timeout=60)
        try:
            STATE.unlink()
        except OSError:
            pass


# ---------- окно управления ----------
def main():
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW(None, False, MUTEX)
    if kernel.GetLastError() == 183:  # AIRA уже запущена — просто открыть её
        for _ in range(100):
            try:
                webbrowser.open(json.loads(STATE.read_text(encoding="utf-8"))["url"])
                return
            except Exception:
                time.sleep(0.3)
        return

    log = open_log()
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("AIRA")
    root.resizable(False, False)
    try:
        root.iconbitmap(str(APP / "launcher" / "aira.ico"))
    except tk.TclError:
        pass
    pad = tk.Frame(root, padx=22, pady=18, bg="#ffffff")
    pad.pack(fill="both", expand=True)
    root.configure(bg="#ffffff")
    try:
        logo = tk.PhotoImage(file=str(FRONTEND / "static" / "logo.png")).subsample(2, 2)
        tk.Label(pad, image=logo, bg="#ffffff").grid(row=0, column=0, rowspan=2, padx=(0, 14), sticky="n")
    except tk.TclError:
        logo = None
    tk.Label(pad, text="AIRA", font=("Segoe UI Semibold", 16), bg="#ffffff", fg="#101828").grid(row=0, column=1, sticky="w")
    status = tk.StringVar(value="Запуск…")
    tk.Label(pad, textvariable=status, font=("Segoe UI", 10), bg="#ffffff", fg="#475467", wraplength=300,
             justify="left").grid(row=1, column=1, sticky="w")
    hint = tk.Label(pad, text="AIRA открывается в браузере. Не закрывайте это окно, пока работаете: "
                              "оно управляет сервером на этом компьютере.",
                    font=("Segoe UI", 9), bg="#ffffff", fg="#667085", wraplength=360, justify="left")
    hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(14, 12))
    buttons = tk.Frame(pad, bg="#ffffff")
    buttons.grid(row=3, column=0, columnspan=2, sticky="e")
    server = Server()
    state = {"pg": None, "busy": True}

    def say(text):
        root.after(0, status.set, text)

    def open_app():
        if server.url:
            webbrowser.open(server.url)

    open_btn = tk.Button(buttons, text="Открыть AIRA", command=open_app, state="disabled", font=("Segoe UI", 10),
                         bg="#4f5bd5", fg="#ffffff", activebackground="#4250c4", activeforeground="#ffffff",
                         relief="flat", padx=14, pady=5)
    quit_btn = tk.Button(buttons, text="Выйти", font=("Segoe UI", 10), relief="groove", padx=14, pady=4)
    open_btn.pack(side="left", padx=(0, 8))
    quit_btn.pack(side="left")

    def boot():
        try:
            state["pg"] = start_postgres(say)
            try:
                url = server.start(state["pg"], say)
            except Exception as e:
                code = getattr(e, "code", None) or getattr(server.error, "code", None)
                run_id = stuck_failed_run(state["pg"]) if code == "recovery_required" else None
                if not run_id:
                    raise
                ok = ask("AIRA", "Прошлая проверка завершилась сбоем, и AIRA заблокировала новые проверки.\n\n"
                                 "Снять блокировку? Документы и результаты не пострадают.")
                if not ok:
                    raise
                clear_stuck_run(state["pg"], run_id)
                server.__init__()
                url = server.start(state["pg"], say)
            say("AIRA работает.")
            root.after(0, lambda: open_btn.configure(state="normal"))
            if not os.environ.get("AIRA_NO_BROWSER"):  # для автотестов сборки
                webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            msg = str(e) if isinstance(e, LaunchError) else "AIRA не запустилась."
            say(f"{msg} Подробности — в журнале: {log}")
        finally:
            state["busy"] = False

    def ask(title, text):
        box = {}
        done = threading.Event()

        def show():
            box["ok"] = messagebox.askyesno(title, text, parent=root)
            done.set()
        root.after(0, show)
        done.wait()
        return box["ok"]

    def quit_app(source="button"):
        print(f"quit requested: {source}", flush=True)
        if server.url:
            answer = messagebox.askyesno("Выйти из AIRA?", "Перед выходом сохраните документы в AIRA (кнопка «Сохранить»).\n\n"
                                                           "Остановить AIRA?", parent=root)
            print(f"quit confirmed: {answer}", flush=True)
            if not answer:
                return
        quit_btn.configure(state="disabled")
        open_btn.configure(state="disabled")
        status.set("Завершаем работу…")

        def stop():
            try:
                server.stop()
                stop_postgres()
            finally:
                print("AIRA stopped", flush=True)
                root.after(0, root.destroy)
        threading.Thread(target=stop, daemon=True).start()

    quit_btn.configure(command=quit_app)
    root.protocol("WM_DELETE_WINDOW", lambda: quit_app("window close"))
    threading.Thread(target=boot, name="aira-boot", daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
