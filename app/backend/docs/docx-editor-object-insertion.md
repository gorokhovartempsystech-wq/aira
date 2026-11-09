# Inserting objects through the existing editor actor

D03-20D, 9 November 2026. Reuse the current `createDocxSession` instance so
insertion, autosave, save and undo share one command sequence.

```js
await editor.edit({action: 'insert_table', value: {rows: 3, columns: 2}});
```

The caret must be collapsed in a supported main-body paragraph. The operation
splits that paragraph at its Unicode offset, inserts an empty table between the
two halves and places the caret at the beginning of the trailing paragraph.
Both text halves and retained formatting survive. The whole insertion is one
undo/redo step. Row/column bounds are 1..100 and 1..32, with at most 1024 cells;
these are technical request bounds. New tables have equal columns and a thin
grid, fitted to the section/column width (maximum six inches).

For cell input the host must enable the existing `table_editor=True` policy
(or the field-safe table editor). Select a cell paragraph using its current
source anchor and use the normal `insert_text` command. No new HTTP endpoint
or separate autosave path is needed. Replay the same command after a lost
response through the actor's `retry()`, not a second insertion.

Unsupported positions, expanded selections and invalid sizes fail before
publishing history. Nested-table insertion, row/column resizing and cell merging
are not provided by this command. Saving/checkpointing and DOCX export use the
existing paths; this backend change does not add a button to Anya's frontend.

## D03-20E — изображения

Команда на том же `/commands`:

```js
await editor.edit({action: 'insert_image', value: {data_base64: encodedBytes}});
```

`encodedBytes` — стандартный канонический base64 переданных пользователем байтов;
путь к файлу, URL или data URL сервер не принимает. Native API:
`EditorSession.insert_image(data, alt_text='', expected_revision=revision)`.
Поддерживаются статический PNG и baseline/progressive JPEG: максимум 4 MiB,
20 млн пикселей. Проверяется структура контейнера, без декодирования пикселей/OCR.
Проверка не гарантирует отображение каждого файла с повреждёнными пиксельными данными.

Вставка разделяет обычный абзац в позиции свёрнутого курсора и помещает картинку
между половинами. Курсор остаётся в начале второй половины. Размер вычисляется
при 96 dpi без увеличения; при необходимости картинка уменьшается пропорционально
до ширины/высоты рабочей области раздела. Для узких колонок используется их ширина.
Вставка в ячейку и расширенное выделение сейчас отклоняются; исходник не меняется.
Одна операция отмены/повтора возвращает весь DOCX, включая media/relationship и курсор.

При повторной вставке тех же байтов media part используется повторно, а drawing ID
выдаётся новый. Существующие части ZIP, связи и оформление не перезаписываются.
Сохранение и повторное открытие проходят обычным протоколом редактора.

Необязательное `alt_text` сохраняется в `wp:docPr@descr` (до 2000 символов).
**Непустое описание пока вызывает явный отказ текущего анализатора**
`unsupported_image_alternative_text`. Не заполнять его автоматически именем файла:
это заблокирует проверку. Визуальное содержимое картинки не анализируется.
Решение об анализе описаний не входит в E; сохранность описания проверяется отдельно.
Новые кнопки frontend и выбор файла остаются интеграцией интерфейса.

9 ноября: D/E вместе с прежним command/HTTP/client набором — 112 passed.
Общий gate и реальная модель проверяются отдельно после фиксации исходников E.

Визуальная регрессия E: новые `Relationship`/`Override` записываются с default
namespace, без префикса. Префиксная форма с корректным URI проходила внутренний
парсер, но LibreOffice отклонял весь пакет. Исправление не сериализует старые
metadata заново; отдельный тест сохраняет обнаруженное условие совместимости.
