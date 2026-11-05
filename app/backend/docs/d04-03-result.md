# D04-03 — онлайн-клиент лицензии

4 ноября 2026. [Контракт](d04-03-contract.md) выполнен: native device identity,
atomic public activation state, проверенный HTTPS и process-local startup permit.
Каждый новый запуск требует свежего ответа сервера. Ошибки сети, повреждённая
активация, чужое устройство, истечение срока и ненадёжные часы не дают доступа.
Повтор/тайм-аут/close не создают дополнительные workers и не принимают поздний ответ.
Даже завершившаяся после close запись identity не открывает доступ.

macOS использует IOKit, Windows — SMBIOS UUID; наружу только versioned digest.
На диске нет ключа/срока/offline permit. Изменение зависимости ограничено переносом
уже используемого httpx>=0.27,<1 в runtime; версии пакетов не обновлены.
[Руководство подключения](license-client.md).

Freeze **d4a6b23**:89 independent cases +1 Windows skip; red72failed/17errors0.81s.
Первая реализация:89passed/1skipped0.73s. Дополнительные review tests проверили
Windows replace ABI, save delay beyond deadline, corrupt identity recovery,
check-response license mismatch и инертные конструкторы; native Windows store
отдельно skipped. Ранее frozen tests/assertions не изменялись.

Совместно policy/server/client: **187passed,2skipped**,4.02s.
`bash scripts/check.sh`: **4289passed,43skipped,24subtests,79warnings**,exit0,
658.05s. Ruff/format green.582 final hashes unchanged; все570 прежних файлов
совпали, кроме заранее разрешённого переноса HTTPX в pyproject.toml.
Read-only snapshot: main `0008_docx_edit_drafts`,schema/counts прежние;
ara_test пустая, временных тестовых БД0. Логи/manifest/snapshot в
`.runtime/d04-03-{red,targeted,regression,full}.log`, `d04-03-hashes.json`,
`d04-03-runtime.json`. Первичная проверка старого manifest отдельно обнаружила
ожидаемую разрешённую правку pyproject; новый gate manifest учитывает именно её.

Настоящий macOS native identity прочитан в изолированном subprocess дважды:
равный digest, stdout только native-ok. Windows native identity/storage требуют
Windows. In-process server integration проверяет реальные HTTP/core/SQL в disposable
БД, но использует явно fixture transport; production TLS не объявляется проверенным.
DNS/OS может пережить socket timeout: доступ инвалидируется, новый worker не создаётся
до завершения старого. Это привязка штатного клиента, не аппаратная аттестация.

Старый development app ещё не использует guard. Публичный сервер не развёрнут,
production keys не создавались. Frontend/модель/установщики/native release gates
остаются отдельными. Следующий **D05-01** — защищённая локальная HTTP-граница и
сохранение уже принятого текста при истечении лицензии. Draft подготовлен; source
следующего цикла начнётся после этого локального commit.
Ориентир **14–29 самостоятельных циклов**, D04-03 вычтен один раз.
Текущая Astra, продолжаем без смены режима по команде Никиты.
