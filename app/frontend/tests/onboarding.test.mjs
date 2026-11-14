import assert from 'node:assert/strict';
import { createOnboarding } from '../static/js/onboarding.mjs';

export async function runTests() {
  let passed = 0;
  const test = async (name, run) => { await run(); passed++; };
  const newState = () => ({ start: 'new', doc: 'new' });
  const memory = () => {
    let state = newState();
    return { read: async () => ({ ...state }), write: async (kind, status) => { state[kind] = status; } };
  };

  await test('completion survives a new window and each tour is independent', async () => {
    const profile = memory();
    const first = createOnboarding(profile);
    await first.load();
    assert.equal(first.handled('start'), false);
    await first.finish('start', { completed: true });
    const nextWindow = createOnboarding(profile);
    await nextWindow.load();
    assert.equal(nextWindow.handled('start'), true);
    assert.equal(nextWindow.handled('doc'), false);
    await nextWindow.finish('doc', { completed: true });
    assert.deepEqual(await profile.read(), { start: 'completed', doc: 'completed' });
  });

  await test('closing training is saved as dismissal; manual replay does not downgrade completion', async () => {
    const profile = memory(), onboarding = createOnboarding(profile);
    await onboarding.load();
    await onboarding.finish('start');
    assert.equal((await profile.read()).start, 'dismissed');
    await onboarding.finish('start', { completed: true });
    await onboarding.finish('start');
    assert.equal((await profile.read()).start, 'completed');
  });

  await test('legacy true is migrated without inventing completion', async () => {
    const profile = memory(), onboarding = createOnboarding({ ...profile, legacy: kind => kind === 'start' });
    await onboarding.load();
    assert.deepEqual(await profile.read(), { start: 'dismissed', doc: 'new' });
  });

  await test('profile failure does not force a tour on every launch', async () => {
    let notices = 0;
    const onboarding = createOnboarding({ read: async () => { throw Error('offline'); },
      write: async () => {}, onError: () => notices++ });
    await onboarding.load();
    assert.equal(notices, 1);
    assert.equal(onboarding.handled('start'), true);
    assert.equal(onboarding.handled('doc'), true);
  });

  await test('failed save is retried on flush without losing the other tour', async () => {
    let fail = true, notices = 0;
    const profile = memory(), onboarding = createOnboarding({ ...profile,
      write: async (...args) => { if (fail) throw Error('disk'); await profile.write(...args); },
      onError: () => notices++ });
    await onboarding.load();
    await onboarding.finish('start', { completed: true });
    assert.equal(onboarding.handled('start'), true);
    assert.equal(notices, 1);
    fail = false;
    await onboarding.finish('doc', { completed: true });
    await onboarding.flush();
    assert.deepEqual(await profile.read(), { start: 'completed', doc: 'completed' });
  });

  await test('overlapping completion and dismissal preserve completed status', async () => {
    const profile = memory(), onboarding = createOnboarding(profile);
    await onboarding.load();
    await Promise.all([onboarding.finish('start', { completed: true }), onboarding.finish('start'),
      onboarding.finish('doc', { completed: true })]);
    assert.deepEqual(await profile.read(), { start: 'completed', doc: 'completed' });
  });
  return { passed };
}
