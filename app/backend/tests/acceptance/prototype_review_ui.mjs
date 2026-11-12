import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

class Element {
  constructor(tag, attrs = {}) { this.tag = tag; this.attrs = attrs; this.children = []; }
  append(...children) { this.children.push(...children.flat(Infinity).filter(v => v !== null && v !== undefined && v !== false)); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  querySelector() { return null; }
}
const h = (tag, attrs, ...children) => {
  const el = new Element(tag, attrs || {}); el.append(...children); return el;
};
const cache = new Map();
const context = vm.createContext({ console, localStorage: {
  getItem: key => cache.get(key) ?? null, setItem: (key, value) => cache.set(key, value),
} });
const ui = new vm.SyntheticModule(['h', 'icon', 'toast', 'fmtTime', 'fmtClock', 'plural'], function () {
  this.setExport('h', h); this.setExport('icon', () => null); this.setExport('toast', () => {});
  this.setExport('fmtTime', () => 'now'); this.setExport('fmtClock', () => '0');
  this.setExport('plural', (n, values) => values[0]);
}, { context });
const mascot = new vm.SyntheticModule(['meerkat'], function () { this.setExport('meerkat', () => null); }, { context });
const directory = process.argv[2];
const data = new vm.SourceTextModule(fs.readFileSync(path.join(directory, 'review-data.mjs'), 'utf8'), { context });
await data.link(() => { throw new Error('unexpected dependency'); }); await data.evaluate();
const module = new vm.SourceTextModule(fs.readFileSync(path.join(directory, 'review.mjs'), 'utf8'), { context });
await module.link(name => name === './ui.mjs' ? ui : name === './mascot.mjs' ? mascot : data);
await module.evaluate();

const evidence = { quote: '10 (двадцать) дней', fragment_id: 'source', start: 900, end: 917 };
const question = { question_id: 'sq-test', text: 'Возможное противоречие', reason: 'Сверьте цифры и пропись.', evidence: [evidence] };
const preferences = { disabled_types: [], show_questions: true, show_hidden: false, revision: 1 };
const view = { findings: [], questions: [], standalone_questions: [question], hidden_finding_ids: [], counts: {}, no_findings: false };
const status = { phase: 'ready', busy: false, canHighlight: true, stale: false,
  review: { run: { run_id: 'synthetic-run' }, view, preferences, view_sha256: 'one', fixture: false } };
const body = new Element('main'), rail = new Element('aside');
const jumps = [];
const editor = { isEmpty: () => false, setHighlights: () => {}, evidenceRanges: () => [],
  scrollToEvidence: e => { jumps.push(e); return true; } };
const client = { analysis: { status: () => ({ phase: 'idle', canCheck: true }) }, review: { status: () => status } };
let panel;
const app = { activeId: 'doc', editors: new Map([['doc', editor]]), workspace: { client: () => client }, render: () => panel.render() };
panel = module.namespace.createReviewPanel({ body, rail, app });
const nodes = el => [el, ...(el?.children || []).flatMap(child => typeof child === 'object' ? nodes(child) : [])];
const text = el => typeof el === 'object' ? (el.children || []).map(text).join('') : String(el);
panel.render();
const chip = nodes(body).find(el => el.tag === 'button' && el.attrs.class?.includes('fchip') && text(el).startsWith('Вопросы'));
assert.equal(chip.attrs.disabled, false);
assert.equal(text(chip), 'Вопросы1');
assert(!text(body).includes('Нечего показать'));
assert(!text(body).includes('Замечаний нет'));
assert.equal(nodes(body).filter(el => el.tag === 'article').length, 1);
chip.attrs.onclick();
assert.equal(nodes(body).filter(el => el.tag === 'article').length, 1);
const quote = nodes(body).find(el => el.tag === 'blockquote');
quote.attrs.onkeydown({ key: 'Enter', preventDefault() {}, stopPropagation() {} });
assert.equal(jumps.length, 1); assert.equal(jumps[0], evidence);
status.canHighlight = false; status.stale = true; panel.render();
nodes(body).find(el => el.tag === 'blockquote').attrs.onkeydown({ key: 'Enter' });
assert.equal(jumps.length, 1);
preferences.disabled_types = ['formulation', 'duplicate']; preferences.show_questions = false;
preferences.revision++; view.standalone_questions = []; status.review.view_sha256 = 'two';
panel.reset(); panel.render();
assert.equal(nodes(body).filter(el => el.tag === 'article').length, 0);
const counts = data.namespace.reviewCounts({ ...view, standalone_questions: [question],
  findings: [{ finding_id: 'a', type: 'formulation' }], questions: [{ question_id: 'linked' }] }, ['formulation', 'duplicate', 'contradiction']);
assert.equal(counts.questions, 2); assert.equal(counts.all, 2);
console.log('ok prototype review UI');
