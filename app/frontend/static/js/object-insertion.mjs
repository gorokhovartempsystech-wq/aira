import { h, modal, toast } from './ui.mjs';

export async function insertTable(ed) {
  const point = await ed.prepareObjectPoint();
  if (!point) return;
  const rows = h('input', {type:'number', min:1, max:100, value:2, class:'input', 'aria-label':'Строки'});
  const columns = h('input', {type:'number', min:1, max:32, value:2, class:'input', 'aria-label':'Столбцы'});
  const body = h('div', {}, h('label', {}, 'Строки', rows), h('label', {}, 'Столбцы', columns),
    h('p', {class:'muted small'}, 'До 100 строк и 32 столбцов, не более 1024 ячеек.'));
  const valid = () => Number.isInteger(Number(rows.value)) && Number.isInteger(Number(columns.value))
    && Number(rows.value)>=1 && Number(rows.value)<=100 && Number(columns.value)>=1
    && Number(columns.value)<=32 && Number(rows.value)*Number(columns.value)<=1024;
  body.addEventListener('input', () => { body.closest('.modal').querySelector('[data-id="insert"]').disabled = !valid(); });
  const result = await modal({title:'Вставить таблицу', body,
    actions:[{id:'cancel', label:'Отмена'}, {id:'insert', label:'Вставить', kind:'primary'}]});
  if (result?.id === 'insert' && valid()) await ed.insertObject('insert_table', {rows:Number(rows.value), columns:Number(columns.value)}, point);
}

export async function insertImage(ed) {
  if (!ed.objectPoint()) return;
  const preparingPoint = ed.prepareObjectPoint();
  // Open within the user gesture, including browsers that disallow a picker
  // after awaiting network I/O. Pending text is committed while it is open.
  const file = await new Promise(resolve => {
    const input = h('input', {type:'file', accept:'.png,.jpg,.jpeg,image/png,image/jpeg', hidden:true});
    const finish = file => { input.remove(); resolve(file); };
    input.addEventListener('change', () => finish(input.files?.[0] || null), {once:true});
    input.addEventListener('cancel', () => finish(null), {once:true});
    document.body.append(input); input.click();
  });
  const point = await preparingPoint;
  if (!point) return;
  if (!file) return;
  if (file.size > 4*1024*1024 || !/\.(png|jpe?g)$/i.test(file.name)) {
    toast('Выберите PNG или JPEG размером не более 4 МиБ.', 'warn'); return;
  }
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for(let i=0;i<bytes.length;i+=8192) binary += String.fromCharCode(...bytes.subarray(i,i+8192));
    await ed.insertObject('insert_image', {data_base64:btoa(binary)}, point);
  } catch { toast('Не удалось прочитать изображение. Попробуйте выбрать файл заново.', 'error'); }
}
