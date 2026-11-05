# D05-06B — owned fixture desktop composition

4 ноября 2026, после D05-06A/77408df. Реализуем один programmatic Mac backend
lifecycle: private Home → owned PostgreSQL → D2 upgrade → D1 schema → A SQL bridge
→ semantic fixture supervisor → protected loopback HTTP. Новых product routes нет.
GUI, package launcher/installer, реальные ML weights, Windows native и публичный
license HTTPS остаются отдельными задачами. `FixtureDesktop` и view.fixture=True
явно обозначают fixture. Конфигурация с trusted absolute paths — предусловие;
она не заменяет проверку immutable installation/signing.

Allowed новые `src/ara/desktop/composition/`,
`tests/acceptance/test_desktop_composition*.py`,
`tests/acceptance/test_licensing_client_drain*.py`, этот contract/result/guide/queue.
Единственный старый source для изменения: `src/ara/licensing/client/_runtime.py`,
additive known worker drain. Старые tests/source/migrations/dependencies/runner/
tasks/progress unchanged. Main V8 не изменять. Все native данные — synthetic temp.

## Владение

Frozen `FixtureConfig(home, postgres, upgrade, migrations, license_origin)`;
paths repr-hidden, PgTools/UpgradeTools exact existing types/same bin. Optional
explicit D04 device_provider/clock/transport trusted test ports, repr-hidden,
не разрешение считать fixture HTTP настоящим TLS. Constructor metadata-only.
`FixtureDesktop(config)`: inert, PID-before-lock, uncopyable; start/view/connection/
shutdown(timeout=5). Frozen view: phase,stage,error_code,resources_pending,fixture.
Phases new/starting/ready/stopping/closed/failed. Stages home/postgres/upgrade/schema/
database/analysis/http/running/cleanup. Errors fixed: validation_error,invalid_handle,
desktop_busy,platform_unavailable,startup_failed,startup_timeout,clock_unavailable,
runtime_failed,cleanup_unknown. No paths/SQL/key/document/native diagnostics.

One strong process claim until known cleanup. Thread creation/start outside mutex;
launch acknowledgement before worker native work. Unknown thread start retains
claim forever even if is_alive=False; late Stop never permits ready. Shutdown on
new is inert closed. Timeout exact int/float finite0..5, bool/huge int rejected before
side effects. Caller shutdown bounded, owned controller continues graceful drain.
Continuous startup budget900s includes all stages, checked before/after waits and
before ready; bad/backwards native clock fails closed. No forced thread/process kill.

HTTP readiness and license admission differ: license UI endpoints available, DOCX
forbidden until fresh online grant. Client/store created only after owned Home,
store exactly Home.license. LoopbackServer alone installs LicensedApplication;
existing app built with explicit DocumentRuntime and supervisor, no dev settings.
Controller owns supervisor lifecycle; no second app lifespan owner. No default
secret loading, old routes remain hidden by existing closed allowlist.

Ready monitors existing metadata PG/source/supervisor/server status; failure fences
HTTP and drains, no automatic reset/recovery/adoption. This isn't continuous SQL
health polling. connection returns existing detached LocalConnection only while
ready and not stopping; session capability remains repr-hidden, never in URL/log.

Close order: stop/drain HTTP → finish license worker → supervisor → schema/upgrade
jobs if still pending → SQL source → PG smart shutdown → Home.close. Startup Stop
uses the same handles. Never close DB under accepted HTTP/COMMIT. Unknown child
cleanup retains all dependencies and top claim; no falsely clean/automatic retry.
Current child shutdown APIs may remain pending; controller waits without busy loop.
Known startup failure with known cleanup can end failed/resources_pending=False.

## LicenseClient additive drain

Keep Snapshot fields, existing close()->None (nonblocking invalidation), normal
activation/retry/timeout/store behavior. Add resources_pending()->bool and
shutdown(timeout=5)->bool, PID before locks, same timeout validation. True means
known worker ended and no future activation-store operation from this client.
It does not claim arbitrary native transport handles audited. Already-begun atomic
save may finish; closing must prohibit late access, then await worker before Home.

Thread creation/start outside client mutex, launch intent/pending fence prevents
concurrent workers. Same pending intent coalesces; other/cancelled attempt busy.
Worker waits for launch acknowledgement before I/O. Unknown constructor/start
exception (including after real start) invalidates permit, disables retry, retains
strong client until exit; closed state cannot be overwritten. shutdown does not
infer success from is_alive=False for ambiguous start. Known worker join bounded;
transport/DNS/store may outlive caller deadline without being cancelled/killed.
No changes to license protocol, store files, expiration or server business rules.

## Приёмка

Freeze/red before implementation. Inert/PID/copy/timeout/one-owner, startup Stop,
known startup failures preserve existing Home and permit explicit retry. Unknown
start in isolated process retains claim; no future Home writes after clean stop.
Real temporary Mac PG, loopback HTTP: initial license gate, activate, import/editor
save/export exact DOCX, semantic fixture check with fixture provenance, clean Stop,
restart same IDs/document/result and new online check nonce. Accepted held editor
save finishes before DB/PG/Home release. Held activation save prevents known close
until atomic write ends; never late access. Existing private snapshot unchanged.
License drain before/during startup, blocked transport/store, normal retry, timeout,
PID, unknown Thread construction/start and close race tested separately. Fault
injection is synthetic, not evidence of Windows native/TLS/model readiness.

New test preparation fixes allowed with documented reason, assertions preserved;
old tests immutable. Review additions allowed before full gate. Required
`bash scripts/check.sh`, final hash manifest/previous690 unchanged except approved
client runtime, readonly mainV8 snapshot, factual result and local commit. Continue
next separate cycle under Никита's current autonomous instruction.

Acquisition clarification before freeze: open_home can retain an internal native
record without returning a handle when native cleanup fails. Its public exception
does not prove close. Composition treats a failed open_home call as unknown cleanup,
retains top claim, and requires process restart; it must not infer clean from absence
of a returned Home. Known retry acceptance concerns later failures with issued
handles and proven cleanup. No inspection/release of another component's internals.
