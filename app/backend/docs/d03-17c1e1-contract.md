# D03-17C1E1 — часы и HANDLE reservations Windows

2 ноября 2026, Astra 6 High. Первый implementation contract [C1E](d03-17c1e-design.md); реализация на Sol 6.1 High. F06–F08/F12. В этом цикле нет Job, model/guardian, pipes, SQL, HTTP, scheduler, установки или чтения пользовательских документов. Native process разрешён только synthetic acceptance для проверки наследования slot.

## 1. Paths и порядок работы

Разрешены только новые:

- `src/ara/docx_analysis_worker/windows/{__init__,_errors,_clock,_abi,_handles,_security,_paths,_locks}.py`;
- `tests/acceptance/test_docx_analysis_windows_primitives.py` — новая acceptance до freeze, после freeze неизменна;
- собственные `tests/docx_documents/test_analysis_windows_primitives_*.py`;
- этот contract до acceptance freeze; `docs/d03-17c1e1-result.md` и статусные ссылки C1E/queue после проверок.

Не менять старые source/tests/contracts, exports root worker, DDL/migrations, runner/tasks/progress/check script/AGENTS/dependencies. Stdlib+ctypes, без pywin32/global install. Native DLL — системные Kernel32/Advapi32, explicit lazy loader c безопасным system32 search. Никаких WinDLL/load/probe на import.

Сначала acceptance compile/collect/review, отдельный freeze, red до source. На Mac red должен подтверждать отсутствие новой реализации в portable случаях; Windows native skips указывать отдельно, не считать pass. Затем implementation, own meaningful checks, targeted и полный `bash scripts/check.sh` на текущей платформе; read-only runtime baseline/main V8 unchanged. Native acceptance на Windows — дополнительный незакрытый gate, если среда отсутствует. Можно продолжить независимый E2, не называя Windows принятой. Не спрашивать разрешение повторно на обычные правки новых собственных файлов.

## 2. API, errors, inert import

Экспорт из нового subpackage: `WindowsRuntimeError`, `milliseconds_to_ns`, `WindowsClock`, `acquire_owner`, `RuntimeOwner`, `SlotLease`. Private native factories injectable тестами, но не публичными аргументами приложения.

Коды WindowsRuntimeError: `validation_error`, `platform_unavailable`, `clock_unavailable`, `runtime_unavailable`, `runtime_busy`, `invalid_handle`. Exact invalid scalar/path grammar→validation_error; non-win32/неподдержанный64-bit ABI→platform_unavailable; unsafe filesystem/ACL/metadata/native file error→runtime_unavailable; busy только ожидаемое sharing conflict либо уже active slot; malformed/foreign/closed capability→invalid_handle. Ошибки clock после platform check→clock_unavailable. Никаких raw WinError/path/SID/environment/payload в str/repr/chained exception; `raise ... from None`.

Import и WindowsClock() инертны: нет native loading, platform/version/filesystem/clock/env/secret/network/SQL calls, subprocess/thread start. Short Python lock allocation допустим. Нет open handles или cache текущего OS user на уровне import. Explicit operations получают current process/user через OS API, не USERNAME/USERPROFILE/environment. Информация об impersonation проверяется при acquire: thread impersonation token не поддержан, fail closed; ERROR_NO_TOKEN означает обычный process token.

Owner/slot/clock process-local, не copy/deepcopy/pickle; safe constant repr без HANDLE/path/PID/SID. RuntimeOwner и SlotLease только issued exact identity/registry: __new__/скопированные атрибуты/число HANDLE не дают authority. Проверка PID origin до ожидания внутреннего lock. Нет destructor/finalizer unlock или скрытого reacquire. Все resources закрываются только explicit методами/cleanup failed factory.

## 3. Часы и ABI

`milliseconds_to_ns(milliseconds:int)->int`: exact int (не bool), 0..2**64-1, multiplication на Python int `ms*1_000_000`, result≤2**63-1. Invalid input→validation_error; overflow result→clock_unavailable. Без float/truncate/wrap. Ноль и одинаковые readings допустимы.

`WindowsClock().now_ns()->int`: explicit thread-safe чтение. Первый I/O фиксирует PID, проверяет sys.platform==win32/64-bit pointer, lazy Kernel32 binding `GetTickCount64()->uint64`, затем conversion. Native load/symbol/read failure, backward reading или overflow делают clock sticky failed; subsequent calls не восстанавливают время. Последний успешный reading обновляется только под коротким clock mutex. Равные readings допустимы; guard второй раз не добавлять/вычитать. Non-Windows не пытается грузить Windows DLL; нет fallback на time/QueryPerformanceCounter/.NET/unbiased clock. [Win32 clock](https://learn.microsoft.com/en-us/windows/win32/sysinfo/windows-time).

FFI ABI фиксируется явно и проверяется portable тестом: HANDLE/void pointers/SIZE_T pointer-sized (поддержано8 bytes), BOOL/int32, DWORD/ULONG/ACCESS_MASK uint32, WORD uint16, LARGE_INTEGER int64, ULONGLONG uint64. Нельзя использовать native-host c_long/c_ulong как Windows DWORD на Mac. Native `W` functions принимают UTF-16; Windows WCHAR2 bytes, не host c_wchar size4 в portable layout assertions. Structures имеют Windows x64 alignment, не `_pack_=1` по догадке. У каждого native call заданы argtypes/restype/use_last_error где нужно; BOOL versus DWORD-return security API различать. INVALID_HANDLE_VALUE pointer-all-ones отличается от NULL; оба никогда не close как реальные handles. GetLastError брать сразу после failed call, до cleanup.

E1 bindings только для clock, token/SID/security descriptors, CreateFile/metadata/volume/path, DuplicateHandle/GetHandleInformation/CloseHandle и current process identity. Job/process/pipe structs не добавлять заранее. На Mac fake factory может проверять orchestration и реальные ctypes layout; это не proof Windows kernel.

## 4. Root и файловая идентичность

`acquire_owner(root:str)->RuntimeOwner` — explicit I/O. Root задаёт trusted caller; runtime не ищет HOME/app data и не создаёт root. Exact str, абсолютный DOS drive path `C:\...`, только backslash separators, минимум один component после drive root, не более64 components,≤4095 UTF-16 code units. Reject NUL/unpaired surrogates, UNC/device/extended prefix input, relative/drive-relative, `.`/`..`, empty component, terminal slash, ADS colon после drive, trailing dot/space, reserved DOS device components (включая варианты с extension), wildcard/control characters. Путь Unicode/с пробелами допустим. Grammar проверяется до native I/O; не expand/resolve/нормализовать неподдержанный input в «безопасный» путь. Internal volume-GUID path из проверенного handle может использоваться, raw user prefix не принимается.

Native путь — local fixed NTFS. Проверить volume/drive metadata, иначе runtime_unavailable. Открывать каждый существующий component от drive root, `CreateFileW(OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT)`, access FILE_READ_ATTRIBUTES|READ_CONTROL; directory/reparse/type проверки через handle. Все ancestor handles остаются у S до owner.close/abandon; share READ|WRITE **без DELETE**, у final private root share READ (без WRITE/DELETE). Никаких follow junction/symlink/mount/cloud placeholder и fallback на os.path.resolve. Root reparse всегда reject.

Для каждого pin сохранить volume/file ID; final path query bounded≤32768 UTF-16 code units, две попытки максимум при resize, дальше fail. Parent-child chain и normalized final path проверяются через pinned metadata, не только строковый prefix. Для сравнения Windows names использовать ordinal OS comparison, не Python Unicode casefold. Aliased/8.3/несовпадающий normalized path отвергается, не принимается молча. Root identity повторно сверяется перед/после открытия reservation и перед release; unexpected path/ACL/volume change→runtime_unavailable. Защита от злонамеренной подмены тем же OS user/administrator не заявляется; unknown metadata отвергается. [File identity API](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex), [Final path](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew).

Private root: owner SID равен process TokenUser. DACL present, non-null, SE_DACL_PROTECTED, только обычные ACCESS_ALLOWED_ACE для current SID, LocalSystem(S-1-5-18), Administrators(S-1-5-32-544); все три обязательны, без других/deny/callback/object/inherit-only ACE. Root ACE mask FILE_ALL_ACCESS, flags CONTAINER_INHERIT_ACE|OBJECT_INHERIT_ACE, без INHERITED_ACE. Это узкий canonical профиль нового служебного каталога, **не** универсальный Windows ACL evaluator. Existing неподходящий root отвергается; E1 не меняет ACL/owner и не создаёт application directories. Synthetic fixture создаёт профиль только в своём temporary child directory. Future installer/bootstrap должен выполнить этот precondition отдельным этапом.

Ancestor DACL не обязана быть private: они pinned без delete-sharing, root проверяется независимо; системные диски/Users не chmod/ACL-repair. Эта политика не превращает произвольный shared root в private; небезопасный final root всё равно запрещён. GetSecurityInfo вызывается по retained handle, его allocated descriptor освобождается LocalFree ровно один раз, SID копируется до free. [Handle security](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo).

## 5. Reservation files и lifetime

Constant names `runtime.owner`, `analysis.slot`. `CreateFileW` access GENERIC_READ|GENERIC_WRITE|READ_CONTROL, share0, OPEN_ALWAYS, FILE_FLAG_OPEN_REPARSE_POINT, explicit non-inheritable SECURITY_ATTRIBUTES с canonical protected DACL: те же три SID, owner current SID, FILE_ALL_ACCESS, ACE flags0. Не CREATE_ALWAYS/TRUNCATE_EXISTING/DELETE_ON_CLOSE, не запись PID/JSON/bytes. Для existing file security attributes не меняют ACL — обязательно проверить фактическую. Sharing violation32→runtime_busy; ACCESS_DENIED5/прочие ошибки не выдавать за contention.

Проверять GetFileType==DISK, не directory/reparse, end-of-file0, NumberOfLinks1, не DeletePending, тот же NTFS volume и ожидаемый parent, canonical owner/DACL. Read-only/system/offline/encrypted/compressed/sparse flags запрещены; обычный ARCHIVE flag допустим. Идентификатор `(VolumeSerialNumber, FILE_ID_128)` записывается после validation. Нет hardlink/alternate stream обхода; reservation открыть только под validated root. Полученный file handle non-inheritable, no protect-from-close flag. Existing unsafe file нельзя truncate/unlink/rename/repair. [CreateFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).

Сначала owner reservation. Второй acquire в том же/другом процессе получает busy и закрывает только свои directory pins. Slot открывается отдельно; independent handle open не подменять DuplicateHandle. Cached identity slot после первого successful reserve сохраняется на весь RuntimeOwner; следующие reserve используют OPEN_EXISTING, дальнейшее несовпадение/удаление fail closed без создания замены. Release probe также использует OPEN_EXISTING, не создаёт отсутствующий файл.

Методы:

- `owner.reserve_slot()->SlotLease`: live issued owner, максимум один active lease; private root recheck, independent open share0; безопасная ошибка не снимает owner. Slot уже active/busy native sharing→runtime_busy.
- `slot.handle()->int`: borrowed non-inheritable native HANDLE только trusted launcher; exact live issued same-process slot. Это не CRT fd. Caller не закрывает/не меняет flags и не делает из int новую capability. Private launcher позже проверяет issued slot прежде duplication.
- `owner.release_slot(slot)->bool`: exact own active slot, root/held file checks до close. Инвалидировать slot, закрыть только S reference, затем independent OPEN_EXISTING read/write share0 того же file ID. Sharing violation→False; open+same identity+metadata→закрыть probe и True. Остальные ошибки→runtime_unavailable, slot уже invalid, owner live. Ошибка precheck до close не меняет resources. False/True не позволяют второй release того же lease; проверить занятость можно новым reserve_slot. Owner slot identity не сбрасывать для принятия replacement.
- `owner.close()->None`: active slot→runtime_busy без close; иначе закрыть owner file и directory pins, invalidate, повтор idempotent. Не подтверждает model cleanup/SQL.
- `owner.abandon()->None`: invalidate и закрыть только собственные active slot/owner/pins, без path reread/probe/kill, даже при root replacement. Idempotent; inherited copies продолжают reservation. Только аварийное прекращение admission, не обход failed release для следующего запуска.

Private `_handles` реализует единственный checked-close/duplicate helper. Invalidate before CloseHandle; после native failure не повторять close того же integer. Best-effort закрыть остальные собственные handles, вернуть sanitized runtime_unavailable, не successful probe. DuplicateHandle использует retained owned capability/current process, SAME_ACCESS, без DUPLICATE_CLOSE_SOURCE; explicit temporary inheritable duplicate разрешён для будущего HANDLE_LIST. В E1 native inheritance test использует тот же helper, а original handle остаётся non-inheritable. Owner/pins не наследуются. Close S duplicate не освобождает reservation, пока осталась другая копия file object. Это проверяется нативно, не выводится из integer equality.

Все operations сериализованы коротким owner mutex; нет callbacks/ожидания чужого процесса/SQL под ним. Local filesystem syscalls не объявляются абсолютным hard-real-time: зависший filesystem→нельзя обещать мгновенный UI response; C1F вызывает admission на своей execution lane. Root local NTFS исключает сетевой fallback.

## 6. Приёмка до source

Portable deterministic cases без Windows kernel:

1. Conversion0/exact maximum before overflow/one-after, uint64 max, bool/float/negative/subclass, no wrap; clock lazy once/equal/backward/overflow/sticky/missing API/concurrent reads, platform rejection до load. Sleep jump — simulated, не native suspend.
2. Fresh import+constructor с forbidden-I/O spies, safe repr/errors; copy/deepcopy/pickle/forged capability/foreign process rejected. В subprocess явно передать src path из trusted fixture setup, не менять production environment.
3. Windows x64 ABI sizes/field offsets, pointer validity, non-Windows host DWORD/WCHAR trap; BOOL/DWORD error handling, owned allocated security buffers, no double CloseHandle/LocalFree; invalid input не делает native call.
4. Root grammar и bounded component/path-buffer handling; fake reparse/volume/ID/type/ACL/owner/size/link/deletepending mismatch, no repair. Sharing32 отдельно от access denied5. Capture всех flags/access/share/disposition, no truncate/delete/blanket inheritance.
5. Owner→slot order, active/foreign/stale errors, failed reserve cleanup, before-close validation, after-close failed probe invalidates lease; independent probe OPEN_EXISTING/read-write/share0 и cached identity, не DuplicateHandle. Ошибки/повтор close/reused integer не закрывают чужой resource.
6. Failure на каждом create/query/dup/close/free step: closed exact resources, remaining failures sanitized, no false True; forced metadata replacement rejects until explicit abandon. Returned handle metadata не authority; private issuance registry.

Native Windows cases, **обязательны и отдельно помечены**, skip только вне win32:

7. Increasing GetTickCount64 ns, actual ctypes signatures/layout, explicit temp private NTFS root; two owners same/different process, two slots, no file content changes, stable IDs after close/reopen.
8. Inherited slot: bounded child получает только temporary duplicate по HANDLE_LIST и подтверждает ready через собственный test channel. Parent release False, owner.close успешен, новый owner acquire успешен, reserve busy до actual child exit; затем reserve/release True. Native owner HANDLE не наследуется. Отдельно parent abrupt exit при живом bounded child, то же отсутствие overlap. Фикстура не требует E3 и не запускает модель; retained process HANDLE/timeout для своей очистки, не PID search.
9. Native symlink/junction/reparse/hardlink/nonempty/ACL mismatch; штатные operations не меняют посторонние файлы. Если конкретный destructive negative fixture требует отсутствующего OS privilege — отдельный pending case, не blanket pass. Все fixtures только temporary synthetic paths.
10. Повтор100 success/failure cycles, GetProcessHandleCount до/после с учётом стабильной инфраструктуры test runner; без growth. После всех wait/close cleanup temporary tree; никаких handles реального приложения/чужих процессов.

Acceptance expectations не ослаблять ради Mac mocks или missing Windows. В result записать native gate pending при отсутствии Windows и ссылку на точные cases. Available E1 code/portable regression можно завершить и передать **Sol 6.1 High → E2 contract/freeze/red**; весь C1E ещё не принят. При новом противоречии контракта закончить доступную проверку и передать на Astra. Product/БД/ML/frozen старые tests неизменны.
