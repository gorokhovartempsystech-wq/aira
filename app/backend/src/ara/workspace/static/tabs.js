export const MAX_OPEN_DOCUMENTS = 12;

// Values are opaque editor frames. Keep their object identity so parking a tab
// does not clone away history methods or a stable pending operation payload.
export function createTabs() {
  const values = new Map();
  let active = null;
  function open(id, value) {
    if (typeof id !== "string" || id.length < 1 || id.length > 128 || value === null || typeof value !== "object") {
      throw new TypeError("Invalid tab");
    }
    if (!values.has(id)) {
      if (values.size >= MAX_OPEN_DOCUMENTS) throw new RangeError("Tab limit reached");
      values.set(id, value);
    }
    active = id; return values.get(id);
  }
  function activate(id) {
    if (!values.has(id)) throw new RangeError("Unknown tab");
    active = id; return values.get(id);
  }
  function close(id) {
    const index = [...values.keys()].indexOf(id);
    if (index < 0) return active;
    values.delete(id);
    if (active === id) active = [...values.keys()][Math.min(index, values.size - 1)] ?? null;
    return active;
  }
  return { open, activate, close, get: id => values.get(id) ?? null,
    has: id => values.has(id), activeId: () => active,
    entries: () => [...values].map(([id, value]) => ({ id, value })) };
}
