# D03-17C1E4 — передача после реализации E3

2 ноября 2026. Это handoff следующего design/implementation, не готовый контракт или source E4. [C1E](d03-17c1e-design.md), [E3 contract](d03-17c1e3-contract.md), [E2](d03-17c1e2-contract.md). Продуктовый scope, C1A/B/C и реальные engine/SQL не расширяются. E3 available/native результаты читать в его result, не выводить из этого документа.

**Уточнение 2 ноября:** вопросы ниже разобраны в [точном контракте E4](d03-17c1e4-contract.md), [результат проектирования](d03-17c1e4-design-result.md). Три owners, startup admission gate, bounded renew receipt с отдельным caller acceptance, Stop без очереди, composite candidate и cleanup определены. Source/tests E4 ещё отсутствуют. Design gate завершён, следующий implementation — Sol6.1 High; этот handoff сохранён как основание, повторно проектировать его не требуется.

## Что зафиксировать перед кодом

E3 `FixtureLaunch` выдаётся до I/O, но start/process poll/finish_close принадлежат одному launch thread. После успешного start доступны отдельные E2 endpoints. E2 с первой submission закрепляет endpoint за I/O thread. Поэтому S требует трёх владельцев: retained launch/cleanup thread, control writer owner и data pump. Caller Stop signal-safe, не poll/close чужого pending/event. Сам по себе mutex не передаёт E2 ownership.

**Нужен exact E4 контракт на Astra6 High**, затем реализация Sol6.1 High. Зафиксировать:

- Публичные методы driver и значения их ACK: какой thread вызывает initial permit/renew, что означает timeout caller, если native write уже частично или полностью прошёл, как sequence/caps и lease обновляются после Stop. Бounded50ms delivery остаётся; нет очереди renew поверх незавершённого write и нет ложного ACK из одного queue.put.
- Как driver предоставляет capabilities control writer owner и pump только после setup; кто и когда закрывает каждый endpoint, как finish_close launch thread узнаёт quiescence без чужого poll. Не сбрасывать `_io_thread` и не closing event из чужого активного wait set. Failed setup pending обслуживается launch thread, не pump.
- Exactly bounded lifecycle commands/status mailboxes: один launch worker и pump, Stop coalescing, отсутствие thread/queue growth при зависшем native create или cancellation. Кого ждёт `.close(timeout=5)` и что остаётся strongly retained при False; Stop не ждёт close.
- Composite candidate: armed+EOF; request complete+EOF; ready/stages/result+eventsEOF; closed(clean,0,True)+statusEOF; actual G exit0/outer count0; live current D/L и no Stop/H. DTO `resources_closed` не M proof/SQL ACK. Data pump не пишет SQL; C1A/B остаются authority публикации.
- No lost late tail/error: bounded drain<=2s; candidate не появляется до всей композиции и отзывается при последующем Stop/fault. Одна immutable reply<=4MiB, bounded decoders/transient copies, metadata mutex без wait/decode/user callbacks.
- Portable barriers/fault matrix между тремя threads и native actual-process tests. Дополнить deferred native cases: G death after known M startup, allowlist/event rights, active-process-limit rejection/external Job conflict,100 attempts HANDLE/thread count, backpressure/cancel/suspend. Missing environment по-прежнему skip/pending, не pass.

E3 умеет запускать bounded synthetic fixture, его reply не B1. E4 тоже не включает реальные weights или production Windows wiring. Unknown pre-return и restart durable fence остаются C1F gate; успешный Mac regression не разрешает его обойти.

Это уточнение уже учтённого E4, не новый ID/дополнительный цикл. Перед E4 implementation необходимы отдельные contract/frozen acceptance/red. Source/tests E3 после final gate не менять ради удобства driver; найденный конфликт зафиксировать отдельно.
