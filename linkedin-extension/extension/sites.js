// Page adapters: how to read conversations and find the compose box on each
// site. content.js only talks to these functions, so a LinkedIn layout change
// is fixed here without touching the sync logic.
//
// IMPORTANT: the `linkedin` adapter's selectors are a best guess at
// LinkedIn's current markup and have NOT been verified against a live
// account. They must be calibrated on a real logged-in LinkedIn and Sales
// Navigator session before a pilot. The `mock` adapter matches the local
// test page served by linkedin-extension/dev_server.py.
(() => {
  const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');

  function setContentEditable(el, value) {
    el.focus();
    el.textContent = value;
    el.dispatchEvent(new InputEvent('input', { bubbles: true }));
  }

  const mock = {
    name: 'mock',
    pollMs: 2000,
    matches: (loc) => loc.pathname.startsWith('/mock-linkedin/'),
    isMessaging: (loc) => loc.pathname.startsWith('/mock-linkedin/messaging'),
    isProfile: (loc) => loc.pathname.startsWith('/mock-linkedin/in/'),
    profileUrl: (loc) => 'https://www.linkedin.com/in/' + loc.pathname.split('/in/')[1].replace(/\/$/, ''),
    openThread() {
      const conv = document.querySelector('#conversation[data-thread-id]');
      if (!conv) return null;
      const who = conv.querySelector('a.participant');
      return {
        thread_key: conv.dataset.threadId,
        participant_name: text(who),
        profile_url: who ? who.dataset.profileUrl : null,
        thread_url: location.origin + '/mock-linkedin/messaging?thread=' + encodeURIComponent(conv.dataset.threadId),
        messages: [...conv.querySelectorAll('li.message')].map((m) => ({
          id: m.dataset.messageId,
          from_me: m.dataset.fromMe === 'true',
          text: text(m.querySelector('.body')),
          sent_at: m.dataset.sentAt || null,
        })),
      };
    },
    threadList() {
      return [...document.querySelectorAll('#conversations li.conv')].map((li) => ({
        thread_key: li.dataset.threadId,
        participant_name: li.dataset.name,
        profile_url: li.dataset.profileUrl || null,
        thread_url: location.origin + '/mock-linkedin/messaging?thread=' + encodeURIComponent(li.dataset.threadId),
      }));
    },
    composeBox: () => document.querySelector('#compose'),
    composeText: (el) => el.textContent,
    fillCompose: setContentEditable,
    sendButton: () => document.querySelector('#send'),
  };

  // LinkedIn messaging (/messaging/thread/<id>/) and Sales Navigator inbox
  // (/sales/inbox/<id>). UNVERIFIED selectors — see the note at the top.
  const linkedin = {
    name: 'linkedin',
    pollMs: 15000,
    matches: (loc) => /(^|\.)linkedin\.com$/.test(loc.hostname),
    isMessaging: (loc) => /^\/(messaging|sales\/inbox)\//.test(loc.pathname),
    isProfile: (loc) => /^\/(in|sales\/lead)\//.test(loc.pathname),
    profileUrl: (loc) => loc.origin + loc.pathname,
    openThread() {
      const m = location.pathname.match(/^\/(?:messaging\/thread|sales\/inbox)\/([^/]+)/);
      if (!m) return null;
      const profileLink = document.querySelector(
        'a.msg-thread__link-to-profile, .msg-entity-lockup a[href*="/in/"], a[href*="/sales/lead/"]');
      const name = text(document.querySelector(
        '.msg-entity-lockup__entity-title, #thread-detail-jump-target, .conversation-insights__name'));
      if (!name) return null;
      const events = [...document.querySelectorAll('.msg-s-message-list__event, .message-item')];
      let lastSender = '';
      const messages = events.map((ev, i) => {
        const sender = text(ev.querySelector('.msg-s-message-group__name, .message-item__sender')) || lastSender;
        lastSender = sender;
        const body = text(ev.querySelector('.msg-s-event-listitem__body, .message-item__body'));
        const urn = ev.getAttribute('data-event-urn') || ev.getAttribute('data-id');
        return {
          id: urn || `${m[1]}:${i}:${body.slice(0, 40)}`,
          from_me: ev.querySelector('.msg-s-event-listitem--other') === null && sender !== name,
          text: body,
          sent_at: (ev.querySelector('time') || {}).dateTime || null,
        };
      }).filter((x) => x.text);
      return {
        thread_key: m[1], participant_name: name,
        profile_url: profileLink ? profileLink.href : null,
        thread_url: location.origin + location.pathname, messages,
      };
    },
    threadList() {
      return [...document.querySelectorAll('.msg-conversation-listitem, .conversation-list-item')].map((li) => {
        const a = li.querySelector('a[href*="/messaging/thread/"], a[href*="/sales/inbox/"]');
        const key = a ? (a.getAttribute('href').match(/\/(?:messaging\/thread|sales\/inbox)\/([^/?]+)/) || [])[1] : null;
        return key && {
          thread_key: key,
          participant_name: text(li.querySelector('.msg-conversation-listitem__participant-names, .conversation-list-item__name')),
          thread_url: a.href,
        };
      }).filter((t) => t && t.participant_name);
    },
    composeBox: () => document.querySelector('.msg-form__contenteditable, textarea[name="message"]'),
    composeText: (el) => (el.value !== undefined ? el.value : el.textContent),
    fillCompose(el, value) {
      if (el.value !== undefined) {
        el.focus(); el.value = value; el.dispatchEvent(new Event('input', { bubbles: true }));
      } else setContentEditable(el, value);
    },
    sendButton: () => document.querySelector('.msg-form__send-button, button[type="submit"].message-send'),
  };

  window.BL_SITE = [mock, linkedin].find((s) => s.matches(location)) || null;
})();
