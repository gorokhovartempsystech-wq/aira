"""AIRA для Windows: запускает локальную базу и сервер, открывает лицензированное окно AIRA.

Раскладка установки ({app} — папка программы):
    {app}\\python\\            Python 3.12 с зависимостями бэкенда и модели
    {app}\\pgsql\\             PostgreSQL 18 (bin, lib, share)
    {app}\\app\\backend\\      бэкенд без изменений + ml_bundle (модель)
    {app}\\app\\frontend\\     фронтенд и aira_host.py
    {app}\\launcher\\          этот файл и иконка

Данные пользователя: %LOCALAPPDATA%\\AIRA (база, рабочие файлы проверки, журналы).
Серверная лицензия обязательна при каждом запуске. Native WebView2 передаёт capability
через мост; браузерный режим этой лицензированной поставки не поддерживается.
Доступ к зашифрованной модели подтверждается закрытым ключом устройства из Windows Credential Manager.
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
STARTUP_TIMEOUT = 300
SHUTDOWN_TIMEOUT = 150


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
    kw.setdefault("timeout", 120)
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

    with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="postgres", autocommit=True, connect_timeout=5, options="-c statement_timeout=5000") as c:
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
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# ---------- снятие блокировки после сбоя ----------
# Если прошлый процесс AIRA завершился, не дождавшись воркера проверки (сбой, «Выйти» во время проверки,
# выключение компьютера), запись воркера остаётся в «armed», и бэкенд не стартует (recovery_required).
# Так было у пилота 0.2.0: проверка ещё шла, поэтому прежнее снятие «только для завершённых» не помогало.
# На Windows воркеры живут в Job-объекте с «убить при закрытии»: раз старого процесса AIRA нет, нет и воркеров.
# Тогда запись переводится в «drained» — это бэкенд сам записал бы после подтверждённого выхода воркера, —
# и дальше он штатно восстанавливается: отменяет очередь, помечает прерванную проверку и очищает запись.
PG_OPTIONS = {"connect_timeout": 5, "options": "-c lock_timeout=2000 -c statement_timeout=5000"}


def other_aira_processes():
    """PID процессов Python из папки AIRA, кроме этого (например, воркер прошлого запуска)."""
    k, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    pids, got = (ctypes.c_ulong * 4096)(), ctypes.c_ulong()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(got)):
        return []
    mine, root, out = os.getpid(), str(PY).lower(), []
    k.OpenProcess.restype = ctypes.c_void_p
    for pid in pids[: got.value // ctypes.sizeof(ctypes.c_ulong)]:
        if not pid or pid == mine:
            continue
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf, size = ctypes.create_unicode_buffer(1024), ctypes.c_ulong(1024)
            if k.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(size)) and buf.value.lower().startswith(root):
                out.append(pid)
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    return out


def stuck_fence(pg_port):
    import psycopg

    with psycopg.connect(host="127.0.0.1", port=pg_port, user="postgres", dbname="aira", **PG_OPTIONS) as c:
        row = c.execute("select s.phase, s.run_id, r.status from docx_analysis_supervisor s "
                        "left join docx_analysis_runs r on r.id = s.run_id where s.slot_key = 1").fetchone()
        return row if row and row[0] == "armed" else None


def release_stuck_fence(pg_port):
    import psycopg

    with psycopg.connect(host="127.0.0.1", port=pg_port, user="postgres", dbname="aira", **PG_OPTIONS) as c:
        n = c.execute("update docx_analysis_supervisor set phase='drained', revision=revision+1 "
                      "where slot_key=1 and phase='armed'").rowcount
    print(f"recovery: analysis worker record armed -> drained ({n} row)", flush=True)
    return n == 1


# ---------- сервер ----------
def configure_static_types():
    # Windows registry can classify .mjs as text/plain. WebView2 then refuses
    # module execution and the page remains at the initial startup screen.
    # Initialize OS associations first, then explicitly override our scripts.
    import mimetypes

    mimetypes.init()
    for extension in (".mjs", ".js"):
        mimetypes.add_type("text/javascript", extension)


class Server:
    def __init__(self):
        self.server = self.thread = self.url = self.connection = None
        self.license_client = self.license_home = None
        self.application = None
        self.error = None

    def start(self, pg_port, say):
        from aira_startup import Progress, StartupError, database_url, wait_started
        progress = Progress(say)
        progress("prepare")
        configure_static_types()
        sys.executable = str(PY / "python.exe")  # воркер анализа — обычный python.exe (запускается без окна)
        sys.path.insert(0, str(FRONTEND))
        import uvicorn

        import aira_host

        started_at = time.monotonic()
        print("startup: preparing local application", flush=True)

        port = pick_port(APP_PORT)
        self.url = f"http://127.0.0.1:{port}/aira/"
        analysis = "model" if (MODEL / "models" / "manifest.json").exists() else "fixture"
        from ara.desktop.access import new_session_token
        from ara.desktop.data_home import open_home
        from ara.model_protection.bundle import configuration
        from aira_licensed_app import NativeApplication, create_license_client

        updates = json.loads((APP / "launcher/release-config.json").read_text())
        self.license_home = open_home(DATA / "state-v2")
        self.license_client = create_license_client(APP / "launcher/release-config.json", self.license_home.path("license"), MODEL / "models")
        token = new_session_token()
        ready = threading.Event()
        def startup_failed(error):
            self.error = error
        app = aira_host.build_app(database_url=database_url(pg_port),
                                  runtime_root=RUNTIME, port=port, analysis=analysis, initialize=True,
                                  onboarding_path=DATA / "onboarding.json",
                                  app_update={"feed_url": updates["origin"].rstrip("/") + "/updates/windows-x64.xml",
                                              "version": version(), "platform": "windows-x64"},
                                  on_ready=ready.set, log_file=LOGS / "aira.log", native_token=token.hex(),
                                  startup_timeout=120, shutdown_timeout=120,
                                  model_key_provider=self.license_client.require_model_key if configuration(MODEL / "models") else None,
                                  startup_progress=progress, on_startup_error=startup_failed,
                                  database_connect_args={"connect_timeout": 5, "options": "-c lock_timeout=5000 -c statement_timeout=30000"})
        self.connection = dict(app.state.aira_connection)
        protected = NativeApplication(app, self.license_client, origin=self.connection["origin"], token=token)
        self.application = protected
        self.license_client.start()
        config = uvicorn.Config(protected, host="127.0.0.1", port=port, proxy_headers=False, access_log=False, log_level="info")
        self.server = uvicorn.Server(config)

        def serve():
            try:
                self.server.run()
            except BaseException as e:  # noqa: BLE001
                if self.error is None:
                    self.error = e
                traceback.print_exc()

        self.thread = threading.Thread(target=serve, name="aira-server", daemon=True)
        self.thread.start()
        def current_error():
            code = self.application.startup_error
            if code and not isinstance(getattr(self.error, "code", None), str):
                return LaunchError("Сервер AIRA не запустился.", code=code)
            return self.error
        try:
            wait_started(self.server, self.thread, current_error, progress, timeout=STARTUP_TIMEOUT)
        except StartupError as error:
            self.server.should_exit = True
            raise LaunchError(str(error), code=error.code) from self.error
        STATE.write_text(json.dumps({"url": self.url, "pid": os.getpid()}), encoding="utf-8")
        return self.url

    def stop(self):
        if self.server and self.thread and self.thread.is_alive():
            self.server.should_exit = True
            self.thread.join(timeout=SHUTDOWN_TIMEOUT)
            if self.thread.is_alive():
                raise LaunchError("Завершение сервера AIRA ещё не подтверждено. База данных сохранена.")
        if self.application is not None and (
            self.application.shutdown_failed
            or (self.application.startup_failed and self.application.startup_error is None)
        ):
            raise LaunchError("Завершение компонентов AIRA не подтверждено. Подробности — в журнале.")
        if self.license_client is not None and not self.license_client.shutdown(timeout=5):
            raise LaunchError("Проверка лицензии ещё завершается. Повторите закрытие AIRA.")
        if self.license_home is not None and not self.license_home.close():
            raise LaunchError("Не удалось подтвердить закрытие данных лицензии.")
        self.license_client = None
        self.connection = None
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
        fence = stuck_fence(state["pg"]) if code == "recovery_required" else None
        print(f"startup refused: code={code} fence={fence}", flush=True)
        if not fence:
            raise
        others = other_aira_processes()
        if others:
            print("recovery skipped: other AIRA processes are alive", others, flush=True)
            raise LaunchError("Прошлый запуск AIRA ещё не завершился. Подождите минуту или перезагрузите "
                              "компьютер и откройте AIRA снова.") from e
        say("Восстанавливаемся после прошлого сбоя…")
        server.stop()
        if not release_stuck_fence(state["pg"]):
            raise
        server.__init__()
        return server.start(state["pg"], say)


def shutdown_backend(server):
    try:
        server.stop()
        stop_postgres()
    except Exception:
        print("AIRA shutdown incomplete", flush=True)
        raise
    else:
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
#t{color:#98a2b3;font-size:13px;margin:10px 0 0}#h{color:#667085;font-size:13px;max-width:340px;margin:8px auto 0;display:none}
button{margin-top:16px;font:inherit;font-size:13.5px;padding:6px 14px;border-radius:9px;border:1px solid #cfd4dd;background:#fff;cursor:pointer}
</style></head><body><div class="box"><div class="card" id="c"><img src="LOGO" width="56" height="56" alt="">
<h1>AIRA</h1><p id="s">Запуск…</p><div class="sp"></div><p id="t"></p>
<p id="h">Первый запуск может занять несколько минут: создаётся база и антивирус проверяет файлы программы.</p>
<button onclick="window.pywebview.api.open_logs()">Открыть журнал</button></div></div>
<script>window.setStatus=(t,e)=>{document.getElementById('s').textContent=t;document.getElementById('c').className=e?'card err':'card';if(e){clearInterval(window.__tick);document.getElementById('h').style.display='none';}};
const t0=Date.now();window.__tick=setInterval(()=>{const s=Math.floor((Date.now()-t0)/1000);document.getElementById('t').textContent=Math.floor(s/60)+':'+String(s%60).padStart(2,'0');if(s>=45)document.getElementById('h').style.display='block';},1000);</script>
</body></html>"""


class DesktopApi:
    """Методы для страницы (window.pywebview.api.*): подключение, системные окна файлов, закрытие."""

    def __init__(self, ctx):
        self._ctx = ctx

    def _require_native_page(self):
        from aira_licensed_app import trusted_page

        if not trusted_page(self._ctx["window"].get_current_url(), self._ctx["server"].url):
            raise LaunchError("Этот запрос недоступен вне окна AIRA.")

    def connection(self):
        self._require_native_page()
        connection = self._ctx["server"].connection
        if connection is None:
            raise LaunchError("Сервер AIRA ещё не готов.")
        return dict(connection)

    def app_version(self):
        return version()

    def _require_native_page(self):
        from urllib.parse import urlsplit

        try:
            current = urlsplit(self._ctx["window"].get_current_url())
            expected = urlsplit(self._ctx["server"].url)
            trusted = (current.scheme == expected.scheme == "http"
                       and current.hostname == expected.hostname == "127.0.0.1"
                       and current.port == expected.port and expected.port is not None
                       and current.path == expected.path == "/aira/"
                       and not current.username and not current.password and not current.query)
        except (TypeError, ValueError):
            trusted = False
        if not trusted:
            raise LaunchError("Обновление доступно только в окне AIRA.")

    def request_update(self):
        self._require_native_page()
        if self._ctx["closing"] or self._ctx["allow_close"]:
            return False
        self._ctx["update_requested"] = True
        # The native close handshake first waits for this RPC reply to reach JS.
        self._ctx["request_update"]()
        return True

    def open_logs(self):
        os.startfile(str(LOGS))

    def open_docx(self):
        self._require_native_page()
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
        self._require_native_page()
        import base64

        import webview

        types = ("Документ Word (*.docx)",) if kind == "docx" else ("Текстовый файл (*.txt)",)
        path = self._ctx["window"].create_file_dialog(webview.FileDialog.SAVE, save_filename=name, file_types=types)
        if not path:
            return {"saved": False}
        path = Path(path[0] if isinstance(path, (list, tuple)) else path)
        path.write_bytes(base64.b64decode(b64))
        return {"saved": True, "path": str(path)}

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
    ctx = {"server": Server(), "state": {"pg": None}, "allow_close": False, "closing": False, "window": None,
           "closed": threading.Event(), "update_requested": False}
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

    def on_closing(wait_for_update_ack=False):
        server = ctx["server"]
        if ctx["allow_close"] or not server.url:
            return True
        from aira_licensed_app import trusted_page
        if not trusted_page(window.get_current_url(), server.url):
            return True
        if not ctx["closing"]:
            ctx["closing"] = True
            from aira_startup import request_window_close
            def result(ok):
                print(f"close requested, page answered: {ok}", flush=True)
                ctx["closing"] = False
                ctx["allow_close"] = ok
                if not ok:
                    ctx["update_requested"] = False
            def error(exc):
                ctx["closing"] = False
                ctx["allow_close"] = False
                ctx["update_requested"] = False
                print("close handshake failed:", type(exc).__name__, flush=True)
            request_window_close(window, ctx["closed"], result, error,
                                 wait_for_update_ack=wait_for_update_ack)
        return False

    ctx["request_update"] = lambda: on_closing(wait_for_update_ack=True)
    window.events.closing += on_closing
    window.events.closed += ctx["closed"].set

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
                    "licence: !document.getElementById('licence').hidden, activation: !!document.querySelector('input.key'), "
                    "bridge: !!window.pywebview?.api?.connection, gateText: document.getElementById('licence').innerText, "
                    "tour: !!document.querySelector('.tour')})")
                print("selftest page:", probe, flush=True)
                try:
                    state = ctx["server"].license_client.view()
                    print("selftest license:", {"phase": state.phase, "error_code": state.error_code}, flush=True)
                except Exception as exc:
                    print("selftest license diagnostic:", type(exc).__name__, flush=True)
                from urllib.request import urlopen
                for relative in ("assets/js/main.mjs", "assets/js/host.mjs", "client/document-workspace.mjs"):
                    with urlopen(url + relative, timeout=5) as response:
                        print("selftest resource:", relative, response.status, response.headers.get("Content-Type"), flush=True)
                # Exercise the same save/close handshake as the user's close button.
                on_closing()
        except (Exception, SystemExit) as e:  # noqa: BLE001
            traceback.print_exc()
            from aira_startup import StartupError
            msg = str(e) if isinstance(e, (LaunchError, StartupError)) else "AIRA не запустилась."
            say(f"{msg} Подробности — в журнале.", True)

    try:
        webview.start(boot, gui="edgechromium", private_mode=False, storage_path=str(DATA / "webview"))
    finally:
        ctx["closed"].set()
        shutdown_backend(ctx["server"])
    return ctx["update_requested"]


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
        if state.get("quitting"):  # повторное «Выйти» во время выхода прерывало остановку воркера проверки
            return
        if server.url:
            answer = messagebox.askyesno("Выйти из AIRA?", "Перед выходом сохраните документы в AIRA (кнопка «Сохранить»).\n\n"
                                                           "Остановить AIRA?", parent=root)
            print(f"quit confirmed: {answer}", flush=True)
            if not answer:
                return
        state["quitting"] = True
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
    """AIRA уже запущена: дождаться native-окна, не открывая HTTP bootstrap."""
    user = ctypes.windll.user32
    user.FindWindowW.restype = ctypes.c_void_p
    for _ in range(100):
        hwnd = user.FindWindowW(None, "AIRA")
        if hwnd:
            user.ShowWindow(ctypes.c_void_p(hwnd), 9)
            user.SetForegroundWindow(ctypes.c_void_p(hwnd))
            return
        time.sleep(0.3)
    print("Existing AIRA window is not ready; browser fallback is disabled", flush=True)


def main():
    if "--stop-db" in sys.argv:  # вызывает деинсталлятор: остановить базу, если она осталась после сбоя
        open_log()
        stop_postgres()
        return
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, MUTEX)
    if not mutex:
        raise LaunchError("Не удалось подготовить запуск AIRA.")
    if kernel.GetLastError() == 183:
        kernel.CloseHandle(mutex)
        focus_running()
        return
    log = open_log()
    # Backend and editor have not started: the installer cannot discard edits.
    try:
        from aira_updates import startup_update
        if startup_update(APP / "launcher", version()):
            return
    except Exception as error:
        print("Update check unavailable:", type(error).__name__, flush=True)
    try:
        if os.environ.get("AIRA_BROWSER_MODE") or "--browser" in sys.argv:
            raise LaunchError("Для этой версии AIRA нужен Microsoft Edge WebView2 Runtime. "
                              "Лицензированное приложение работает в собственном окне.")
        if run_desktop(log):
            # The old backend/PostgreSQL have stopped; the new process starts with WinSparkle.
            kernel.CloseHandle(mutex)
            mutex = None
            subprocess.Popen([str(PY / "pythonw.exe"), str(Path(__file__).resolve())],
                             creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as error:
        traceback.print_exc()
        message = str(error) if isinstance(error, LaunchError) else "Не удалось открыть окно AIRA. Проверьте установку Microsoft Edge WebView2 Runtime."
        ctypes.windll.user32.MessageBoxW(None, message + "\nПодробности — в журнале AIRA.", "AIRA", 0x10)
        raise SystemExit(1) from None
    finally:
        if mutex:
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()

