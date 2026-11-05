# Владение командами PostgreSQL на macOS

D05-05B, 4 ноября 2026. `ara.desktop.postgres_process.OwnedCommand` запускает
одну доверенную bundled команду через отдельный guardian и подтверждает освобождение
ресурсов. Это внутренний компонент: нельзя предоставлять выбор executable/arguments
через пользовательский HTTP API. Проверка файлов установки остаётся обязанностью
launcher; объект команды сам не проверяет подпись пакета.

Конструктор получает существующий macOS RuntimeOwner, absolute executable/cwd,
tuple arguments и optional capture_stdout. Он не создаёт файлов и процессов.
Owner остаётся у higher-level coordinator; команда его не закрывает. Coordinator
держит owner до завершения всех операций над cluster и проверяет slot admission
перед изменением файлов после restart.

`start()` начинает worker и возвращает ProcessView. Повторный start начатого объекта
не дублирует запуск. running означает подтверждённый запуск дочерней команды, а не
готовность SQL или frontend. view содержит только phase,error_code,resources_pending,
returncode; пути/argument/output отсутствуют. Копирование/pickle/fork use запрещены.

`shutdown(timeout=5)` просит graceful Stop и ждёт не больше заданного времени0..5с.
False означает, что завершение ещё не подтверждено. Вызывать повторно допустимо;
тайм-аут не усиливает сигнал остановки. True требует законченного worker, wait
своего guardian, свободного inherited slot и известного закрытия своих descriptors.
Ненулевой exit команды может сочетаться с True: ошибка команды и cleanup различаются.
Для ещё не запущенной команды shutdown не затрагивает borrowed owner.

`stdout()` возвращает bytes только при capture_stdout=True, успешном exit0 и
подтверждённом cleanup. Предел64KiB. Переполнение даёт output_limit и graceful Stop,
обрезанный результат не возвращается. Для долгоживущего postgres capture выключен:
stdout/stderr читаются ограниченными порциями и отбрасываются, без накопления/log files.
stderr никогда не возвращается caller.

Guardian запускается fixed isolated Python entry с узким env и private pipes.
Он не запускает команду до полного ограниченного bootstrap. Parent death или Stop
закрывает keepalive pipe. Guardian отправляет SIGTERM только своему прямому child
и ждёт его завершения. Для PostgreSQL это smart shutdown: текущие connections
могут завершить свои транзакции. Нет group kill, SIGKILL escalation, чтения PID-файла
для управления чужим процессом или усыновления оставшегося сервера.

Слот наследуется guardian, PostgreSQL и его дочерними процессами. Даже если прямой
child уже reaped, оставшийся descendant сохраняет блокировку; новая команда ждёт
подтверждённого освобождения. Неизвестный spawn/wait/close/thread-start остаётся
в strong registry и возвращает cleanup pending. Потеря ссылки caller не обходит
блокировку. Поздний сбой возврата Thread.start не освобождает owner преждевременно,
даже если быстрый worker успел завершиться.

Если погибнут и родительское приложение, и guardian, живой PostgreSQL продолжит
держать slot. Компонент обнаружит занятость, но не станет искать и убивать процесс
по PID. В таком аварийном случае может понадобиться завершить OS-сессию/перезапустить
компьютер. Это ограничение отличается от проверенного обычного parent-death случая:
при живом guardian EOF приводит к smart shutdown и сохранению уже committed данных.

Native macOS проверены на PostgreSQL18.6 и временных данных: pending shutdown
с открытой транзакцией, успешный COMMIT, clean exit, повторное чтение; смерть parent
после COMMIT и последующий restart. Ещё проверены stderr flood, stdout limit,
descendant retention, concurrent Stop и injected unknown outcomes. Windows Job/
HANDLE/SSPI, durable cluster preparation, schema/backup и desktop composition идут
отдельно. Рабочая БД и пользовательский профиль этим циклом не мигрируются.
