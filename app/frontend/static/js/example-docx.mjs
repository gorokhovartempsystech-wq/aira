// The tutorial document (F04). It is imported like any DOCX so the backend owns it fully;
// the frontend only marks it as an example and keeps it out of the user's document list.

export const EXAMPLE_TITLE = 'Учебный пример · заявки поддержки';

const BLOCKS = [
  ['h1', 'Система управления заявками службы поддержки'],
  ['h2', '1. Общие требования'],
  ['p', 'Система должна иметь удобный и интуитивно понятный интерфейс для сотрудников поддержки.'],
  ['p', 'Система должна быстро обрабатывать заявки при большом количестве обращений.'],
  ['h2', '2. Работа с заявками'],
  ['ul', 'Сотрудник поддержки создаёт заявку и назначает исполнителя.'],
  ['ul', 'При необходимости заявке присваивается приоритет.'],
  ['ul', 'Заявка содержит тему, описание, категорию, вложения и т.д.'],
  ['h2', '3. Сроки обработки'],
  ['p', 'Система должна регистрировать новую заявку не более чем за 2 секунды.'],
  ['p', 'Регистрация новой заявки в системе занимает не более 2 секунд.'],
  ['p', 'Время регистрации новой заявки не должно превышать 10 секунд.'],
  ['h2', '4. Уведомления'],
  ['p', 'При изменении статуса заявки должно быть обеспечено своевременное уведомление клиента.'],
];

const enc = new TextEncoder();
const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
const crc32 = b => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

function zip(files) {
  const parts = [], central = [];
  let offset = 0;
  for (const f of files) {
    const name = enc.encode(f.name), data = enc.encode(f.data), crc = crc32(data);
    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true);
    lh.setUint16(12, 0x5b21, true); lh.setUint32(14, crc, true); lh.setUint32(18, data.length, true);
    lh.setUint32(22, data.length, true); lh.setUint16(26, name.length, true);
    parts.push(new Uint8Array(lh.buffer), name, data);
    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true);
    ch.setUint16(8, 0x0800, true); ch.setUint16(14, 0x5b21, true); ch.setUint32(16, crc, true);
    ch.setUint32(20, data.length, true); ch.setUint32(24, data.length, true);
    ch.setUint16(28, name.length, true); ch.setUint32(42, offset, true);
    central.push(new Uint8Array(ch.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const size = central.reduce((s, a) => s + a.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, size, true); end.setUint32(16, offset, true);
  const all = [...parts, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((s, a) => s + a.length, 0));
  let p = 0;
  for (const a of all) { out.set(a, p); p += a.length; }
  return out;
}

const x = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';

export function buildExampleDocx() {
  const style = { h1: 'Heading1', h2: 'Heading2' };
  const body = BLOCKS.map(([kind, text]) => {
    const pPr = kind === 'ul' ? '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
      : style[kind] ? `<w:pPr><w:pStyle w:val="${style[kind]}"/></w:pPr>` : '';
    return `<w:p>${pPr}<w:r><w:t xml:space="preserve">${x(text)}</w:t></w:r></w:p>`;
  }).join('');
  const heading = (id, name, size, lvl) => `<w:style w:type="paragraph" w:styleId="${id}"><w:name w:val="${name}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="${lvl}"/></w:pPr><w:rPr><w:b/><w:sz w:val="${size}"/></w:rPr></w:style>`;
  return zip([
    { name: '[Content_Types].xml', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>' },
    { name: '_rels/.rels', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>' },
    { name: 'word/_rels/document.xml.rels', data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>' },
    { name: 'word/document.xml', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document ${NS}><w:body>${body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>` },
    { name: 'word/styles.xml', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles ${NS}><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>${heading('Heading1', 'heading 1', 32, 0)}${heading('Heading2', 'heading 2', 28, 1)}</w:styles>` },
    { name: 'word/numbering.xml', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering ${NS}><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>` },
  ]);
}
