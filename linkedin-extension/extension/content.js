// Runs inside the agent's LinkedIn tab.
//
// 1. Sync: reads the conversations the agent has on screen and sends them to
//    the portal. It never navigates, scrolls or clicks on its own.
// 2. Replies: picks up replies written in the portal for this agent, fills the
//    open conversation's compose box, and records SENT when the agent clicks
//    LinkedIn's own Send button. Nothing is ever sent without that click.
// 3. Ownership: on a profile page, shows who owns the contact and the last
//    touch on any channel, so two agents don't approach the same person.
(() => {
  const site = window.BL_SITE;
  if (!site) return;

  const call = (method, path, body) => new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'api', method, path, body }, (res) => {
      resolve(res || { ok: false, error: (chrome.runtime.lastError || {}).message || 'no response' });
    });
  });

  // ---------------------------------------------------------------- panel
  const panel = document.createElement('div');
  panel.id = 'bl-panel';
  panel.innerHTML = '<div class="bl-title">BookLender</div><div class="bl-status"></div><div class="bl-items"></div>';
  document.documentElement.appendChild(panel);
  const setStatus = (msg, kind = '') => {
    const el = panel.querySelector('.bl-status');
    el.textContent = msg;
    el.className = 'bl-status ' + kind;
  };

  // ----------------------------------------------------------------- sync
  let lastSent = '';
  async function syncNow() {
    if (!site.isMessaging(location)) return;
    const open = site.openThread();
    const threads = open ? [open] : [];
    for (const t of site.threadList()) {
      if (!open || t.thread_key !== open.thread_key) threads.push({ ...t, messages: [] });
    }
    if (!threads.length) return;
    const signature = JSON.stringify(threads);
    if (signature === lastSent) return;
    const res = await call('POST', '/linkedin/ext/sync', { threads });
    if (!res.ok) { setStatus('Sync failed: ' + res.error, 'bl-err'); return; }
    lastSent = signature;
    const collision = res.data.threads.some((t) => t.collision);
    setStatus(collision
      ? 'Synced. Note: this contact is owned by another agent.'
      : `Synced ${threads.length} conversation(s) to the portal`, collision ? 'bl-warn' : 'bl-ok');
  }

  let syncTimer = null;
  const scheduleSync = () => { clearTimeout(syncTimer); syncTimer = setTimeout(syncNow, 600); };
  new MutationObserver((mutations) => {
    if (mutations.some((m) => !panel.contains(m.target))) scheduleSync();
  }).observe(document.body, { childList: true, subtree: true, characterData: true });

  // --------------------------------------------------------------- outbox
  const filled = new Map(); // outbox_id -> { thread_key, body }

  async function pollOutbox() {
    const res = await call('GET', '/linkedin/ext/outbox');
    if (!res.ok) return;
    const open = site.isMessaging(location) ? site.openThread() : null;
    const waitingElsewhere = [];
    for (const item of res.data.items) {
      if (open && item.thread_key === open.thread_key) {
        if (filled.has(item.outbox_id)) continue;
        const box = site.composeBox();
        if (box && !site.composeText(box).trim()) {
          site.fillCompose(box, item.body);
          filled.set(item.outbox_id, { thread_key: item.thread_key, body: item.body });
          await call('POST', `/linkedin/ext/outbox/${item.outbox_id}/status`, { status: 'FILLED' });
          setStatus('Reply from the portal is ready. Review it and click Send.', 'bl-warn');
        }
      } else {
        waitingElsewhere.push(item);
      }
    }
    const items = panel.querySelector('.bl-items');
    items.innerHTML = '';
    for (const item of waitingElsewhere) {
      const a = document.createElement('a');
      a.href = item.thread_url || '#';
      a.textContent = `Reply waiting for ${item.participant_name}: open conversation`;
      items.appendChild(a);
    }
  }

  // The agent clicks LinkedIn's own Send button; we only record that it happened.
  document.addEventListener('click', (e) => {
    const btn = site.sendButton();
    if (!btn || !btn.contains(e.target)) return;
    const box = site.composeBox();
    const finalText = box ? site.composeText(box).trim() : '';
    const open = site.openThread();
    for (const [id, item] of filled) {
      if (open && item.thread_key === open.thread_key && finalText) {
        filled.delete(id);
        call('POST', `/linkedin/ext/outbox/${id}/status`, { status: 'SENT', body: finalText }).then((res) => {
          setStatus(res.ok ? 'Sent. Recorded in the portal.' : 'Could not record send: ' + res.error,
            res.ok ? 'bl-ok' : 'bl-err');
          setTimeout(syncNow, 800);
        });
      }
    }
  }, true);

  // -------------------------------------------------------- profile banner
  async function profileBanner() {
    document.getElementById('bl-banner')?.remove();
    if (!site.isProfile(location)) return;
    const res = await call('GET', '/linkedin/ext/profile?url=' + encodeURIComponent(site.profileUrl(location)));
    if (!res.ok) return;
    const d = res.data;
    const banner = document.createElement('div');
    banner.id = 'bl-banner';
    if (!d.known) {
      banner.textContent = 'BookLender: not in the CRM yet.';
    } else {
      const touch = d.last_touch
        ? ` · last contact: ${d.last_touch.channel} ${d.last_touch.direction === 'IN' ? 'from them' : 'by ' + (d.last_touch.agent || 'us')}`
        : '';
      banner.textContent = d.owned_by_you
        ? `BookLender: your contact · status ${d.status}${touch}`
        : `BookLender: owned by ${d.owner || 'nobody'} · status ${d.status}${touch}. Check with them before reaching out.`;
      if (!d.owned_by_you) banner.className = 'bl-other';
    }
    document.body.prepend(banner);
  }

  // ------------------------------------------------- page / SPA navigation
  let lastHref = '';
  function onPage() {
    if (location.href === lastHref) return;
    lastHref = location.href;
    lastSent = '';
    profileBanner();
    scheduleSync();
  }
  setInterval(onPage, 1000);
  setInterval(pollOutbox, site.pollMs);
  onPage();
  pollOutbox();
})();
