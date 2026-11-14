import assert from 'node:assert/strict';
import { connectHost } from '../static/js/host.mjs';

export async function runTests() {
  const previousWindow = globalThis.window, previousLocation = globalThis.location;
  const origin = 'http://127.0.0.1:47017';
  let reply, fail;
  globalThis.location = { origin, hash: '#desktop' };
  globalThis.window = { pywebview: { api: {
    connection: async () => ({ origin, sessionToken: 'a'.repeat(64) }),
    request_update: () => new Promise((resolve, reject) => { reply = resolve; fail = reject; }),
  } } };
  try {
    const host = await connectHost();
    const first = host.checkUpdates();
    const acknowledged = window.__airaUpdateBridgeReady;
    let finished = false;
    acknowledged.then(() => { finished = true; });
    await Promise.resolve();
    assert.equal(finished, false, 'Native close must wait for the RPC reply');
    reply(true);
    assert.equal(await first, true);
    assert.equal(await acknowledged, true);

    const refused = host.checkUpdates();
    reply(false);
    assert.equal(await refused, false);
    assert.equal(await window.__airaUpdateBridgeReady, false);

    const failed = host.checkUpdates();
    const rejected = assert.rejects(failed, /synthetic bridge error/);
    fail(new Error('synthetic bridge error'));
    await rejected;
    assert.equal(await window.__airaUpdateBridgeReady, false);
    return { passed: 3 };
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousLocation === undefined) delete globalThis.location;
    else globalThis.location = previousLocation;
  }
}
