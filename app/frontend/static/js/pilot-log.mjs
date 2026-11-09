// Local pilot diagnostics: fixed action names, never document text or file paths.
const IDS = new Set(['new-doc', 'home-btn', 'save-btn', 'export-btn',
  'zoom-in', 'zoom-out', 'zoom-value', 'help-btn', 'licence-retry', 'drawer-close']);
const COMMANDS = new Set(['undo', 'redo', 'table', 'image', 'bullet', 'numbered']);
const REVIEW = new Set(['analysis.stop', 'analysis.refresh', 'analysis.retry', 'analysis.check', 'review.filter', 'review.visibility']);
const START = new Set(['import', 'example', 'new']);

export function installPilotLog(root, send, now = () => Date.now()) {
  let sequence = 0;
  let lastEdit = -Infinity;
  const record = action => send('pilot', JSON.stringify({event:action, seq:++sequence}));
  const click = event => {
    const element = event.target?.closest?.('button, [data-start], [data-finding]');
    if (!element || element.disabled) return;
    if (REVIEW.has(element.dataset.pilot)) record(element.dataset.pilot);
    else if (IDS.has(element.id)) record(element.id);
    else if (COMMANDS.has(element.dataset.cmd)) record('editor.' + element.dataset.cmd);
    else if (START.has(element.dataset.start)) record('start.' + element.dataset.start);
    else if (element.classList.contains('check-btn')) record('analysis.check');
    else if (element.dataset.finding !== undefined) record('finding.select');
    else if (element.closest('.modal')) record('dialog.action');
  };
  const input = event => {
    if (!event.target?.closest?.('.doc[contenteditable="true"]')) return;
    const time = now();
    if (time - lastEdit >= 5000) {
      lastEdit = time;
      record('editor.input');
    }
  };
  root.addEventListener('click', click, true);
  root.addEventListener('input', input, true);
  return () => {
    root.removeEventListener('click', click, true);
    root.removeEventListener('input', input, true);
  };
}
