# D03-17A2b2b1 — структурный каталог перемещений Word

4 ноября2026. Frozen acceptance/contract: ba6fd52. Pure source-pinned каталог
paired main-part ranges/members, deterministic digest и fixed diagnostics готов.
[Контракт](d03-17a2b2b1-contract.md), [guide](docx-move-catalog.md).

Red:46failed0.30s (namespace отсутствовал). Initial targeted:46passed0.09s.
Review обнаружил, что XMLParser выносит namespace declarations из attrs mapping;
длинный URI не учитывался в character budget. Independent red:1failed20deselected
0.06s, semantic DOM вызывался раньше отказа. Counter.start_ns теперь учитывает URI.
Добавлены проверки comments/PIs/root metadata paths и mixed Word namespace.
Frozen baseline acceptance/contract неизменны; к own edge tests только3 additions.
Первый отдельный запуск edge test требовал PYTHONPATH tests/acceptance для fixture
helper; повтор с правильной средой подтвердил именно semantic budget failure.

Combined new + old final/visible readers:169passed1.00s. Required full
`bash scripts/check.sh`: **4961passed,45skipped,78warnings,24subtests passed**,
794.71s,exit0. Ruff/format667files green. Final712 hashes match; все704 предыдущих
hashes без изменений. Main V8/схема/счётчики совпадают с D05-06B, ara_test empty,
временных ara_check databases нет; содержимое строк не читалось.
Локальные evidence: `.runtime/d03-17a2b2b1-{red,targeted,review-red,regression,full}.log`,
`d03-17a2b2b1-hashes.json`, `d03-17a2b2b1-runtime.json`.

Нет текстового reading/ML admission, mutation original DOCX или новых API/DDL.
Main-body inline restriction и native Word/paragraph boundary gate сохраняются.
Один plain synthetic Word control снова вернул -1712; source SHA unchanged,
собственный контрольный документ закрыт (cleanup confirmed). Причина, включая
лицензию Microsoft, не установлена. Это не native parity proof; user files untouched.

Следующий отдельный **D03-17A2b2b2** — versioned opt-in итоговый inline move reader
и source-backed batch mapping. Native parity/application admission отдельно;
текущие profile guards остаются. По команде пользователя продолжаем без смены режима.
