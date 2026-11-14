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
