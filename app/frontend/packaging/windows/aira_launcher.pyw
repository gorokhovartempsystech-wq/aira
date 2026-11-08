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
RUNTIME, LOGS, STATE = DATA / "runtime", DATA / "logs", DATA / "state.json"   # база — см. pg_paths()
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
    print_environment()
    return log


def print_environment():
    """Сведения о системе для разбора проблем на чужом компьютере (без имён файлов документов)."""
    import locale
    import platform

    try:
        version = (APP / "launcher" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = "dev"
    k = ctypes.windll.kernel32
    info = {
        "aira": version, "windows": platform.platform(), "python": sys.version.split()[0],
        "ansi_codepage": k.GetACP(), "oem_codepage": k.GetOEMCP(), "locale": locale.getlocale(),
        "user_ascii": os.environ.get("USERNAME", "").isascii(), "app_ascii": str(APP).isascii(),
        "data_ascii": str(DATA).isascii(), "model": (MODEL / "models" / "manifest.json").exists(),
        "cpus": os.cpu_count(), "tz": time.strftime("%z"),
    }
    print("environment:", info, flush=True)


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
# PostgreSQL на Windows не работает с русскими буквами в путях (например, профиль «C:\Users\Анна»):
# initdb вставляет путь в SQL в кодировке Windows и падает с «invalid byte sequence for encoding UTF8».
# Поэтому ему передаются только латинские пути: короткие имена Windows (8.3) или запасная папка.
def short_path(p):
    p = Path(p)
    if str(p).isascii():
        return p
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 1024) and buf.value.isascii():
        return Path(buf.value)
    return None


_pg = None


def pg_paths():
    """bin, share, каталог базы и журнал PostgreSQL — только латиницей."""
    global _pg
    if _pg:
        return _pg
    bin_, share = short_path(PG_BIN), short_path(APP / "pgsql" / "share")
    if not bin_ or not share:
        raise LaunchError("AIRA установлена в папку с русскими буквами в пути, а база данных так не работает. "
                          "Переустановите AIRA в папку латиницей, например C:\\AIRA.")
    DATA.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    home, logs = short_path(DATA), short_path(LOGS)
    if not home:
        import hashlib

        user = hashlib.sha256(os.environ.get("USERNAME", "user").encode()).hexdigest()[:10]
        home = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "AIRA" / user
        home.mkdir(parents=True, exist_ok=True)
        logs = home
        print("non-ASCII profile path without 8.3 names; database in", home, flush=True)
    _pg = {"bin": bin_, "share": share, "data": home / "pgdata", "log": (logs or home) / "postgres.log"}
    print("postgres paths:", {k: str(v) for k, v in _pg.items()}, flush=True)
    return _pg


def pg(cmd, *args):
    # Английские сообщения PostgreSQL: русские на Windows приходят в другой кодировке и не читаются в журнале.
    return run([pg_paths()["bin"] / cmd, *args], env=dict(os.environ, LC_MESSAGES="C"))


def pg_running():
    return pg("pg_ctl.exe", "status", "-D", pg_paths()["data"]).returncode == 0


def pg_port_from_pid():
    try:
        return int((pg_paths()["data"] / "postmaster.pid").read_text().splitlines()[3])
    except Exception:
        return None


def start_postgres(say):
    p = pg_paths()
    if not (p["data"] / "PG_VERSION").exists():
        say("Первый запуск: готовим базу данных…")
        r = pg("initdb.exe", "-D", p["data"], "-L", p["share"], "-U", "postgres", "-A", "trust", "-E", "UTF8",
               "--locale=C")
        if r.returncode:
            raise LaunchError("Не удалось создать базу данных AIRA.")
    if pg_running():
        port = pg_port_from_pid()
        if port:
            return port
        pg("pg_ctl.exe", "stop", "-D", p["data"], "-m", "fast", "-w")
    say("Запускаем базу данных…")
    port = pick_port(PG_PORT)
    r = pg("pg_ctl.exe", "start", "-D", p["data"], "-w", "-t", "90", "-l", p["log"],
           "-o", f"-p {port} -c listen_addresses=127.0.0.1")
    if r.returncode:
        raise LaunchError("Не удалось запустить базу данных AIRA.")
    import psycopg

    with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="postgres", autocommit=True) as c:
        if not c.execute("select 1 from pg_database where datname='aira'").fetchone():
            c.execute("create database aira")
    return port


def stop_postgres():
    try:
        p = pg_paths()
    except LaunchError:
        return
    if (p["data"] / "PG_VERSION").exists() and pg_running():
        pg("pg_ctl.exe", "stop", "-D", p["data"], "-m", "fast", "-w", "-t", "60")


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
        self.server = self.thread = self.url = self.connection = None
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
                                  on_ready=ready.set, log_file=LOGS / "aira.log")
        self.connection = dict(app.state.aira_connection)
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


# ---------- запуск базы и сервера (общий для окна приложения и запасного режима) ----------
def boot_backend(server, state, say, ask):
    state["pg"] = start_postgres(say)
    try:
        return server.start(state["pg"], say)
    except Exception as e:
        code = getattr(e, "code", None) or getattr(server.error, "code", None)
        run_id = stuck_failed_run(state["pg"]) if code == "recovery_required" else None
        if not run_id:
            raise
        if not ask("AIRA", "Прошлая проверка завершилась сбоем, и AIRA заблокировала новые проверки.\n\n"
                           "Снять блокировку? Документы и результаты не пострадают."):
            raise
        clear_stuck_run(state["pg"], run_id)
        server.__init__()
        return server.start(state["pg"], say)


def shutdown_backend(server):
    try:
        server.stop()
        stop_postgres()
    finally:
        print("AIRA stopped", flush=True)


def version():
    try:
        return (APP / "launcher" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"


# ---------- окно приложения (WebView2 через pywebview) ----------
SPLASH = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;font:15px/1.5 "Segoe UI",system-ui,sans-serif;background:#f4f5f8;color:#101828}
.box{height:100%;display:grid;place-items:center;text-align:center}
.card{background:#fff;border:1px solid #e4e7ec;border-radius:16px;padding:34px 40px;box-shadow:0 8px 24px rgba(16,24,40,.08);min-width:340px}
h1{margin:10px 0 6px;font-size:22px}#s{color:#475467;margin:0}
.sp{width:28px;height:28px;border:3px solid #e4e7ec;border-top-color:#4f5bd5;border-radius:50%;margin:18px auto 0;animation:r 1s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}.err .sp{display:none}.err #s{color:#c2352b}
button{margin-top:16px;font:inherit;padding:7px 16px;border-radius:9px;border:1px solid #cfd4dd;background:#fff;cursor:pointer;display:none}
.err button{display:inline-block}
</style></head><body><div class="box"><div class="card" id="c"><img src="LOGO" width="56" height="56" alt="">
<h1>AIRA</h1><p id="s">Запуск…</p><div class="sp"></div>
<button onclick="window.pywebview.api.open_logs()">Открыть журнал</button></div></div>
<script>window.setStatus=(t,e)=>{document.getElementById('s').textContent=t;document.getElementById('c').className=e?'card err':'card';}</script>
</body></html>"""


class DesktopApi:
    """Методы для страницы (window.pywebview.api.*): подключение, системные окна файлов, закрытие."""

    def __init__(self, ctx):
        self._ctx = ctx

    def connection(self):
        return self._ctx["server"].connection

    def app_version(self):
        return version()

    def open_logs(self):
        os.startfile(str(LOGS))

    def open_docx(self):
        import base64

        import webview

        paths = self._ctx["window"].create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                                                       file_types=("Документы Word (*.docx)", "Все файлы (*.*)"))
        if not paths:
            return None
        path = Path(paths[0] if isinstance(paths, (list, tuple)) else paths)
        data = path.read_bytes()
        if len(data) > 32 * 1024 * 1024:
            return {"name": path.name, "b64": "", "too_big": True}
        return {"name": path.name, "b64": base64.b64encode(data).decode("ascii")}

    def save_file(self, name, b64, kind="docx"):
        import base64

        import webview

        types = ("Документ Word (*.docx)",) if kind == "docx" else ("Текстовый файл (*.txt)",)
        path = self._ctx["window"].create_file_dialog(webview.FileDialog.SAVE, save_filename=name, file_types=types)
        if not path:
            return {"saved": False}
        path = Path(path[0] if isinstance(path, (list, tuple)) else path)
        path.write_bytes(base64.b64decode(b64))
        return {"saved": True, "path": str(path)}

    def close_result(self, ok):
        # Ответ страницы на запрос закрытия: prepareToClose() дописал правки (ok) или пользователь остаётся.
        print(f"close requested, page answered: {ok}", flush=True)
        self._ctx["closing"] = False
        if ok:
            self._ctx["allow_close"] = True
            threading.Thread(target=self._ctx["window"].destroy, daemon=True).start()


def set_window_icon(title):
    """У окна pywebview значок Python: ставим значок AIRA (окно и панель задач)."""
    user = ctypes.windll.user32
    user.FindWindowW.restype = ctypes.c_void_p
    user.LoadImageW.restype = ctypes.c_void_p
    user.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    for _ in range(50):
        hwnd = user.FindWindowW(None, title)
        if hwnd:
            for size, which in ((16, 0), (32, 1)):
                icon = user.LoadImageW(None, str(APP / "launcher" / "aira.ico"), 1, size, size, 0x10)
                if icon:
                    user.SendMessageW(hwnd, 0x80, ctypes.c_void_p(which), ctypes.c_void_p(icon))
            return
        time.sleep(0.1)


def run_desktop(log):
    import webview

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AIRA.Desktop")
    ctx = {"server": Server(), "state": {"pg": None}, "allow_close": False, "closing": False, "window": None}
    logo = "data:image/png;base64," + __import__("base64").b64encode((FRONTEND / "static" / "logo.png").read_bytes()).decode()
    window = webview.create_window("AIRA", html=SPLASH.replace("LOGO", logo), js_api=DesktopApi(ctx),
                                   width=1380, height=900, min_size=(1000, 640))
    ctx["window"] = window

    def say(text, error=False):
        try:
            window.evaluate_js(f"window.setStatus && window.setStatus({json.dumps(text)}, {json.dumps(error)})")
        except Exception:
            pass

    def ask(title, text):
        return window.create_confirmation_dialog(title, text)

    def on_closing():
        server = ctx["server"]
        if ctx["allow_close"] or not server.url:
            return True
        if not ctx["closing"]:
            ctx["closing"] = True
            # Спросить страницу: она допишет правки (prepareToClose) и ответит через close_result().
            def request():
                # run_js не ждёт ответа: окно может закрыться раньше, чем evaluate_js вернётся.
                run = getattr(window, "run_js", None) or window.evaluate_js
                try:
                    run("window.__airaRequestClose ? window.__airaRequestClose() : window.pywebview.api.close_result(true)")
                except Exception:
                    ctx["closing"] = False
            threading.Thread(target=request, daemon=True).start()
        return False

    window.events.closing += on_closing

    def boot():
        threading.Thread(target=set_window_icon, args=("AIRA",), daemon=True).start()
        try:
            url = boot_backend(ctx["server"], ctx["state"], say, ask)
            window.load_url(url + "#desktop")
            if os.environ.get("AIRA_SELFTEST"):  # самопроверка сборки: загрузка страницы и закрытие окна
                time.sleep(int(os.environ.get("AIRA_SELFTEST") or 12))
                probe = window.evaluate_js(
                    "JSON.stringify({url: location.href, app: !document.getElementById('app').hidden, "
                    "start: !document.getElementById('start').hidden, native: !!(window.__airaRequestClose), "
                    "licence: !document.getElementById('licence').hidden, tour: !!document.querySelector('.tour')})")
                print("selftest page:", probe, flush=True)
                window.destroy()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            msg = str(e) if isinstance(e, LaunchError) else "AIRA не запустилась."
            say(f"{msg} Подробности — в журнале.", True)

    try:
        webview.start(boot, gui="edgechromium", private_mode=False, storage_path=str(DATA / "webview"))
    finally:
        shutdown_backend(ctx["server"])


# ---------- запасной режим: окно управления + браузер (если нет WebView2) ----------
def run_browser(log):
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
    tk.Label(pad, text="AIRA открывается в браузере. Не закрывайте это окно, пока работаете: "
                       "оно управляет сервером на этом компьютере.",
             font=("Segoe UI", 9), bg="#ffffff", fg="#667085", wraplength=360, justify="left").grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(14, 12))
    buttons = tk.Frame(pad, bg="#ffffff")
    buttons.grid(row=3, column=0, columnspan=2, sticky="e")
    server, state = Server(), {"pg": None}

    def say(text, error=False):
        root.after(0, status.set, text)

    def ask(title, text):
        box, done = {}, threading.Event()

        def show():
            box["ok"] = messagebox.askyesno(title, text, parent=root)
            done.set()
        root.after(0, show)
        done.wait()
        return box["ok"]

    open_btn = tk.Button(buttons, text="Открыть AIRA", command=lambda: server.url and webbrowser.open(server.url),
                         state="disabled", font=("Segoe UI", 10), bg="#4f5bd5", fg="#ffffff",
                         activebackground="#4250c4", activeforeground="#ffffff", relief="flat", padx=14, pady=5)
    quit_btn = tk.Button(buttons, text="Выйти", font=("Segoe UI", 10), relief="groove", padx=14, pady=4)
    tk.Button(buttons, text="Журнал", font=("Segoe UI", 10), relief="groove", padx=10, pady=4,
              command=lambda: os.startfile(str(LOGS))).pack(side="left", padx=(0, 8))
    open_btn.pack(side="left", padx=(0, 8))
    quit_btn.pack(side="left")

    def boot():
        try:
            url = boot_backend(server, state, say, ask)
            say("AIRA работает.")
            root.after(0, lambda: open_btn.configure(state="normal"))
            if not os.environ.get("AIRA_NO_BROWSER"):  # для автотестов сборки
                webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            msg = str(e) if isinstance(e, LaunchError) else "AIRA не запустилась."
            say(f"{msg} Подробности — в журнале: {log}")

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
                shutdown_backend(server)
            finally:
                root.after(0, root.destroy)
        threading.Thread(target=stop, daemon=True).start()

    quit_btn.configure(command=quit_app)
    root.protocol("WM_DELETE_WINDOW", lambda: quit_app("window close"))
    threading.Thread(target=boot, name="aira-boot", daemon=True).start()
    root.mainloop()


def focus_running():
    """AIRA уже запущена: вывести её окно вперёд (или открыть в браузере в запасном режиме)."""
    user = ctypes.windll.user32
    user.FindWindowW.restype = ctypes.c_void_p
    hwnd = user.FindWindowW(None, "AIRA")
    if hwnd:
        user.ShowWindow(ctypes.c_void_p(hwnd), 9)
        user.SetForegroundWindow(ctypes.c_void_p(hwnd))
        return
    for _ in range(100):
        try:
            webbrowser.open(json.loads(STATE.read_text(encoding="utf-8"))["url"])
            return
        except Exception:
            time.sleep(0.3)


def main():
    if "--stop-db" in sys.argv:  # вызывает деинсталлятор: остановить базу, если она осталась после сбоя
        open_log()
        stop_postgres()
        return
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW(None, False, MUTEX)
    if kernel.GetLastError() == 183:
        focus_running()
        return
    log = open_log()
    mode = "browser" if os.environ.get("AIRA_BROWSER_MODE") or "--browser" in sys.argv else "desktop"
    if mode == "desktop":
        try:
            import webview  # noqa: F401
        except Exception:
            traceback.print_exc()
            mode = "browser"
    print("ui mode:", mode, flush=True)
    if mode == "desktop":
        try:
            run_desktop(log)
            return
        except Exception:
            # Нет WebView2 или окно не создалось: продолжаем в браузере.
            traceback.print_exc()
            print("desktop window failed, falling back to browser mode", flush=True)
    run_browser(log)


if __name__ == "__main__":
    main()
