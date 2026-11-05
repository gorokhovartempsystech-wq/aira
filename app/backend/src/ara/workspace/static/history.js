export const HISTORY_LIMIT = 64;
export const HISTORY_TEXT_BUDGET = 2000000;

function snapshot(value) {
  if (!value || typeof value.text !== "string" || !Number.isInteger(value.start) ||
      !Number.isInteger(value.end) || value.start < 0 || value.start > value.end || value.end > value.text.length) {
    throw new TypeError("Invalid history snapshot");
  }
  return Object.freeze({ text: value.text, start: value.start, end: value.end });
}

// History contains only input snapshots. The saved document's revision and
// source anchor belong to the editor, so autosave never resets this stack.
export function createHistory(initial) {
  let states = [snapshot(initial)], index = 0, group = null;
  const current = () => snapshot(states[index]);
  const canUndo = () => index > 0;
  const canRedo = () => index < states.length - 1;
  function capture(value) {
    const next = snapshot(value);
    if (next.text !== states[index].text) throw new TypeError("History base has changed");
    states[index] = next; group = null;
  }
  function record(value, { before = null, inputType = "", time = 0 } = {}) {
    const next = snapshot(value), previous = states[index];
    const origin = before === null ? null : snapshot(before);
    if (origin && origin.text !== previous.text) throw new TypeError("History base has changed");
    if (next.text === previous.text) {
      states[index] = next; group = null; return false;
    }
    const eligible = origin && origin.start === origin.end && next.start === next.end &&
      ["insertText", "deleteContentBackward", "deleteContentForward"].includes(inputType) &&
      Number.isFinite(time) && time >= 0;
    const merge = eligible && index > 0 && index === states.length - 1 && group &&
      group.type === inputType && time >= group.time && time - group.time <= 750 &&
      origin.start === previous.start && origin.end === previous.end;
    if (origin) states[index] = origin;
    states = states.slice(0, index + 1);
    if (merge) states[index] = next;
    else { states.push(next); index++; }
    group = eligible ? { type: inputType, time } : null;
    let total = states.reduce((sum, item) => sum + item.text.length, 0);
    while (states.length > 1 && (states.length > HISTORY_LIMIT || total > HISTORY_TEXT_BUDGET)) {
      total -= states.shift().text.length; index--;
    }
    if (index === 0) group = null;
    return true;
  }
  function undo() {
    group = null;
    if (!canUndo()) return null;
    index--; return current();
  }
  function redo() {
    group = null;
    if (!canRedo()) return null;
    index++; return current();
  }
  return { current, canUndo, canRedo, record, capture, undo, redo };
}
