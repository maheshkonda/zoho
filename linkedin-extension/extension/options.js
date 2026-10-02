const $ = (id) => document.getElementById(id);

chrome.storage.local.get(['portalUrl', 'token']).then((cfg) => {
  $('portalUrl').value = cfg.portalUrl || 'http://localhost:8091';
  $('token').value = cfg.token || '';
});

$('save').onclick = async () => {
  const portalUrl = $('portalUrl').value.trim().replace(/\/$/, '');
  const token = $('token').value.trim();
  const out = $('result');
  try {
    // A hosted portal (https) needs host permission, granted once here.
    if (portalUrl.startsWith('https://')) {
      const granted = await chrome.permissions.request({ origins: [portalUrl + '/*'] });
      if (!granted) throw new Error('Permission to reach the portal was not granted');
    }
    await chrome.storage.local.set({ portalUrl, token });
    const res = await chrome.runtime.sendMessage({ type: 'api', method: 'GET', path: '/linkedin/ext/me' });
    if (!res.ok) throw new Error(res.error);
    out.className = 'ok';
    out.textContent = 'Connected as ' + res.data.agent;
  } catch (e) {
    out.className = 'err';
    out.textContent = String(e.message || e);
  }
};
