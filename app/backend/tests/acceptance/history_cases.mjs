import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const [root, name] = process.argv.slice(2);
const source = await readFile(root + "/src/ara/workspace/static/history.js", "utf8");
const { createHistory, HISTORY_LIMIT, HISTORY_TEXT_BUDGET } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
assert.equal(HISTORY_LIMIT, 64); assert.equal(HISTORY_TEXT_BUDGET, 2000000);
const s = (text, start = text.length, end = start) => ({text,start,end});
const cases = {
  basic() {
    const input = s("A"), h = createHistory(input); input.text = "mutated";
    assert.deepEqual(h.current(),s("A")); assert.equal(h.undo(),null); assert.equal(h.redo(),null);
    h.record(s("B")); h.record(s("C")); assert.deepEqual(h.undo(),s("B"));
    assert.deepEqual(h.undo(),s("A")); assert.equal(h.canUndo(),false);
    assert.deepEqual(h.redo(),s("B")); assert.deepEqual(h.redo(),s("C")); assert.equal(h.canRedo(),false);
    const copy=h.current(); try { copy.text="unsafe"; } catch (_) {}
    assert.equal(h.current().text,"C");
  },
  paste() {
    const h=createHistory(s("old"));
    h.record(s("new pasted text"),{before:s("old",0,3),inputType:"insertFromPaste",time:10});
    h.record(s("replacement"),{before:s("new pasted text",0,15),inputType:"insertReplacementText",time:20});
    assert.equal(h.undo().text,"new pasted text"); assert.deepEqual(h.undo(),s("old",0,3));
  },
  grouping() {
    const h=createHistory(s(""));
    h.record(s("a"),{before:s(""),inputType:"insertText",time:10});
    h.record(s("ab"),{before:s("a"),inputType:"insertText",time:20});
    h.record(s("abc"),{before:s("ab"),inputType:"insertText",time:30});
    assert.equal(h.undo().text,""); assert.equal(h.canUndo(),false); assert.equal(h.redo().text,"abc");
  },
  deletion() {
    const h=createHistory(s("abcd"));
    h.record(s("abc"),{before:s("abcd"),inputType:"deleteContentBackward",time:10});
    h.record(s("ab"),{before:s("abc"),inputType:"deleteContentBackward",time:20});
    h.record(s("a",0),{before:s("ab",0),inputType:"deleteContentForward",time:30});
    assert.deepEqual(h.undo(),s("ab",0)); assert.equal(h.undo().text,"abcd");
  },
  selection() {
    const h=createHistory(s("a"));
    h.record(s("ab"),{before:s("a"),inputType:"insertText",time:10});
    h.record(s("Xab",1),{before:s("ab",0),inputType:"insertText",time:20});
    assert.deepEqual(h.undo(),s("ab",0)); assert.equal(h.undo().text,"a");
  },
  gap() {
    for(const delta of [751,-1]) {
      const h=createHistory(s("")); h.record(s("a"),{before:s(""),inputType:"insertText",time:1000});
      h.record(s("ab"),{before:s("a"),inputType:"insertText",time:1000+delta});
      assert.equal(h.undo().text,"a");
    }
  },
  branch() {
    const h=createHistory(s("A")); h.record(s("B")); h.record(s("C")); h.undo();
    h.record(s("D")); assert.equal(h.canRedo(),false); assert.equal(h.undo().text,"B");
    assert.equal(h.redo().text,"D");
  },
  unicode() {
    const h=createHistory(s("  Я🧪\r\n  ",2,5)); h.record(s("<script>🧪</script>"));
    assert.deepEqual(h.undo(),s("  Я🧪\r\n  ",2,5));
    assert.equal(h.redo().text,"<script>🧪</script>");
  },
  capture() {
    const h=createHistory(s("A")); h.record(s("AB"),{before:s("A"),inputType:"insertText",time:10});
    h.capture(s("AB",0,2)); h.record(s("C"),{before:s("AB",0,2),inputType:"insertText",time:20});
    assert.deepEqual(h.undo(),s("AB",0,2)); assert.equal(h.undo().text,"A");
  },
  unchanged() {
    const h=createHistory(s("A")); h.record(s("B")); h.undo();
    assert.equal(h.record(s("A",0)),false); assert.equal(h.canRedo(),true);
    assert.deepEqual(h.current(),s("A",0)); assert.equal(h.redo().text,"B");
  },
  recovered() {
    const h=createHistory(s("base")); h.record(s("restored"));
    assert.equal(h.undo().text,"base"); assert.equal(h.redo().text,"restored");
    // A saved base lives outside the input history: marking it saved must not be
    // required to keep the old text available after autosave.
    assert.equal(h.undo().text,"base");
  },
  composition() {
    const h=createHistory(s(""));
    h.record(s("漢字"),{before:s(""),inputType:"insertCompositionText",time:10});
    assert.equal(h.record(s("漢字")),false);
    h.record(s("漢字文"),{before:s("漢字"),inputType:"insertCompositionText",time:20});
    assert.equal(h.undo().text,"漢字"); assert.equal(h.undo().text,"");
  },
  invalid() {
    for(const bad of [{text:1,start:0,end:0},s("a",-1),s("a",0,2),s("a",1,0),s("a",0.5)]) {
      assert.throws(()=>createHistory(bad)); const h=createHistory(s("a"));
      assert.throws(()=>h.record(bad)); assert.deepEqual(h.current(),s("a"));
    }
    const h=createHistory(s("a")); assert.throws(()=>h.capture(s("other")));
    assert.throws(()=>h.record(s("b"),{before:s("other")})); assert.equal(h.canUndo(),false);
  },
  capacity() {
    const h=createHistory(s("0")); for(let i=1;i<=100;i++)h.record(s(String(i)));
    let steps=0; while(h.undo()!==null)steps++;
    assert.equal(steps,63); assert.equal(h.current().text,"37");
  },
  memory() {
    const a="a".repeat(800000), b="b".repeat(800000), c="c".repeat(800000);
    const h=createHistory(s(a)); h.record(s(b)); h.record(s(c));
    assert.equal(h.undo().text,b); assert.equal(h.undo(),null); assert.equal(h.redo().text,c);
    const oversized="z".repeat(2000001); h.record(s(oversized));
    assert.equal(h.current().text,oversized); assert.equal(h.canUndo(),false);
  },
};
assert.ok(Object.hasOwn(cases,name)); cases[name](); console.log("ok "+name);
