# D03-17C1D1 — continuous clock и owner/slot macOS

1 ноября 2026, Astra 6 High. Первый implementation цикл [C1D](d03-17c1d-design.md), далее Sol 6.1 High. Этот контракт фиксируется до новой acceptance/source. F06–F08/F12, C1A–C1C unchanged. Pure clock conversion + explicit native clock/locks; **не** guardian, процессы модели, SQL, launcher, IPC или scheduler.

## 1. Разрешённые изменения

- Только новые `src/ara/docx_analysis_worker/macos/{__init__,_errors,_clock,_locks}.py`.
- Новая frozen `tests/acceptance/test_docx_analysis_macos_primitives.py`; собственные `tests/docx_documents/test_analysis_macos_primitives_*.py`. Синтетический subprocess fixture для наследования FD допустим в этих новых tests; это не model runtime.
- Этот contract/новая acceptance до freeze; после freeze только source и own tests. Результат `docs/d03-17c1d1-result.md`, актуальные status-ссылки в C1/C1D/queue после gate.
- Не менять старые source/tests/DDL/contracts, root worker exports, runner/tasks/progress/AGENTS/dependencies/check script. Root `macos` — новый subpackage, импорт по нему достаточен.

## 2. Ошибки и инертность

Из `ara.docx_analysis_worker.macos` экспортировать `MacRuntimeError`, `ticks_to_ns`, `DarwinClock`, `acquire_owner`, `RuntimeOwner`, `SlotLease`.

`MacRuntimeError.code` — только `validation_error`, `platform_unavailable`, `clock_unavailable`, `runtime_unavailable`, `runtime_busy`, `invalid_handle`. str/repr/traceback не содержат root path, environment, native exception text или payload; wrap errors `from None`. Никаких logging или print. Programmer invalid scalar/path type — validation_error; native unsupported platform — platform_unavailable; невалидный/чужой/закрытый resource object — invalid_handle; lock contention — runtime_busy; unsafe path/permissions/native open error — runtime_unavailable. Native clock fault — clock_unavailable.

Import package и `DarwinClock()` не выполняют platform probing, CDLL loading, clock/file/SQL/network calls, не читают environment/secrets, не стартуют thread/process. I/O только `now_ns`, `acquire_owner` и explicit resource methods. Никаких модульных singletons с открытыми FD. Не использовать context manager/destructor для неявного unlock. Objects runtime owner/slot/clock process-local, не copy/deepcopy/pickle; созданный объект после fork в другом PID не действует как authority.

## 3. Часы

`ticks_to_ns(ticks:int, numer:int, denom:int)->int` — pure, exact int (bool запрещён). Ticks0..2**64-1; numer/denom1..2**32-1. Invalid inputs — validation_error. Python integer multiplication/division без float и без uint64 wrap: `ticks*numer//denom`. Result0..2**63-1, overflow — clock_unavailable. Equal readings допустимы.

`DarwinClock()` — inert. `.now_ns()->int` — потокобезопасный explicit вызов. На первом вызове проверить Darwin, загрузить `ctypes.CDLL(None)` и задать точные signatures `mach_continuous_time()->c_uint64`, `mach_timebase_info(pointer(struct{c_uint32 numer,denom}))->c_int`. Ненулевой return code, zero/invalid timebase, missing symbol/library, backward reading, conversion overflow — clock_unavailable. На non-Darwin — platform_unavailable, без попытки загружать Apple symbols. Значения timebase закрепляются для экземпляра после успешного init, не перечитываются каждый tick.

Чтение native ticks и проверка против last_ns сериализованы под коротким lock. last_ns устанавливается только успешным вызовом; backward/overflow/native fault после начала работы делает экземпляр permanently failed. Последующие calls не сбрасывают ошибку и не переякоряют время. Новая instance не обещает восстановить утраченную попытку. Никакого fallback на time.time/monotonic/perf_counter или повторного safety guard.

Внутреннюю FFI factory можно подменять в tests для fake readings; public callback API в контракт не добавлять. Тестовый fake не объявляется native clock. PID origin фиксировать при первом explicit I/O, не в inert constructor. После fork действующий экземпляр выдаёт invalid_handle; новый inert экземпляр в child разрешён.

## 4. Каталог и locks

`acquire_owner(root:pathlib.Path)->RuntimeOwner`: explicit I/O, Darwin only. Root — абсолютный, уже существующий canonical private directory. Нет expansion `~`, resolve symlinks, mkdir пользовательского каталога или discovery HOME. Reject `..`; components открываются от `/` через directory FD с O_DIRECTORY/O_NOFOLLOW и non-inheritable descriptors. Каждый component — directory; final root owner=euid, mode ровно0700. Ancestors принадлежат root/euid и не доступны записи group/other, кроме root-owned sticky directory (например `/private/tmp`); symlink всегда reject. Canonical temp path для tests получается в trusted fixture setup, не внутри resource API. Unsupported filesystem/flag не заменяется unsafe fallback.

В root constant names `runtime.owner` и `analysis.slot`. Openat с O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC, creation0600, без O_TRUNC. Перед lock и после lock проверить fstat: regular file, euid owner, mode ровно0600, nlink1, size0. Directory entry (stat nofollow через retained dir FD) совпадает dev/ino с открытым FD. Не chmod/chown/unlink/recreate небезопасный existing file. Также перед reserve/release сверять, что canonical root всё ещё указывает на удерживаемый directory inode; подмена/rename — runtime_unavailable и никакого нового reserve. Сеть/NFS/вредоносное изменение тем же OS user не являются security guarantee этой схемы.

`runtime.owner` открывается/LOCK_EX|LOCK_NB первым. Второй независимый acquire (в том числе в том же процессе) получает runtime_busy; не обращается к slot. Только один successful owner object на root. Все открытые вспомогательные FD закрываются на любом отказе; созданный пустой lock file можно оставить. Существующие inode не удаляются ни при успехе, ни при отказе/close.

Публичные методы:

- `owner.reserve_slot()->SlotLease`: только live owned RuntimeOwner, не более одного active SlotLease на объект. Независимый open+LOCK_EX|LOCK_NB `analysis.slot`, тот же validation. Active lease уже есть/lock занят — runtime_busy. Failed reserve не повреждает owner и не снимает чужой lock.
- `slot.fileno()->int`: borrowed descriptor только для trusted launcher/pass_fds; active same-process object, иначе invalid_handle. Он не становится inheritable глобально. Caller не закрывает FD, не делает LOCK_UN, не передаёт user code. Внешний int — не новая SlotLease capability.
- `owner.release_slot(slot)->bool`: только exact active object этого owner, не по совпадению fd/root/UUID. Проверить handles/path; закрыть собственный slot FD без LOCK_UN, необратимо invalidate slot. Затем **новый независимый open+LOCK_EX|LOCK_NB** того же slot inode. Если занят наследниками — False; если захвачен — немедленно close probe, True. Probe error — runtime_unavailable; свой lease всё равно уже закрыт/invalid, owner остаётся live и не выдумывает cleanup success. Ошибка validation до close не меняет ресурсы. После False повторно release того же slot запрещён; повторная проверка делается новым reserve_slot, которое также может получить busy.
- `owner.close()->None`: idempotent для уже закрытого exact owner; если active slot ещё есть — runtime_busy, ничего не закрывает. Иначе закрывает только owner и directory FDs, инвалидирует object. Живые унаследованные slot references не разблокируются. Это низкоуровневое освобождение ресурсов, не Stop/SQL reconciliation. В C1F release/close вызываются только после соответствующих lifecycle решений.
- `owner.abandon()->None`: explicit аварийное завершение владельца, в том числе при подмене пути, когда release validation уже не проходит. Закрыть только собственные active slot/owner/directory references без probe/LOCK_UN, инвалидировать всё; повтор idempotent. Не читать изменённый path, не kill descendants, не объявлять cleanup или SQL success. C1F применяет только после прекращения admission/control при shutdown/неустранимой ошибке; дальнейшие операции закрытого owner запрещены. Это не способ продолжить работу после failed release.

Конструкторы RuntimeOwner/SlotLease не выдают usable handles извне; использовать private issuance. Проверка exact identity/внутреннего registry не доверяет dataclass attributes, переданному fd или скопированному DTO. `__new__` без инициализации/поддельный object не закрывает реальные FD. Объекты не возвращают root path/fd через repr (fileno — только explicit internal API). Внутренний lock owner сериализует reserve/release/close; callbacks/parsing/waits под ним нет, файловые операции nonblocking.

На всех путях **никогда не вызывать flock(LOCK_UN)**: close reference не снимает lock, пока у guardian/model осталась унаследованная ссылка. Owner FD не передаётся в child; slot FD — только через explicit pass_fds. Проверка одной записью LOCK_EX на уже held description не считается независимым probe. API не выводит PID и не убивает процессы.

Каждый close инвалидирует сохранённый descriptor до syscall; не повторять close старого int после ошибки/EINTR (возможен reuse). Close error возвращается sanitized runtime_unavailable после best-effort закрытия остальных собственных references; объект не оживает. Невозможность гарантированно закрыть OS resource не считается successful probe. В обычных/native acceptance путях проверяется отсутствие утечек; произвольную неисправность kernel close не выдавать за доказанный cleanup.

## 5. Frozen acceptance до реализации

Acceptance фиксируется отдельным local commit, затем red. Independent expectations, synthetic temp root только0700/fixtures, никакого реального app-data/secret/user document. Native cases Darwin only; skip в иной ОС не native pass.

1. Pure conversion: zero/max/min/rational125/3, точная floor для больших ticks, overflow на1 за signed63, bool/float/negative/out-of-range/denom0. Inputs не мутируют.
2. Clock: FFI signatures/native return codes, lazy init once, missing symbols, timebase0, overflow/backward sticky fault/equal valid; concurrent read serialization без fabricated rollback; non-Darwin explicit failure, native smoke increasing ns. Fake suspend jumps показывают continuous numbers, но не заменяют OS sleep gate D2/D3.
3. Inert fresh import/constructor с spy на forbidden I/O/env/CDLL/clock/process/SQL; safe exceptions, copy/deepcopy/pickle отказ. forked live handle rejected (child fixture закрывает только своё process resources при exit, не unlock).
4. Root/mode/type/owner/symlink parent/final/lock/hardlink/size/writable ancestry/path replacement; no truncation/chmod/unlink. Invalid caller path type, relative и `..` дают expected sanitized error. Каждый failed path не увеличивает FD count после cleanup.
5. Два owner в одном и отдельных процессах: ровно один успех; второй не снимает lock. Два slot/reserve close misuse; owner.close с active slot не закрывает его; foreign/stale/forged SlotLease не меняет FD.
6. Native inherited slot: child держит borrowed FD через pass_fds, parent release False, owner можно закрыть, новый owner успешен, reserve busy **до** natural child exit. После exact child wait новый reserve успешен. Explicit readiness pipe вместо sleep-угадывания. Owner FD не наследуется; LOCK_UN spy запрещает любой путь.
7. Release без child True; идемпотентный owner close; stale fileno/release invalid_handle, FD-number reuse не закрывает новый descriptor. Probe I/O failure после close не выдаёт True и не возвращает старый slot в active.
8. Lock inode сохранён после всех операций; repeated early failures/success cycles без утечек; всё временное удаляет test fixture только после закрытия всех своих handles и child exit.
9. Root/lock replacement после reserve: обычный release fail closed, explicit abandon закрывает только свои references и не меняет подменённые файлы. Abandon с унаследованным child slot оставляет его busy до child exit; не вызывает probe/LOCK_UN/kill. Close error/reused int не вызывает повторный close чужого FD.

Targeted/own/native + `bash scripts/check.sh`; read-only DB baseline до/после, main V8 unchanged. Report фактического результата и native skips, source/local commit. После этого на **Sol 6.1 High** подготовить отдельный D2 contract/frozen acceptance по уже выбранной C1D архитектуре и продолжить. При новом архитектурном противоречии завершить текущий цикл и передать на Astra, не подменять acceptance.
