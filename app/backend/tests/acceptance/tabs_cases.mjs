import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const [root,name] = process.argv.slice(2);
const source = await readFile(root+"/src/ara/workspace/static/tabs.js","utf8");
const {createTabs,MAX_OPEN_DOCUMENTS} = await import("data:text/javascript;base64,"+Buffer.from(source).toString("base64"));
assert.equal(MAX_OPEN_DOCUMENTS,12);
const cases={
  identity(){
    const t=createTabs(), value={draft:"A"}; assert.equal(t.activeId(),null);
    assert.equal(t.open("a",value),value); assert.equal(t.open("a",{draft:"B"}),value);
    assert.equal(t.entries().length,1); assert.equal(t.activeId(),"a");
  },
  order(){
    const t=createTabs(); t.open("b",{});t.open("a",{});t.open("c",{});t.activate("b");
    assert.deepEqual(t.entries().map(e=>e.id),["b","a","c"]);
    const rows=t.entries(); rows[0].id="bad";rows.pop();
    assert.deepEqual(t.entries().map(e=>e.id),["b","a","c"]);
  },
  state(){
    const t=createTabs(), history={undo(){return "old";}}, pending={key:"same",payload:"exact"};
    const value={draft:{replacement:"🧪",history,pending},selection:{start:0,end:2}};
    t.open("a",value);t.open("b",{});assert.equal(t.activate("a"),value);
    assert.equal(t.get("a").draft.history,history);assert.equal(t.get("a").draft.pending,pending);
    assert.deepEqual(t.get("a").selection,{start:0,end:2});
  },
  capacity(){
    const t=createTabs();for(let i=0;i<12;i++)t.open(String(i),{value:i});
    assert.throws(()=>t.open("new",{}));assert.equal(t.activeId(),"11");assert.equal(t.entries().length,12);
    assert.equal(t.open("0",{}).value,0); assert.equal(t.close("5"),"0");
    t.open("new",{});assert.equal(t.entries().length,12);assert.equal(t.has("11"),true);
  },
  close_right(){
    const t=createTabs();t.open("a",{});t.open("b",{});t.open("c",{});t.activate("b");
    assert.equal(t.close("b"),"c");assert.equal(t.has("b"),false);
  },
  close_left(){
    const t=createTabs();t.open("a",{});t.open("b",{});assert.equal(t.close("b"),"a");
  },
  close_inactive(){
    const t=createTabs(),a={text:"keep"};t.open("a",a);t.open("b",{});t.activate("a");
    assert.equal(t.close("b"),"a");assert.equal(t.get("a"),a);
  },
  close_last(){
    const t=createTabs();t.open("a",{});assert.equal(t.close("a"),null);assert.deepEqual(t.entries(),[]);
    assert.equal(t.get("a"),null);assert.equal(t.activeId(),null);
  },
  missing(){
    const t=createTabs();t.open("a",{});assert.throws(()=>t.activate("missing"));
    assert.equal(t.activeId(),"a");assert.equal(t.close("missing"),"a");assert.equal(t.get("missing"),null);
  },
  invalid(){
    const t=createTabs();for(const bad of [null,"",1,"x".repeat(129)])assert.throws(()=>t.open(bad,{}));
    for(const bad of [null,1,"text"])assert.throws(()=>t.open("a",bad));
    assert.deepEqual(t.entries(),[]);assert.equal(t.activeId(),null);
  },
  independent(){
    const t=createTabs();t.open("a",{draft:{text:"A"}});t.open("b",{draft:{text:"B"}});
    t.get("a").draft.text="changed";assert.equal(t.get("b").draft.text,"B");
    t.close("a");assert.equal(t.get("b").draft.text,"B");
  },
};
assert.ok(Object.hasOwn(cases,name)); cases[name](); console.log("ok "+name);
