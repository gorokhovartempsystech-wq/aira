# D05-04 — папка данных и идентичность локальной установки

4 ноября 2026. Следующий цикл после D05-03/135e1ad. F02/F03/F12: отдельные данные
desktop, стабильная локальная identity и единственный владелец до запуска БД.
Разрешены новые `src/ara/desktop/data_home/`, `tests/acceptance/test_desktop_data_home*.py`,
этот contract/result/guide и development-queue. Старые source/tests/dependencies,
БД/миграции/runner/tasks/progress не менять. Main V8 не читать и не усыновлять.
Не запускать PG/model/HTTP и не создавать реальные папки профиля при разработке:
приёмка использует только одноразовые синтетические каталоги.

## Интерфейс и владение

`default_root()->Path` явно определяет стандартную папку без её создания:
macOS — pwd.getpwuid(euid).pw_dir/Library/Application Support/AIRA;
Windows — SHGetKnownFolderPath(LocalAppData,flags0,tokenNULL)/AIRA.
Не брать путь из HOME/LOCALAPPDATA/environment/config. Unsupported OS отклоняется.

`open_home(root:Path|None=None)->DataHome` явно создаёт только собственную leaf
папку под существующим проверенным parent и забирает эксклюзивное владение.
Импорт не вызывает I/O/native/entropy/threads. Root должен быть absolute Path
без `..`, NUL и пустого leaf (сам filesystem root запрещён); symlinks/reparse и чужая/неподходящая папка запрещены. Нет chmod существующих
каталогов, автоматического переноса или поиска иных копий данных.

DataHome выдаётся только factory; PID проверяется до mutex, copy/deepcopy/pickle
запрещены. `identity()` возвращает frozen InstallationIdentity(installation_id,
user_id,project_id). `path(name)` возвращает один из root/postgres/analysis/license/
backups; неизвестное имя — validation_error. Эти методы доступны только open.
Это server-owned локальная область документов, не пользовательский аккаунт.

`view()` возвращает frozen HomeView(phase,error_code,resources_pending): open,
closing,closed,failed. Пока ресурсы удерживаются или освобождение не подтверждено,
resources_pending=True. `close()->bool`: True только после известного освобождения;
повтор closed=True, concurrent closing=False. Ошибка закрытия → failed/quarantine,
False; новый open того же root в этом процессе не обходит неизвестный результат.
Никакого delete/unlink lock files, принудительного unlock или PID-based kill.

Реиспользовать существующие public macOS/Windows acquire_owner/RuntimeOwner.close
на ROOT приложения. Supervisor получает ДРУГОЙ root/analysis и собственную блокировку.
Не reserve_slot на глобальном владельце приложения. До identity/child mutations
обязательно успешно захватить OS owner. Strong process registry удерживает открытые
и failed ресурсы даже при потере ссылки caller. Ключ — проверенная identity корневого
каталога, а не только строка пути. Межпроцессная блокировка остаётся OS-authoritative.
После ошибки acquisition освободить только свои ресурсы; если close неизвестен,
оставить quarantine. Нельзя оставить блокировку из-за обычной validation failure.

HomeError — fixed code/message без raw paths/OS exceptions/данных: validation_error,
invalid_handle,home_busy,home_unavailable,home_recovery_required,unsupported_platform.
Unknown code → home_unavailable. Repr не раскрывает root/OS identity/native handles.
Default-root read может возвращать путь явно; его не логировать автоматически.

## Права и каталоги

macOS: пройти parent по dirfd/O_NOFOLLOW; owner каждого ancestor root/current euid,
без group/world write, кроме root-owned sticky temp ancestor. Новый root0700,
существующий root exact0700/current euid. Identity files0600/single-link/regular/
current uid, no FIFO/symlink; bounded no-follow/nonblocking opens. Сохранять проверенный
root FD и сверять identity pathname во время инициализации. Все временные FD закрыть.

Windows: known folder GUID F1B32785-6FBA-4FCF-9D55-7B8E7F157091; освобождать PWSTR
CoTaskMemFree. Только local fixed NTFS, проверенные non-reparse ancestors, retained
handles. CreateDirectoryW с private protected DACL user/System/Admin, как у C1E1.
Проверить существующую папку, не исправлять чужой ACL. Identity file создаётся с
explicit private protected file DACL, non-inheritable handle. Native Filesystem/
Security helpers допустимо реиспользовать без изменения старого кода; для nonempty
identity проверять size<=1024 отдельно от zero-size lock file contract.

После подтверждения identity создать/проверить только postgres,analysis,license,
backups — такие же private directories. PostgreSQL data directory внутри postgres
здесь ещё не создаётся. Не сканировать и не менять содержимое уже существующих
валидных child directories. Непредусмотренные root entries → recovery_required. Сверить допустимые имена
до создания owner file в существующем root и повторить проверку после OS claim.
Никаких secret reads/writes: identity не содержит ключ лицензии/пароли/device ID.

## Постоянная identity и прерванный первый запуск

`identity.json`, <=1024bytes, UTF8 strict JSON, exact keys schema_version и
installation_id. schema_version="aira-data-home/1"; installation_id — canonical
lowercase UUIDv4, nonnil. Duplicate/unknown fields, invalid bytes/UUID —
home_recovery_required. Файл ни при каких штатных повторах не переписывается.

Из installation UUID выводить user_id=uuid5(installation_id,"aira/local-user/1")
и project_id=uuid5(installation_id,"aira/local-project/1"). Данные в БД позже должны
проверяться против этих IDs; старые dev fixed UUID автоматически не заимствовать.

Первый запуск допустим только если root содержит runtime.owner и, возможно,
единственный внутренний staging `.identity.pending`. При отсутствии final identity
наличие любых child dirs или пользовательских/неизвестных files означает
recovery_required: не выдавать новые IDs поверх возможной существующей БД.

Под OS owner: создать staging EXCL/private, записать bytes полностью, подтвердить
flush; атомарно опубликовать БЕЗ замены существующего identity.json; подтвердить
durability barrier до создания child dirs или передачи identity caller.
Darwin: renameatx_np с RENAME_EXCL=4, fsync file/parent и F_FULLFSYNC=51; Windows:
FlushFileBuffers и MoveFileExW(WRITE_THROUGH=8), без REPLACE/COPY flags. Не fallback
на перезапись при конфликте или неподдержанной native операции.

Если после сбоя в pristine root остался корректный staging, повтор использует тот
же UUID и завершает публикацию. Некорректный незавершённый staging можно удалить
ТОЛЬКО после доказательства pristine layout и private single-link regular staging
<=1024bytes: это собственный неопубликованный temp, рядом нет userdata. При чужом
файле/каталоге, unsafe staging или повреждённом final ничего не удалять и не генерировать.
Если final существует и рядом остался staging — recovery_required; не угадывать,
какой документ новее. Если final корректен и child dirs отсутствуют после сбоя,
повтор создаёт только недостающие private dirs с прежней identity.

Ошибка flush/write/publication не возвращает готовую DataHome и не запускает другие
компоненты. Published final никогда не удалять при rollback; повтор читает его же.
Закрытие DataHome сохраняет все данные. Гарантия ограничена подтверждёнными OS
операциями: не обещать восстановление после произвольной порчи носителя.

## Приёмка и следующий этап

Freeze/red до implementation. First/reopen stable IDs; no overwrite/missing final
with userdata; concurrent process busy; separate analysis owner; strong retention;
close/reopen/failed close quarantine; PID/copy; malformed identity и unsafe root/
file/parent, mode/owner/link/reparse/FIFO. Crash cutpoints write/flush/publish/after
publish; повтор не теряет опубликованный UUID и не касается пользовательского sentinel.
Known folder/Windows ACL/native API fixtures плюс отдельный pending Windows gate.
Native macOS на disposable dirs; никакого реального профиля/Main V8.

Targeted/full/hash/main V8 snapshot/result/local commit. Ошибки подготовки новых
tests можно исправить с записью причины без ослабления assertions; старые tests
не меняются. Higher-level bootstrap обязан удерживать Home до завершения HTTP,
supervisor, DB engines и PG children; этот компонент не угадывает их жизненный цикл.
Далее отдельный PostgreSQL bootstrap/schema backup/composition, не внутри D05-04.

Native preflight4ноября: temporary macOS dir + existing acquire_owner; fsync(file),
F_FULLFSYNC, renameatx_np(NOREPLACE), fsync(directory), повторный F_FULLFSYNC прошли.
Второй rename дал EEXIST и сохранил оба файла; временные данные удалены. Первый
probe не нашёл ara без PYTHONPATH; повтор с PYTHONPATH=src прошёл, source не менялся.

Источники: [Apple rename ABI](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/sys/stdio.h),
[Known folders](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid),
[SHGetKnownFolderPath](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath),
[CreateDirectoryW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createdirectoryw),
[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw).
