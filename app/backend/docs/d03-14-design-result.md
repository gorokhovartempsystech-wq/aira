# D03-14-design — результат проектирования

31 октября 2026. Прямой запрос Никиты после переключения на Astra 6: спроектировать разбиение/склейку абзацев и отмену изменений. Завершён **этап проектирования**, а не реализация D03-14 и не функциональная приёмка будущего редактора.

Подготовлены [техническое решение](d03-14-design.md) и [ограниченный контракт D03-14](d03-14-contract.md). Обновлены ссылки/следующий шаг в development-queue.md и docx-editor-api.md. Основной продуктовый объём не менялся; source, tests, DB schema, зависимости, runner/tasks/progress/AGENTS и frontend остались прежними.

## Зафиксированные решения

- Paragraph anchor + code-point offset, отдельные pure SplitParagraph/JoinParagraphs. Перенос styled runs и namespace context, сохранение package вне выбранных p. Явные правила пустых/нулевых nodes, Unicode, native controls и paragraph identity attributes.
- Первая склейка требует совместимых pPr, а не только равных style IDs. Не обещать сохранность оформления при Heading+Normal без resolver наследования. Консервативные gates и перечень копируемых свойств/attributes зафиксированы до реализации.
- Общая snapshot-история DOCX: один пользовательский жест — одно состояние, точные undo/redo, selection/typing format связаны с историей, autosave не сбрасывает стек. Compose split+next-style атомарно; не считать две опубликованные команды одной.
- Разделены session revision, package hash и storage revision. Отмена уже сохранённого изменения становится новой CAS-записью; ACK-loss разрешается durable receipt, а не сравнением текста. Старый single-span /draft не используется для новых structural payloads без отдельного совместимого протокола.
- Три последовательных цикла: D03-14 pure operations; D03-15 история/controller; D03-16 durable working state/recovery. Клавиши/UI и расширение разных styles/сложных элементов имеют отдельную последующую приёмку.

## Проверка дизайна

Код исследован непосредственно: существующий DocxSession, range/structure/formatting, projection/lexical readers, paragraph persistence, legacy recovery и text history UI. Синтетический read-only probe подтвердил различие наследуемых AIRA Heading1/Normal (16/11 pt) при отсутствии прямого run rPr и next=Normal; записаны только технические факты в ignored .runtime/d03-14-design-probe.json. Новый DOCX-exporter при этом не реализовывался.

Первичные Microsoft/W3C ссылки встроены рядом с обоснованиями. Проверены XML namespace scoping, paragraph style/run inheritance, w:next и имена сложных атрибутов. Проектные ограничения явно отделены от поведения Word. Контракт содержит 16 именованных групп будущей acceptance B01–B16; исполняемые frozen tests будут подготовлены и проверены красными до кода D03-14. Таблица сценариев не считается пройденными тестами новой функции.

Проверены локальные ссылки, парность fenced blocks, уникальность B01–B16 и `git diff --check`. Полный `bash scripts/check.sh`: **1710 passed, 24 subtests passed**, 69 предупреждений, **169,56 секунды**, exit 0. Это регрессия существующей реализации; новые split/join/undo не объявляются работающими. Лог .runtime/d03-14-design-check.log. Изменений source/tests после gate нет; повторный полный прогон для редакционных уточнений не требовался.

Итоговый snapshot схемы/ревизии/счётчиков совпал с baseline, ara_test пуста, временных ara_check_* нет. PostgreSQL штатно остановлен с сохранением данных. Секреты и архив пользователя не читались, чужие dirty-файлы сохранены, внешних публикаций/сообщений не было.

## Передача в реализацию

Рекомендуемый следующий режим — **Sol 6.1 High**. Начать с чтения current-product-scope.md и d03-14-contract.md, подготовки синтетической acceptance/проверки fixtures, её freeze/red; затем реализовать только boundaries. Критерии будущих D03-15/D03-16 отдельно фиксируются до каждого цикла. До завершения этих циклов не заявлять сквозную готовность структурного редактирования, undo UI или восстановления после перезапуска.
