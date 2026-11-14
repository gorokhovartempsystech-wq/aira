// Profile state survives WebKit's temporary storage, new loopback ports and app updates.
export function createOnboarding({ read, write, legacy = () => false, onError = () => {} }) {
  const state = { start: 'new', doc: 'new' };
  const dirty = new Map();
  let ready = false, pending = Promise.resolve();
  const valid = value => ['new', 'completed', 'dismissed'].includes(value);

  function flush() {
    pending = pending.then(async () => {
      for (const [kind, status] of [...dirty]) {
        try {
          await write(kind, status);
          if (dirty.get(kind) === status) dirty.delete(kind);
        } catch { onError(); }
      }
    });
    return pending;
  }

  return {
    async load() {
      try {
        const value = await read();
        if (!value || !valid(value.start) || !valid(value.doc)) throw new Error('invalid_onboarding');
        Object.assign(state, value);
        ready = true;
        for (const kind of ['start', 'doc']) {
          // Old flags did not distinguish completion from dismissal.
          if (state[kind] === 'new' && legacy(kind) === true) {
            state[kind] = 'dismissed'; dirty.set(kind, 'dismissed');
          }
        }
        await flush();
      } catch { onError(); }
    },
    handled: kind => !ready || state[kind] !== 'new',
    finish(kind, { completed = false } = {}) {
      if (!['start', 'doc'].includes(kind)) return Promise.resolve();
      if (state[kind] !== 'completed') state[kind] = completed ? 'completed' : 'dismissed';
      dirty.set(kind, state[kind]);
      return flush();
    },
    flush,
  };
}
