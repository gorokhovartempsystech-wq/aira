import assert from 'node:assert/strict';

const origin = 'http://127.0.0.1:47017';
globalThis.location = {origin, hash:'#desktop'};
globalThis.window = {pywebview:{api:{
  connection: async () => ({origin, sessionToken:'a'.repeat(64)}),
  close_result: () => { throw new Error('Close must not create an RPC reply after destroying the window'); },
}}};
const {connectHost} = await import('../app/frontend/static/js/host.mjs');
const host = await connectHost();
assert.equal(await window.__airaRequestClose(), true);
host.onCloseRequest(async () => false);
assert.equal(await window.__airaRequestClose(), false);
host.onCloseRequest(async () => { throw new Error('synthetic save failed'); });
assert.equal(await window.__airaRequestClose(), false);
host.onCloseRequest(async () => 'truthy but not permission');
assert.equal(await window.__airaRequestClose(), false);
let save;
host.onCloseRequest(() => new Promise(resolve => { save=resolve; }));
let finished=false;
const pending = window.__airaRequestClose().then(value => { finished=true; return value; });
await Promise.resolve();
assert.equal(finished, false);
save(true);
assert.equal(await pending, true);
console.log('Windows close bridge: approval, cancellation, failed save and delayed save passed.');
