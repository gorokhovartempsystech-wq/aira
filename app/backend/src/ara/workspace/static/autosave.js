export const AUTOSAVE_DELAY_MS = 120000;

// One controller belongs to one editor draft. Dependencies make timing testable
// without exposing a production switch that shortens the two-minute interval.
export function createAutosave({ hasChanges, canSave, save,
  schedule = (fn, delay) => setTimeout(fn, delay), cancel = id => clearTimeout(id),
  onError = () => {} }) {
  let timer = null, running = false, stopped = false;
  function touch() {
    if (stopped || running || timer !== null || !hasChanges()) return;
    timer = schedule(() => { void run(); }, AUTOSAVE_DELAY_MS);
  }
  async function run() {
    timer = null;
    if (stopped || running) return;
    running = true;
    try { if (hasChanges() && canSave()) await save(); }
    catch (error) { try { onError(error); } catch (_) { /* Keep the timer settled. */ } }
    finally { running = false; touch(); }
  }
  function stop() {
    stopped = true;
    if (timer !== null) cancel(timer);
    timer = null;
  }
  return { touch, stop };
}
