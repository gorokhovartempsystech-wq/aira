// Direct calls for routes that the desktop client modules do not wrap:
// document list, structural view, DOCX bytes for images/numbering and licence state.
// All of them are in the licensed desktop allowlist (docs/d05-01-contract.md).

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.code || `http_${status}`);
    this.status = status;
    this.code = body?.code || null;
    this.retryable = !!body?.retryable;
  }
}

export function createApi({ origin, sessionToken }) {
  async function request(path, { method = 'GET', json, binary = false, timeoutMs } = {}) {
    let r;
    try {
      r = await fetch(origin + path, {
        method,
        ...(timeoutMs ? { signal: AbortSignal.timeout(timeoutMs) } : {}),
        headers: { 'X-AIRA-Session': sessionToken, Accept: binary ? '*/*' : 'application/json',
          ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}) },
        body: json !== undefined ? JSON.stringify(json) : undefined,
        cache: 'no-store', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer',
      });
    } catch {
      throw new ApiError(0, { code: 'transport_error', retryable: true });
    }
    if (binary && r.ok) return new Uint8Array(await r.arrayBuffer());
    let body = null;
    try { body = await r.json(); } catch { body = null; }
    if (!r.ok) throw new ApiError(r.status, body);
    return { status: r.status, body };
  }
  const doc = id => `/docx-documents/${id}`;
  return {
    onboarding: () => request('/aira/onboarding', { timeoutMs: 5000 }).then(x => x.body),
    markOnboarding: (kind, status) => request(`/aira/onboarding/${kind}`, {
      method: 'POST', json: { status }, timeoutMs: 5000,
    }).then(x => x.body),
    updates: (refresh = false) => request('/aira/updates' + (refresh ? '?refresh=1' : ''), { timeoutMs: 10000 }).then(x => x.body),
    async listDocuments() {
      const { body } = await request('/docx-documents');
      return Array.isArray(body?.items) ? body.items : [];
    },
    async recovery(documentId) {
      const { body } = await request(`${doc(documentId)}/editor-recovery`);
      return body;
    },
    async view(documentId, sessionId) {
      const { body } = await request(`${doc(documentId)}/editor-sessions/${sessionId}/view`);
      return body;
    },
    savedBytes: documentId => request(`${doc(documentId)}/content`, { binary: true }),
    workingBytes: (documentId, snapshot) => request(
      `${doc(documentId)}/editor-sessions/${snapshot.session_id}/working-content`, {
        method: 'POST', binary: true, json: {
          expected_command_sequence: snapshot.command_sequence,
          expected_session_revision: snapshot.document.session_revision,
          expected_sha256: snapshot.document.source_sha256,
        } }),
    async licence() {
      try { return (await request('/desktop/license')).body; } catch (e) {
        if (e.status === 404) return null; // no licence wrapper on this stand
        throw e;
      }
    },
    activate: key => request('/desktop/license/activate', { method: 'POST', json: { license_key: key } }).then(x => x.body),
    verify: () => request('/desktop/license/verify', { method: 'POST', json: {} }).then(x => x.body),
  };
}
