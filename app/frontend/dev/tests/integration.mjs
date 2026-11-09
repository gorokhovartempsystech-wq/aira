// Run against a disposable dev stand only: creates synthetic documents and activates its licence stub.
// AIRA_UI_ORIGIN=http://127.0.0.1:8017 node app/frontend/dev/tests/integration.mjs
// Requires Playwright; optional PLAYWRIGHT_MODULE and AIRA_CHROME_EXECUTABLE point to existing installs.
import assert from 'node:assert/strict';
import {readFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.AIRA_UI_ORIGIN || 'http://127.0.0.1:8017';
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/);
const browser = await chromium.launch({headless:true, ...(process.env.AIRA_CHROME_EXECUTABLE ? {executablePath:process.env.AIRA_CHROME_EXECUTABLE} : {})});
const output = new URL('./results/', import.meta.url);
await mkdir(output, {recursive:true});
const errors = [];
const deadline = setTimeout(() => { console.error('UI integration exceeded 4 minutes'); process.exitCode=1; void browser.close(); }, 240000);
async function page() {
  const p = await browser.newPage();
  p.setDefaultTimeout(20000);
  p.on('pageerror', e => errors.push(e.message));
  await p.addInitScript(() => { for(const k of ['aira.tour.start','aira.tour.doc']) localStorage.setItem(k,'true'); });
  const r = await p.request.post(origin+'/desktop/license/activate', {data:{license_key:'SYNTHETIC-TEST-LICENSE'}});
  assert.equal(r.ok(),true);
  await p.goto(origin+'/aira/');
  await p.waitForSelector('#app:not([hidden])');
  return p;
}
async function idle(p) {
  await p.evaluate(() => window.AIRA.activeEditor().flushAll());
  await p.waitForFunction(() => { const e=window.AIRA.activeEditor(); return !e.queued && !e.assetsLoading && !e.editor.status().busy; });
}
async function bodyCaret(p) {
  await idle(p);
  await p.evaluate(() => { const e=window.AIRA.activeEditor(), para=e.paras.filter(p=>p.top!==null).at(-1); e.root.focus(); e.placeCaret(para.key,[...para.block.text].length); });
}
async function exportDoc(p,name) {
  await idle(p);
  const download = p.waitForEvent('download');
  await p.locator('#export-btn').click();
  const file=await download;
  assert.equal(await file.failure(),null);
  const path=fileURLToPath(new URL(name,output));
  await file.saveAs(path); return path;
}
async function importDoc(p,path) {
  await p.locator('#home-btn').click();
  const picker=p.waitForEvent('filechooser');
  await p.locator('[data-start="import"]').click();
  await (await picker).setFiles(path);
  await p.locator('.modal .btn.primary').click();
  await p.waitForSelector('.doc .para');
  await idle(p);
}
async function close(p) {
  assert.equal(await p.evaluate(() => window.AIRA.prepareToClose()),true);
  assert.equal(await p.evaluate(() => window.AIRA.debug.workspace.status().tabs.filter(t=>t.phase==='open').length),0);
  await p.close();
}
try {
  const word=await page();
  await importDoc(word,fileURLToPath(new URL('../pages/sample-blockers.docx',import.meta.url)));
  await word.waitForFunction(() => window.AIRA.activeEditor().assets?.blockers?.length>0);
  assert.equal(await word.locator('.check-btn').isDisabled(),false);
  await word.locator('.check-btn').click();
  await word.waitForFunction(() => window.AIRA.activeEditor().client.analysis.status().phase==='finished',null,{timeout:60000});
  const result=await word.evaluate(() => {const s=window.AIRA.activeEditor().client.analysis.status();return {status:s.receipt.state.status,fixture:s.receipt.fixture};});
  assert.equal(result.status,'succeeded');
  if(process.env.AIRA_EXPECT_REAL_MODEL==='1')assert.equal(result.fixture,false);
  await close(word);
  console.log('PASS Word admission and immediate close',JSON.stringify(result));

  const p=await page();
  await p.locator('#new-doc').click();
  await p.locator('.modal input').fill('Synthetic UI integration');
  await p.locator('.modal .btn.primary').click();
  await p.waitForSelector('.doc .para');
  await p.locator('.doc .para').first().click();
  await p.keyboard.insertText('Система должна отвечать за 2 секунды.');
  // Deliberately do not wait for debounce/flush before opening the dialog.
  await p.locator('[data-cmd="table"]').click();
  await p.getByLabel('Строки',{exact:true}).fill('100');
  await p.getByLabel('Столбцы',{exact:true}).fill('32');
  assert.equal(await p.locator('.modal [data-id="insert"]').isDisabled(),true);
  await p.getByLabel('Строки',{exact:true}).fill('2');
  await p.getByLabel('Столбцы',{exact:true}).fill('3');
  await p.locator('.modal [data-id="insert"]').click();
  await p.waitForSelector('.doc-table td:nth-child(3)');
  assert.equal(await p.locator('.doc-table td').count(),6);
  await idle(p);
  await p.locator('[data-cmd="undo"]').click();
  await p.waitForFunction(() => !document.querySelector('.doc-table'));
  await p.locator('[data-cmd="redo"]').click();
  await p.waitForSelector('.doc-table');
  await p.locator('.doc-table td .para').first().click();
  await p.keyboard.insertText('Состояние реле');
  await idle(p);
  // Cell insertion is deliberately unsupported: no dialog and no mutation.
  const revision=await p.evaluate(() => window.AIRA.activeEditor().editor.snapshot().document.session_revision);
  await p.locator('[data-cmd="table"]').click();
  await p.getByText('Поставьте курсор в обычный абзац вне таблицы, без выделения текста.',{exact:true}).first().waitFor();
  assert.equal(await p.locator('.modal').count(),0);
  assert.equal(await p.evaluate(() => window.AIRA.activeEditor().editor.snapshot().document.session_revision),revision);
  await bodyCaret(p);
  // Cancelled table selection and rejected image bytes must leave source bytes intact.
  const source=await p.evaluate(() => window.AIRA.activeEditor().editor.snapshot().document.source_sha256);
  await p.locator('[data-cmd="table"]').click();
  await p.locator('.modal [data-id="cancel"]').click();
  assert.equal(await p.evaluate(() => window.AIRA.activeEditor().editor.snapshot().document.source_sha256),source);
  await bodyCaret(p);
  const invalidPicker=p.waitForEvent('filechooser');
  await p.locator('[data-cmd="image"]').click();
  await (await invalidPicker).setFiles({name:'invalid.png',mimeType:'image/png',buffer:Buffer.from('not an image')});
  await p.getByText('Вставка в этой позиции или этот файл не поддерживаются. Документ не изменён.',{exact:true}).first().waitFor();
  await idle(p);
  assert.equal(await p.evaluate(() => window.AIRA.activeEditor().editor.snapshot().document.source_sha256),source);
  assert.equal(await p.evaluate(() => window.AIRA.activeEditor().laneError),null);
  await bodyCaret(p);
  const picker=p.waitForEvent('filechooser');
  await p.locator('[data-cmd="image"]').click();
  await (await picker).setFiles(fileURLToPath(new URL('../../static/logo.png',import.meta.url)));
  await p.waitForSelector('.doc .obj.img img');
  await idle(p);
  assert.equal(await p.locator('.doc img').evaluate(img=>img.complete&&img.naturalWidth>0),true);
  await p.locator('[data-cmd="undo"]').click();
  await p.waitForFunction(() => !document.querySelector('.doc img'));
  await p.locator('[data-cmd="redo"]').click();
  await p.waitForSelector('.doc img');
  // A dialog point captured before another edit must never attach to a different revision.
  await bodyCaret(p);
  const stale=await p.evaluate(() => window.AIRA.activeEditor().objectPoint());
  await p.keyboard.insertText(' Проверка выбора.');
  await idle(p);
  const changed=await p.evaluate(() => window.AIRA.activeEditor().editor.snapshot().document.source_sha256);
  await p.evaluate(point => window.AIRA.activeEditor().insertObject('insert_table',{rows:1,columns:1},point),stale);
  assert.equal(await p.evaluate(() => window.AIRA.activeEditor().editor.snapshot().document.source_sha256),changed);
  assert.equal(await p.locator('.doc-table').count(),1);
  const saved=await exportDoc(p,'table-image.docx');
  await p.screenshot({path:fileURLToPath(new URL('editor.png',output)),fullPage:true});
  await close(p);
  const reopened=await page();
  let busyReads=2;
  await reopened.route('**/working-content', async route => {
    if(busyReads>0) { busyReads--; await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'editor_busy'})}); }
    else await route.continue();
  });
  await importDoc(reopened,saved);
  assert.equal(await reopened.locator('.doc-table td').count(),6);
  assert.match(await reopened.locator('.doc-table').innerText(),/Состояние реле/);
  await reopened.waitForSelector('.doc img');
  assert.equal(busyReads,0,'Transient busy reads were actually exercised');
  await reopened.unroute('**/working-content');
  await reopened.locator('.check-btn').click();
  await reopened.waitForFunction(() => window.AIRA.activeEditor().client.analysis.status().phase==='finished',null,{timeout:60000});
  assert.equal(await reopened.evaluate(() => window.AIRA.activeEditor().client.analysis.status().receipt.state.status),'succeeded');
  await close(reopened);
  console.log('PASS table/image insertion, validation, undo/redo, export/reimport and analysis');

  // Set up a synthetic supported edit with alt text which current analysis explicitly refuses.
  const refused=await page();
  await refused.locator('#new-doc').click();
  await refused.locator('.modal input').fill('Synthetic refusal');
  await refused.locator('.modal .btn.primary').click();
  await refused.waitForSelector('.doc .para');
  await refused.locator('.doc .para').first().click();
  await refused.keyboard.insertText('Система должна сохранять требования.');
  await bodyCaret(refused);
  const png=(await readFile(new URL('../../static/logo.png',import.meta.url))).toString('base64');
  await refused.evaluate(async data => {const e=window.AIRA.activeEditor(); await e.insertObject('insert_image',{data_base64:data,alt_text:'Synthetic diagram'},e.objectPoint());},png);
  await refused.waitForSelector('.doc img');
  await refused.locator('.check-btn').click();
  await refused.waitForFunction(() => window.AIRA.activeEditor().client.analysis.status().phase==='not_admitted');
  assert.equal(await refused.evaluate(() => window.AIRA.activeEditor().client.analysis.status().canStop),false);
  assert.equal(await refused.locator('.check-btn').isDisabled(),false);
  await exportDoc(refused,'refused.docx');
  await close(refused);
  console.log('PASS refused analysis releases export and actual workspace close');
  assert.deepEqual(errors,[],'No browser script errors');
} finally {clearTimeout(deadline);await browser.close();}
