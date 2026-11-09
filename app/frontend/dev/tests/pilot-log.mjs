import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless:true, ...(process.env.AIRA_CHROME_EXECUTABLE ? {executablePath:process.env.AIRA_CHROME_EXECUTABLE} : {})});
try {
  const page = await browser.newPage();
  await page.setContent('<button id="save-btn">Private title</button><button data-cmd="table">Table</button><button data-pilot="analysis.stop">Stop</button><button data-pilot="review.filter">Filter</button><button data-cmd="private text">Unknown</button><button id="export-btn" disabled>Export</button><div class="doc" contenteditable="true">Secret requirement</div>');
  const source = await readFile(new URL('../../static/js/pilot-log.mjs', import.meta.url), 'utf8');
  const result = await page.evaluate(async source => {
    const {installPilotLog} = await import('data:text/javascript;base64,' + btoa(source));
    const events = [];
    let time = 0;
    const stop = installPilotLog(document, (kind, value) => events.push({kind, ...JSON.parse(value)}), () => time);
    for (const button of document.querySelectorAll('button')) button.click();
    const editor = document.querySelector('.doc');
    editor.dispatchEvent(new InputEvent('input', {bubbles:true}));
    editor.dispatchEvent(new InputEvent('input', {bubbles:true}));
    time = 5000;
    editor.dispatchEvent(new InputEvent('input', {bubbles:true}));
    stop();
    document.querySelector('#save-btn').click();
    return events;
  }, source);
  assert.deepEqual(result.map(x=>x.event), ['save-btn','editor.table','analysis.stop','review.filter','editor.input','editor.input']);
  assert.deepEqual(result.map(x=>x.seq), [1,2,3,4,5,6]);
  assert.ok(result.every(x=>x.kind==='pilot'));
  assert.ok(!JSON.stringify(result).includes('Secret'));
  console.log('PASS pilot actions, disabled/unknown controls, edit sampling, teardown, content exclusion');
} finally {await browser.close();}
