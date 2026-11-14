"""Bounded startup progress; no platform calls, secrets, network or I/O on import."""
import time

LABELS = {
    "prepare": "Подготавливаем локальный сервер…",
    "database": "Проверяем хранилище документов…",
    "model_package": "Проверяем целостность файлов модели…",
    "routes": "Подготавливаем интерфейс…",
    "server": "Запускаем локальный сервер…",
}


class StartupError(RuntimeError):
    def __init__(self, message, code="startup_failed"):
        self.code = code
        super().__init__(message)


def database_url(port):
    # The supervisor validates URL options and applies its own stricter SQL limits.
    # Main editor limits belong to its separate engine's connect_args.
    from sqlalchemy import URL
    return URL.create("postgresql+psycopg", username="postgres", host="127.0.0.1",
                      port=port, database="aira", query={"connect_timeout": "5"}).render_as_string(hide_password=False)


def startup_error(error):
    if isinstance(error, StartupError):
        return error
    code = getattr(error, "code", None)
    code = code if isinstance(code, str) else "startup_failed"
    return StartupError("Не удалось запустить локальный сервер AIRA. Откройте журнал запуска.", code)


class Progress:
    def __init__(self, say, *, clock=time.monotonic, limit=120):
        self.say, self.clock, self.limit = say, clock, limit
        self.started = clock()
        self.stage, self.last = "prepare", -1

    def __call__(self, stage=None):
        now = self.clock()
        elapsed = now - self.started
        if elapsed >= self.limit:
            raise StartupError("Запуск AIRA превысил 120 секунд. Закройте приложение и откройте журнал запуска.", "startup_timeout")
        changed = stage is not None and stage != self.stage
        if stage is not None:
            if stage not in LABELS:
                raise ValueError("Unknown startup stage")
            self.stage = stage
        if changed or now - self.last >= 1:
            self.last = now
            self.say(f"{LABELS[self.stage]} {int(elapsed)} с")
            if changed:
                print(f"startup stage={self.stage} elapsed_ms={round(elapsed * 1000)}", flush=True)


def wait_started(server, thread, error, progress, *, clock=time.monotonic, sleep=time.sleep, timeout=90):
    deadline = clock() + timeout
    try:
        progress("server")
    except StartupError:
        server.should_exit = True
        raise
    while not server.started:
        if not thread.is_alive():
            raise startup_error(error())
        if clock() >= deadline:
            server.should_exit = True
            raise StartupError("Локальный сервер не ответил за 90 секунд. Откройте журнал запуска.", "startup_timeout")
        try:
            progress()
        except StartupError:
            server.should_exit = True
            raise
        sleep(0.1)


def request_window_close(window, closed, result, error, *, wait_for_update_ack=False):
    """Finish the JS evaluation before destroying its WebView; refuse non-boolean answers."""
    from threading import Event, Thread

    answered = Event()
    response = []

    def receive(value):
        response.append(value)
        answered.set()

    def request():
        try:
            # pywebview's promise callback is one-way. A js_api method instead
            # sends an RPC reply *after* our method returns, possibly after Close.
            update_ack = (
                "if ((await window.__airaUpdateBridgeReady) !== true) return false; "
                if wait_for_update_ack else ""
            )
            window.evaluate_js(
                # No bridge yet means the startup/error splash has no editor.
                "Promise.resolve().then(async () => { " + update_ack
                + "return window.__airaRequestClose ? await window.__airaRequestClose() : true; })",
                callback=receive,
            )
            while not answered.wait(0.1):
                if closed.is_set():
                    return
            if closed.is_set():
                return
            accepted = response[0] is True
            result(accepted)
            if accepted:
                window.destroy()
        except Exception as exc:
            if not closed.is_set():
                error(exc)

    # Joining a non-daemon thread before Python finalization keeps CLR callbacks
    # from trying to construct exception types after the interpreter is gone.
    thread = Thread(target=request, name="aira-close", daemon=False)
    thread.start()
    return thread
