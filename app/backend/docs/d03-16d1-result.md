# D03-16D1 — scoped registry и открытие редактора

31 октября 2026, Sol 6.1 High, F05/F11/F12. Реализован d03-16d1-contract.md в новом ara.docx_editor: explicit constructor runtime, passive согласованная recovery inspection, current/recover open и fresh snapshot, scope и новый registry/session epoch. Live open replay не сбрасывает редактор, глобальная open sequence блокирует запоздалые fresh requests. Dirty/clean/selection восстанавливаются точно, история после restart пуста; pending открывается frozen без commit/finalize. Conflict остаётся доступной копией, чужой current/slot не перезаписывается.

Project/document read locks охватывают validation/reply, завершаются до admission; нет outer SQL lock вокруг get_checkpoint initialization. Cached current/working scope читает metadata и длину BLOB, не загружает пакеты. Pending использует single-transaction полный receipt/handle proof. Snapshot/replay повторно проверяют scope после ожидания mutex. Stored corruption не очищается.

Admission учитывает union actual immutable bytes references, candidate + live, без eviction; отказ/ошибка reply/read commit освобождает reservation и не увеличивает sequence. Нативные session/editor изменены только добавлением private read-only retained helpers, AST всех прежних методов сверены с HEAD без изменений. Есть strict detached DTO, bounded counters, native snapshot digest/dirty validation, sanitized errors, first-import/constructor inertness. No global singleton, background timer или secret loading.

Acceptance freeze **7f7e562**, затем **ed6f896** только форматирование с проверкой одинакового AST. Первичный formatting check нашёл длинную строку; критерии/assertions не менялись. Red **18 failed**, 3,56 секунды — новый package отсутствовал. После реализации frozen acceptance неизменна. Финальный targeted **53 passed**, 2 предупреждения, **13,42 секунды**: 18 frozen registry, 19 дополнительных registry edges, 7 checkpoint и 9 reconcile acceptance.

Дополнительные сценарии: до/после commit ACK-loss первого initialization и финального read/admission, две threads/повтор одного ID, чужой base при одинаковых bytes, pending commit/finalize другим controller, reverse selection, scope move/revocation при ожидании actor mutex, старый draft, MAX/replay, retained history/identity union, DTO rollback/isolation, отдельный процесс восстановления и inert import. Дополнительный пример reverse selection исправлен до фиксации own tests: не менялись frozen tests или требование направления.

Первый полный regression run: 2118 passed + 24 subtests, 70 предупреждений, 208,55 секунды. Во время него были добавлены strict Python request binding и пять финальных edge cases; поэтому окончательный результат определяется отдельным повторным gate ниже.

Финальный `bash scripts/check.sh`: **2123 passed + 24 subtests passed**, 70 предупреждений, **208,81 секунды**, exit 0. Ruff/format прошли. После gate production source не менялся. Логи .runtime/d03-16d1-red.log, d03-16d1-targeted.log, d03-16d1-final-check.log.

Отдельная disposable rich DOCX QA: current open exact original, затем восстановление working exact ранее просмотренного reference — 48211 bytes, SHA256 `1239ac34f1e975cc56e97698acfab2f747d75e1b97f759b3794f00db66114529`. Selection exact, dirty restored, history0, replay same actor, old live actor обнаружил новый CP. Original/current/storage revision1 сохранились, working checkpoint2 не изменился открытием. .runtime/d03-16d1-qa.json, собственная DB удалена. Hash-proof reuse прежнего visual reference; нового render/Word запуска не заявляется.

Ограничения D1: нет native command dispatch, save/checkpoint/close bridge, HTTP/application wiring или UI. Пока только ограниченный lifetime registry; production wiring после D3. Working DB V8 автоматически не мигрируется, новые adapters требуют V9. Далее D2 на Sol 6.1 High по отдельному контракту; обычное разрешение продолжать уже получено.

Baseline рабочих схем/ревизий/счётчиков совпал, ara_test пуста, временных ara_check_* нет. Архив/секреты/чужие изменения/старые tests/schema/API/dependencies/runner/tasks/progress не затронуты. Локальный commit без push; свой PostgreSQL оставлен для следующего цикла.
