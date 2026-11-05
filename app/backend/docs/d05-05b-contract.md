# D05-05B — владение PostgreSQL процессом на macOS

4 ноября 2026. После D05-05A/0afb3c2, F02/F11/F12. Разрешены только новые
`src/ara/desktop/postgres_process/`, `tests/acceptance/test_desktop_postgres_process*.py`,
этот contract/result/guide/queue. Старые source/tests/dependencies/БД/миграции/
runner/tasks/progress не менять. Windows реализация, cluster filesystem/record/
publication, схема/backup и общая desktop composition — следующие этапы.

## Интерфейс и права

`OwnedCommand(owner, executable:Path, arguments:tuple[str,...], *, cwd:Path,
capture_stdout:bool=False)` — inert constructor. owner exact существующий macOS
RuntimeOwner текущего PID; он принадлежит higher-level coordinator и здесь не
закрывается. Worker резервирует его SlotLease на одну команду. Это внутренний API
для доверенных bundled binaries, не endpoint для пользовательских команд.
Проверку installer pin/immutable payload делает launcher отдельно. Не искать binary
в PATH, не выполнять shell=True и не принимать environment override от caller.

executable/cwd absolute Path без `..`, NUL/controls, <=4096UTF8bytes. arguments exact
tuple<=128, каждый str<=4096bytes без NUL/Unicode control/format/line separators,
пустые arguments допускаются. Весь закрытый bootstrap JSON<=16384bytes.
Нет I/O/threads/entropy/env lookup при импорте/constructor. Не копировать/pickle;
origin PID проверяется до mutex. Repr/errors/view не включают пути/arguments/output.

`start()->ProcessView` однократно начинает worker, повтор started idempotent;
start после shutdown(new) — invalid_handle. `view()` frozen phase,error_code,
resources_pending,returncode. Phases new,starting,running,stopping,exited,failed.
new не владеет ресурсами, start немедленно pending. running — получен started ACK,
не SQL-ready. Ненулевой command exit → failed/process_failed, но подтверждённая
очистка может закончиться. Нельзя смешивать semantic success и cleanup proof.

`shutdown(timeout=5)->bool`: finite number0..5 (не bool), запрос graceful Stop и join
вне mutex. True только когда закончился worker и подтверждены guardian wait,
slot-free и закрытие своих FDs. New→exited без команды, owner не закрывается.
Повтор closed cleanup=True. При незавершённом shutdown False; нет повышения до
SIGINT/SIGQUIT/SIGKILL по timeout. `stdout()->bytes` только для capture=True,
успешного exit0 и известной очистки; иначе invalid_handle. Не отдавать truncated
output или ошибочную диагностику как успешный результат команды.

CommandError fixed codes validation_error,invalid_handle,platform_unavailable,
process_busy,process_unavailable,process_failed,output_limit,protocol_error,
cleanup_unknown. Unknown→process_unavailable. Результат хранит только code.
Одна активная/неизвестно очищенная команда на owner, strong process registry;
потеря ссылки не освобождает ресурсы. После известного cleanup новая команда
использует тот же owner. Thread-start неизвестен → quarantine, без ложного True.

## Guardian и Stop

Отдельный фиксированный isolated Python entry (-I,-B), импорт только установленного
package. Минимальный env PATH=/usr/bin:/bin,LC_ALL=C,LANG=C,TZ=UTC; никаких inherited
PG*/DYLD*/PYTHON*/secrets. stdin private control/keepalive pipe, stdout status pipe,
stderr DEVNULL, inherited SlotLease FD. Guardian и command в собственных sessions.
Slot private single-link regular0600/current uid/zero size, без explicit flock unlock.

Parent передаёт единственную strict JSON line<=16384 с keys version=1,argv(tuple
на wire list с executable первым),cwd,capture(bool) только после получения своего
Popen. До полной проверенной line child не запускается. EOF/Stop до её завершения
отменяет запуск. После line любые дополнительные bytes — protocol failure/Stop;
обычный Stop и parent death — EOF. Control writer не наследуется другими children.
Parent public methods меняют state/event; только worker читает/пишет/закрывает FDs
и ждёт guardian. Никакого гоняющегося close(fd) из другого thread.

Guardian запускает command stdin DEVNULL, stdout/stderr pipes, inherited slot FD.
PG получает тот же lock description. Один guardian loop владеет прямым child PID
до reap: на Stop SIGTERM только этому child, затем wait; никогда process-group kill,
поиск/усыновление PID или waitpid(-1). Старый ML OwnedChild с escalated group kill
здесь использовать нельзя. Параллельного waiter нет; один loop сериализует signal/
wait. Ошибка сигнала не доказывает exit; ошибка wait/неизвестный child create —
uncertain и quarantine, никакого повторного kill предполагаемого PID.

Guardian справедливо читает control/stdout/stderr bounded chunks. Server output
discard без накопления/лог-файла; finite stdout capture<=65536bytes. Overflow
задаёт output_limit и Stop, не обрезанный успешный результат. stderr никогда не
возвращается/логируется. Parent status total<=100000bytes, не более2 closed frames:
started, затем finished(returncode,error_code,stdout base64,uncertain bool).
Finished без started допустим только для uncertain startup failure. Время подготовки
bootstrap<=15s по sleep-counting clock; timeout просит graceful Stop, не kill.
Потерянный/невалидный status — ошибка, но не отказ от ожидания своего child.

Guardian exit сам по себе недостаточен: после известного wait parent освобождает
свою копию slot и проверяет отсутствие держателей. Если descendants ещё держат
slot, сохраняет owner/registry и ждёт, пробуя reserve/release без запуска новой
команды. Результат close/spawn/wait неизвестен → pending/quarantine. Не закрывать
чужие FDs и не удалять lock/PID files. Parent startup error с неизвестным Popen
не превращается в cleanup только из-за свободного slot.

Parent death → guardian видит EOF и просит smart shutdown. Если одновременно
погиб guardian, живой PG сохраняет inherited slot: новая установка не начинает
initdb/PG поверх него. Автоматическое управление таким orphan по PID запрещено;
в этом узком этапе может понадобиться завершение OS-сессии/перезапуск компьютера.
Это fail-closed обнаружение, не обещание автоматического clean crash recovery.
Higher coordinator обязан получить owner+slot admission до любых cluster mutations.

## Приёмка

Native preflight4ноября на PG18.6 прошёл: initdb completion, inherited PG slot
не позволяет повторную reserve после закрытия parent copy; smart shutdown ждёт
открытый connection, COMMIT проходит, после закрытия connection PG exits0, slot
освобождается; повторный сервер читает сохранённую synthetic row. Временные cluster/
socket очищены после собственного wait. Main не затронут.

Freeze/red, portable validation/PID/copy/immutable view; native fixture commands
success/nonzero/finite ignore-term/stderr flood/stdout limit, partial bootstrap,
сильное удержание, concurrent Stop, unknown spawn/close/wait fencing. Отдельные
процессы для quarantine/fork/crash scenarios. Native PG: start, активная SQL
транзакция, pending shutdown, успешный COMMIT, закрытие connection, exit/slot proof,
restart/read same data. Parent-process death должен остановить собственный PG
через guardian EOF. Всё на disposable paths/данных, без существующего сервера.

Новые ошибки подготовки tests можно исправить с описанием причины без ослабления
assertions; frozen старые проверки unchanged. Full/hash/mainV8/result/local commit.
Windows native Job/HANDLE/SSPI ещё не подтверждены; этот Mac модуль там отклоняет
запуск и не импортирует Darwin-only implementation до explicit start.

Основания: [PG18 shutdown](https://www.postgresql.org/docs/18/server-shutdown.html),
[PG18 postmaster/ClosePostmasterPorts](https://raw.githubusercontent.com/postgres/postgres/REL_18_STABLE/src/backend/postmaster/postmaster.c).
