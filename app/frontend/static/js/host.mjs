// Bridge between the page and the native desktop shell.
//
// The shell (not chosen yet: Electron/Tauri/…) may define `window.airaHost` before the page
// loads. Every member is optional except connection():
//
//   connection(): Promise<{origin, sessionToken}>   live loopback origin + 64-hex capability
//   openDocx(): Promise<{name, bytes: Uint8Array} | null>         native file picker
//   saveDocx(name, bytes): Promise<{saved: boolean, path?: string}> native "Save as" + write
//   onCloseRequest(handler: () => Promise<boolean>)   shell asks before quitting; true = may quit
//
// The capability is never stored or put into URLs. Without a shell (dev stand) the page reads
// it from /aira/connection and falls back to browser file input / download.

export async function connectHost() {
  const native = window.airaHost || await desktopBridge();
  let conn;
  if (native?.connection) conn = await native.connection();
  else {
    const r = await fetch('/aira/connection', { cache: 'no-store', credentials: 'omit' });
    if (!r.ok) throw new Error('host_unavailable');
    conn = await r.json();
  }
  if (!conn || typeof conn.origin !== 'string' || !/^[0-9a-f]{64}$/.test(conn.sessionToken || '')) {
    throw new Error('host_unavailable');
  }
  // Client modules accept only the exact http://127.0.0.1:<port> origin, same-origin.
  if (location.origin !== conn.origin) {
    location.replace(conn.origin + location.pathname);
    return new Promise(() => {});
  }
  return {
    origin: conn.origin,
    sessionToken: conn.sessionToken,
    native: !!native,
    openDocx: native?.openDocx ? () => native.openDocx() : browserPick,
    saveDocx: native?.saveDocx ? (n, b) => native.saveDocx(n, b) : browserDownload,
    saveFile: native?.saveFile ? (n, b, type) => native.saveFile(n, b, type) : null,
    onCloseRequest: handler => {
      if (native?.onCloseRequest) native.onCloseRequest(handler);
    },
  };
}

// Окно приложения AIRA для Windows (pywebview + WebView2, packaging/windows/aira_launcher.pyw):
// мост window.pywebview.api превращается в тот же контракт window.airaHost.
async function desktopBridge() {
  if (!location.hash.includes('desktop') && !window.pywebview) return null;
  if (!window.pywebview?.api?.connection) {
    await new Promise(resolve => { window.addEventListener('pywebviewready', resolve, { once: true }); setTimeout(resolve, 8000); });
  }
  const api = window.pywebview?.api;
  if (!api?.connection) return null;
  const toB64 = bytes => {
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };
  const fromB64 = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  let closeHandler = null;
  // Native shell consumes the resolved Promise through pywebview's one-way callback.
  // Do not send another js_api RPC: its reply would race the window being destroyed.
  window.__airaRequestClose = async () => {
    try { return closeHandler ? (await closeHandler()) === true : true; }
    catch { return false; }
  };
  return {
    desktop: true,
    connection: () => api.connection(),
    openDocx: async () => {
      const r = await api.open_docx();
      if (!r) return null;
      return r.too_big ? { name: r.name, bytes: new Uint8Array(0), tooBig: true } : { name: r.name, bytes: fromB64(r.b64) };
    },
    saveDocx: (name, bytes) => api.save_file(name, toB64(bytes), 'docx'),
    saveFile: async (name, bytes) => api.save_file(name, toB64(bytes), 'txt'),
    onCloseRequest: handler => { closeHandler = handler; },
  };
}

function browserPick() {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    let done = false;
    input.addEventListener('change', async () => {
      done = true;
      const f = input.files[0];
      if (!f) return resolve(null);
      resolve({ name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) });
    });
    window.addEventListener('focus', () => setTimeout(() => { if (!done) resolve(null); }, 800), { once: true });
    input.click();
  });
}

async function browserDownload(name, bytes) {
  const url = URL.createObjectURL(new Blob([bytes], {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }));
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  // A browser download cannot confirm that the file was written.
  return { saved: null, browser: true };
}
