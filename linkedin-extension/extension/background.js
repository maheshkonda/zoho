// Background worker: the only part of the extension that talks to the portal.
// Content scripts ask it to make API calls, so the agent token never touches
// the LinkedIn page and portal requests are not subject to the page's CORS.
const DEFAULTS = { portalUrl: 'http://localhost:8091', token: '' };

async function config() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(['portalUrl', 'token'])) };
}

async function api(method, path, body) {
  const cfg = await config();
  if (!cfg.token) throw new Error('Not signed in: set your agent token in the extension options');
  const res = await fetch(cfg.portalUrl.replace(/\/$/, '') + path, {
    method,
    headers: { 'Authorization': 'Bearer ' + cfg.token, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === 'api') {
    api(msg.method, msg.path, msg.body)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((e) => sendResponse({ ok: false, error: String(e.message || e) }));
    return true; // async response
  }
  return false;
});
