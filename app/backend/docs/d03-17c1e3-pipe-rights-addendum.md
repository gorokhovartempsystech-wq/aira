# D03-17C1E3 — право чтения атрибутов пишущего pipe

2 ноября 2026. Узкое дополнение к [E3](d03-17c1e3-contract.md) при реализации после freeze `d948ca1`. **Прямое разрешение Никиты в этом чате:** «Да, исправить E2 и продолжить (рекомендую)» на вопрос об одной строке создания пишущего канала и новой проверке; старые tests сохраняются.

Обнаружено по первичным источникам: E2 `IO.client` открывает клиент с GENERIC_WRITE=0x40000000. E3 adoption вызывает GetNamedPipeInfo для проверки client/server end и byte mode. Для write-only handle Microsoft требует одновременно GENERIC_WRITE и FILE_READ_ATTRIBUTES. GENERIC_WRITE содержит права записи атрибутов, но не чтения. SAME_ACCESS duplicate недостающее право не добавляет; произвольное расширение DuplicateHandle не используется. [GetNamedPipeInfo](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-getnamedpipeinfo), [Named pipe rights](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights).

Это документированная несовместимость выбранных прав, **не наблюдённое native Windows падение**: Windows на этом Mac не запускалась. Portable gates до этого дополнения сами по себе её не обнаруживали.

Разрешён ровно один прежний source path: `src/ara/docx_analysis_worker/windows/_io_abi.py`, в `IO.client` access=0x40000080 вместо0x40000000, одинаково для overlapped writer и synchronous diagnostic writer. FILE_READ_ATTRIBUTES=0x80 не даёт FILE_READ_DATA=1. DACL, имя, flags/overlap, direction, peer checks, pending retention, CancelIoEx и остальные E2 APIs неизменны. Обновление реализации E2 обосновано этим дополнением; первоначальный E2 contract/result сохраняется как история.

Новая additive frozen acceptance: `tests/acceptance/test_docx_analysis_windows_guardian_pipe_rights.py`; compile/collect/freeze/red до одной строки исправления. Raw call проверяет оба writer modes, отсутствие read-data bit и сохранение остальных аргументов. Native проверяет GetNamedPipeInfo на обоих концах и на inherited-compatible SAME_ACCESS writer duplicate, без payload/содержимого документов. Старые acceptance/own E2 tests не меняются.

После исправления targeted E1/E2/E3, новый final source/tests hash baseline и полный `bash scripts/check.sh` с read-only DB snapshots. Промежуточный полный прогон до исправления не считается final E3 gate. Native skips остаются pending. Это дополнение текущего E3, новый цикл/функция/статус runner не создаются.
