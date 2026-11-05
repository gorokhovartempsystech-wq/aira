# D03-17C1E3 — вопрос о startup proof до реализации

2 ноября 2026, Sol6.1 High, после проверенных E1 `ab5d2f2` и E2 `134633c`. E3 source/acceptance/contract ещё не создавались, freeze E3 отсутствует. Остаток28–43 не меняется, E3 не объявляется выполненным. Это handoff архитектурного вопроса, не сообщение об обнаруженном Windows runtime баге.

**Статус после проектирования 2 ноября:** вопрос разобран в [контракте E3](d03-17c1e3-contract.md). JOB_LIST сохранён; неизвестный pre-return исход не подтверждает cleanup и не разрешает новый анализ. Сильное обещание автоматического crash recovery заменено явным blocked/recovery gate C1F. Ниже исходная постановка вопроса, а не текущий блокер реализации E3. Теперь **Sol6.1 High для D03-17C1E3**; freeze/source ещё впереди.

## Что требует уточнения

[C1E §1/§4](d03-17c1e-design.md) выбирает JOB_LIST и два nested Job; при этом утверждает отсутствие startup orphan window и автоматическое прекращение G/M при смерти владельца в любом cut point, включая создание процесса. Для этой схемы нужны разные гарантии:

1. Новый процесс не выполняет свой код до назначения Job. Это явно описано Microsoft и обосновывает JOB_LIST вместо отдельного create→Assign.
2. При прекращении **самого caller, пока CreateProcessW ещё не вернулся**, не остаётся suspended child после последнего close Job HANDLE. Здесь требуется также порядок удержания/закрытия Job reference, назначения процесса и cleanup незавершённого creation.

Изученные [UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute) и [разбор Microsoft](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812) описывают назначение Job при creation и до исполнения initial thread. Они не дают явного отдельного утверждения о lifetime/rollback во втором сценарии. [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) описывает kill при последнем close для связанных процессов. Из этих фактов **в этом проходе не получен самостоятельный proof** сильного утверждения «caller death внутри API всегда очищает любой startup child».

Это ограничение доказательства/контракта, **не доказанная небезопасность Windows API**. Windows здесь не запускалась; реального orphan, неправильного Job membership или kernel failure не наблюдали. Community Q&A из поиска не использованы как авторитетное основание поведения ядра. Не маскировать неизвестность mocks, проверкой IsProcessInJob только после успешного возврата или тестом, в котором внешний harness держит лишний Job HANDLE и меняет last-close условия.

## Почему вопрос нужен до source

E1/E2 подтверждают available portable primitives, не Win32 creation semantics. E3 launcher отвечает за исход, когда PID/process HANDLE ещё не возвращены caller; нельзя задним числом считать такой child owned или искать/убивать его по имени/старому PID. Простая ветка «после возврата проверить membership» не покрывает смерть до возврата. Сильное обещание cleanup нельзя объявить реализованным по одному correctly typed binding.

При этом сохраняются консервативные границы C1: engine только после prepared→GO→armed и полного run; нет нового inference/publication старой попытки; inherited slot и SQL reconciliation остаются раздельными fences. **Не отменять их и не признавать cleanup по одному свободному slot**, если речь о неизвестном process outcome.

## Что решить на Astra 6 High

- Уточнить exact обещание на pre-return cut point. Можно ли обосновать более сильный cleanup достаточным первичным источником/допустимой native проверкой, либо честно сохранить fail-closed unknown/busy/recovery без заявления автоматического физического завершения? Сам факт отсутствия явного документа не требует удаления JOB_LIST.
- Для пути с неизвестным creation outcome явно задать сохранение slot/admission, durable SQL state, возврат ошибки caller и условия нового запуска. Какие facts реально доступны выжившему S/G, какие утрачены после обоих crash, чего нельзя заявлять новому S.
- Разделить pre-return death, failed API return, membership verification failure до Resume и неоднозначный Resume outcome. Определить cleanup только по exact retained handles там, где они реально получены; никакой alternative PID kill.
- Сохранить original caller-only J_attempt HANDLE / guardian-only J_model HANDLE. Если нужен broker/другой lifetime owner, это пересмотр выбранной схемы, а не скрытый fallback/передача лишнего Job HANDLE child. Не добавлять службу/установщик автоматически.
- Согласовать будущий native crash test с безопасной очисткой синтетических процессов, не меняя проверяемое last-close условие и не оставляя неуправляемые suspended fixtures. Mac mocks этого не доказывают; native gate может остаться внешним блокером.
- После выбора подготовить точный E3 contract: roles/handles/creation outcomes/holder API, отдельные owner I/O threads, cleanup/quarantine при startup failure, обязательная acceptance. E2 thread ownership и pending-buffer lifetime уже frozen; silent transfer/poll/close из чужого потока не допускаются. E4 control dispatcher и data pump должны учитывать это явно.

## Передача и проверки

**Следующий режим: Astra 6 High — уточнить D03-17C1E3 startup proof/recovery.** После завершения проектирования — Sol6.1 High для E3 implementation/freeze/red, затем E4, если новых противоречий нет. E1/E2 не переписывать ради нового обещания, runner/tasks/progress не менять.

Последний source gate E2: **3378passed+24subtests,10native Windows skipped,75warnings,398,68s,exit0**; runtime snapshots equal, main V8 unchanged. После gate source/tests не менялись, hash snapshot совпал. Дальнейшие изменения только documentation/handoff; дополнительный fake red E3 не имитировался. Чужие dirty файлы, секреты, архив, рабочие БД и remote репозиторий не затрагивались.
