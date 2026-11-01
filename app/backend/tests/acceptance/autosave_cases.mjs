import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const [root, name] = process.argv.slice(2);
const source = await readFile(root + "/src/ara/workspace/static/autosave.js", "utf8");
const { createAutosave, AUTOSAVE_DELAY_MS } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
assert.equal(AUTOSAVE_DELAY_MS, 120000);
let now = 0, nextId = 0, dirty = true, allowed = true, value = "first";
const timers = new Map(), calls = [], errors = [];
let save = async () => { calls.push(value); dirty = false; };
const options = {
  hasChanges: () => dirty,
  canSave: () => allowed,
  save: () => save(),
  schedule: (fn, delay) => { const id = ++nextId; timers.set(id, { fn, at: now + delay }); return id; },
  cancel: id => timers.delete(id),
  onError: error => errors.push(error.message),
};
const controller = createAutosave(options);
assert.equal(timers.size, 0, "Construction must be inert");
async function tick(ms) {
  const target = now + ms;
  for (;;) {
    const due = [...timers].filter(([, t]) => t.at <= target).sort((a,b) => a[1].at - b[1].at)[0];
    if (!due) break;
    const [id, timer] = due; timers.delete(id); now = timer.at; timer.fn();
    for (let i = 0; i < 10; i++) await Promise.resolve();
  }
  now = target;
}
const cases = {
  async deadline() {
    controller.touch(); await tick(119999); assert.deepEqual(calls, []);
    value = "latest"; await tick(1); assert.deepEqual(calls, ["latest"]); assert.equal(timers.size, 0);
  },
  async unchanged() {
    dirty = false; controller.touch(); assert.equal(timers.size, 0);
    dirty = true; controller.touch(); dirty = false; await tick(120000); assert.deepEqual(calls, []);
  },
  async continuous() {
    controller.touch(); await tick(60000); value = "continued"; controller.touch();
    assert.equal(timers.size, 1); await tick(60000); assert.deepEqual(calls, ["continued"]);
  },
  async blocked() {
    controller.touch(); allowed = false; await tick(120000); assert.deepEqual(calls, []);
    assert.equal(timers.size, 1); allowed = true; await tick(120000); assert.deepEqual(calls, ["first"]);
  },
  async overlap() {
    let release; save = () => { calls.push(value); return new Promise(r => { release = r; }); };
    controller.touch(); await tick(120000); controller.touch(); await tick(360000);
    assert.deepEqual(calls, ["first"]); assert.equal(timers.size, 0);
    dirty = false; release(); for (let i=0; i<10; i++) await Promise.resolve();
    assert.equal(timers.size, 0);
  },
  async stop() {
    controller.touch(); assert.equal(timers.size, 1); controller.stop(); controller.touch();
    await tick(240000); assert.deepEqual(calls, []); assert.equal(timers.size, 0);
  },
  async stale() {
    controller.touch(); const oldCallback = [...timers.values()][0].fn; controller.stop();
    const other = createAutosave(options); other.touch(); oldCallback(); await tick(120000);
    assert.deepEqual(calls, ["first"]); other.stop();
  },
  async errors() {
    save = async () => { calls.push("failed"); throw new Error("synthetic"); };
    controller.touch(); await tick(120000); assert.deepEqual(errors, ["synthetic"]);
    save = async () => { calls.push("recovered"); dirty = false; };
    await tick(120000); assert.deepEqual(calls, ["failed", "recovered"]);
  },
  async paused() {
    save = async () => { calls.push(value); dirty = false; };
    controller.touch(); dirty = false; await tick(120000); assert.deepEqual(calls, []);
    dirty = true; controller.touch(); await tick(120000); assert.deepEqual(calls, ["first"]);
  },
  async second_cycle() {
    controller.touch(); await tick(120000); value = "second"; dirty = true;
    controller.touch(); await tick(119999); assert.deepEqual(calls, ["first"]);
    await tick(1); assert.deepEqual(calls, ["first", "second"]);
  },
};
assert.ok(Object.hasOwn(cases, name)); await cases[name](); controller.stop();
console.log("ok " + name);
