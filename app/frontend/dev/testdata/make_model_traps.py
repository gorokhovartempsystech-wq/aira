"""Документ-ловушка для модели AIRA: котики, сурикаты, размытые формулировки, опечатки,
противоречия и дубли в неудобной для модели форме. Пишет DOCX и JSON-ключ с ожиданиями.

Запуск: python make_model_traps.py model-traps-cats-meerkats.docx model-traps-key.json
"""
import json, sys, zipfile
from xml.sax.saxutils import escape

OUT_DOCX, OUT_KEY = sys.argv[1], sys.argv[2]

# kind: F — размытая формулировка, C:<пара> — противоречие, D:<пара> — дубль, OK — чистое требование (ложное срабатывание = ошибка модели)
B = []
def H(level, text): B.append(("h", level, text))
def P(text, kind="", trick=""): B.append(("p", text, kind, trick))
def LI(text, num, kind="", trick=""): B.append(("li", text, kind, trick, num))
def T(rows): B.append(("t", rows))

H(1, "ТЗ: сервис учёта котиков и сурикатов «Мурнора»")
P("Версия 0.0.1-мяу. Документ составлен главным сурикатом по итогам совещания с котиками.")

H(2, "1. Общие требования")
P("Сервис должен работать хорошо, красиво и мурчательно, чтобы котикам было приятно.", "F", "субъективные слова + неологизм «мурчательно»")
P("Интерфейс должен быть интуитивно понятным для сурикатов любого возраста.", "F", "контроль: классическая размытая формулировка")
P("Система должна бысто и удобна показывать список котиков.", "F", "опечатки в размытых словах: «бысто», «удобна»")
P("Страница сурикатов должна загружатся достаточно шустро.", "F", "синоним вне словаря: «шустро», «достаточно»; опечатка «загружатся»")
P("Приложение должно моментально реагировать на мяуканье пользователя.", "F", "синоним «моментально»")
P("Отклик системы на действия котика должен быть оптимальным.", "F", "«оптимальный» без критерия")
P("Поиск котиков должен быть максимально эффективным и надёжным.", "F", "«максимально эффективный», «надёжный»")
P("Сервис должен выдерживать разумное количество одновременно мурчащих котиков.", "F", "«разумное количество»")
P("Главный сурикат при желании может настроить в системе всё что угодно.", "F", "«при желании», «всё что угодно»")
P("Желательно, чтобы суррикаты видели ежедневный отчёт о котиках.", "F", "«желательно» + опечатка «суррикаты»")
P("Котик может, но не обязан, получать уведомления о новых сурикатах.", "F", "необязательность «может, но не обязан»")
P("Система учитывает котиков, сурикатов, хомяков итд.", "F", "открытый перечень без пробелов: «итд»")
P("Каждому животному назначается корм, лежанка, игрушки и прочее.", "F", "открытый перечень «и прочее»")
P("Котики и/или сурикаты могут голосовать за новое название сервиса.", "F", "«и/или»")
P("Это должно происходить своевремено и без лишней суеты.", "F", "неясное «это», опечатка «своевремено», «без лишней суеты»")
P("Лимит корма на одного котика: TBD, уточнить у главного суриката.", "F", "заглушка TBD")
P("Сервис должен быть user-friendly и работать ASAP.", "F", "англицизмы: user-friendly, ASAP")
P("Сервис хранит не более 500 карточек котиков.", "OK", "контроль ложных срабатываний: точное требование")
P("Карточка котика содержит кличку, дату рождения и окрас.", "OK", "контроль: закрытый перечень")

H(2, "2. Сроки и расписание")
P("Регистрация котика занимает не более 3 секунд.", "C:reg", "«не более 3» против «не менее 5»")
P("Корм выдаётся не позднее пяти минут после мяуканья.", "C:food", "число словами против цифр")
P("Сурикат заступает на пост каждые 2 часа.", "C:post", "разные единицы: часы и минуты")
P("Сервис работает круглосуточно, без перерывов.", "C:night", "противоречие разнесено в разные разделы")
P("Котикам разрешено удалять сурикатов из списка друзей.", "C:delete", "антонимы «разрешено» / «запрещено»")
P("Регистрация котика занимает не менее 5 секунд.", "C:reg", "пара к «не более 3 секунд»")
P("Корм выдаётся не ранее чем через 10 минут после мяуканья.", "C:food", "пара: «не ранее 10 минут»")
P("Сурикат заступает на пост каждые 30 минут.", "C:post", "пара: 30 минут против 2 часов")
P("Вес котика задаётся в диапазоне от 10 до 2 кг.", "F", "невозможный диапазон внутри одного требования")
P("Уведомление о голодном котике отправляется мгновенно, но не раньше чем через час.", "F", "противоречие внутри одного предложения")
P("Котик получает 3 порции корма в день.", "C:portion", "противоречие с таблицей ниже (не более 1 порции)")

T([["Животное", "Порции корма в день", "Время реакции на мяуканье"],
   ["Котик", "не более 1 порции", "быстро"],
   ["Сурикат", "достаточно", "оперативно"],
   ["Хомяк", "2–3 порции", "ну, как получится"]])

H(2, "3. Котики и сурикаты")
P("Каждый котик должен иметь уникальную кличку.", "D:name", "дубль-перефраз")
P("Сурикат может добавить котика в избранное.", "D:fav", "дубль с инверсией залога")
P("Система хранит фотографию каждого суриката.", "D:photo", "дубль с опечаткой")
P("Двух котиков с одинаковыми кличками в системе быть не может.", "D:name", "пара к «уникальная кличка»")
P("Добавление котика в избранное доступно сурикату.", "D:fav", "пара")
P("Система хранит фотографию каждого сурриката.", "D:photo", "пара с опечаткой «сурриката»")
P("Сурикат всегда видит всех котиков в списке.", "C:see", "«всегда» против «никогда»")
P("Сурикат никогда не видит котиков в списке.", "C:see", "пара")
P("Котикам запрещено удалять сурикатов из списка друзей.", "C:delete", "пара к «разрешено»")

H(2, "4. Порядок кормления")
P("Кормление котика выполняется так:")
LI("Сурикат по возможности проверяет миску.", 2, "F", "«по возможности» в нумерованном списке")
LI("Котик ест сколько захочет.", 2, "F", "неизмеримое «сколько захочет»")
LI("Сурикат делает всё как надо и т. п.", 2, "F", "«всё как надо», «т. п.» с пробелом")
LI("После еды котик спит не менее 14 часов в сутки.", 2, "OK", "контроль: измеримо")

H(2, "5. Надёжность и безопасность")
P("Данные котиков должны быть надёжно защищены.", "F", "«надёжно» без критерия")
P("Пароль главного суриката должен быть сложным.", "F", "«сложный» без правил")
P("Резервные копии делаются регулярно.", "F", "«регулярно»")
P("Доступ к карточкам сурикатов есть только у своих.", "F", "неясная роль «свои»")
P("Ночью, пока котики спят, сервис недоступен.", "C:night", "пара к «круглосуточно» из раздела 2")
P("СИСТЕМА ДОЛЖНА РАБОТАТЬ БЫСТРО!!!", "F", "капс и восклицательные знаки")
P("Система должна работать быстро, удобно, надёжно, красиво, современно, гибко, интуитивно понятно и вообще чтобы всем нравилось, особенно котикам, но сурикатам тоже, если они не против, а если против, то по возможности как-нибудь договориться.", "F", "длинное предложение, много размытостей сразу")
P("Время ответа сервиса не превышает 2 секунд при 100 одновременных пользователях.", "OK", "контроль: точное требование")

# ---------- DOCX ----------
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
def run(text, bold=False):
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
def para(text, style=None, num=None, bold=False):
    ppr = ""
    if style or num:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + (
            f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num}"/></w:numPr>' if num else "") + "</w:pPr>"
    return f"<w:p>{ppr}{run(text, bold)}</w:p>"
def table(rows):
    widths = [2000, 3600, 3400]
    border = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="999999"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    body = "".join("<w:tr>" + "".join(f'<w:tc><w:tcPr><w:tcW w:w="{widths[i]}" w:type="dxa"/></w:tcPr>{para(c, bold=(r == 0))}</w:tc>'
                                      for i, c in enumerate(row)) + "</w:tr>" for r, row in enumerate(rows))
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    return f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>{border}</w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>'

xml, key = [], []
for b in B:
    if b[0] == "h": xml.append(para(b[2], f"Heading{b[1]}"))
    elif b[0] == "p":
        xml.append(para(b[1]))
        if b[2]: key.append({"text": b[1], "kind": b[2], "trick": b[3]})
    elif b[0] == "li":
        xml.append(para(b[1], num=b[4]))
        if b[2]: key.append({"text": b[1], "kind": b[2], "trick": b[3]})
    elif b[0] == "t":
        xml.append(table(b[1]))
        key.append({"text": "не более 1 порции", "kind": "C:portion", "trick": "пара в таблице к «3 порции в день»"})
        for t, trick in (("быстро", "размытость в ячейке таблицы"), ("достаточно", "размытость в ячейке таблицы"),
                         ("оперативно", "размытость в ячейке таблицы"), ("ну, как получится", "размытость в ячейке таблицы")):
            key.append({"text": t, "kind": "F", "trick": trick, "cell": True})

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{"".join(xml)}'
            '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701" '
            'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
def heading(sid, name, size, lvl):
    return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
            f'<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="{lvl}"/></w:pPr><w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>')
styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {W}><w:docDefaults><w:rPrDefault><w:rPr>'
          '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault>'
          '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
          + heading("Heading1", "heading 1", 32, 0) + heading("Heading2", "heading 2", 26, 1) + "</w:styles>")
def lvl(fmt, text):
    return (f'<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>')
numbering = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering {W}>'
             f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/>{lvl("bullet", "•")}</w:abstractNum>'
             f'<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="singleLevel"/>{lvl("decimal", "%1.")}</w:abstractNum>'
             '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>')
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
with zipfile.ZipFile(OUT_DOCX, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>')
    z.writestr("_rels/.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="word/document.xml"/></Relationships>')
    z.writestr("word/_rels/document.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/styles" Target="styles.xml"/><Relationship Id="rId2" Type="{REL}/numbering" Target="numbering.xml"/></Relationships>')
    z.writestr("word/document.xml", document)
    z.writestr("word/styles.xml", styles)
    z.writestr("word/numbering.xml", numbering)
json.dump(key, open(OUT_KEY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok", len(key), "ловушек")
