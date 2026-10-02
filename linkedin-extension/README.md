# LinkedIn / Sales Navigator sync (Chrome extension prototype)

Brings LinkedIn conversations into the BookLender portal and lets agents
reply from the portal, without logging into LinkedIn from a server.

| What Krishna asked for | How the prototype does it |
|---|---|
| LinkedIn / Sales Navigator replies appear in the portal | The extension reads the conversations the agent has open in LinkedIn and sends them to the portal |
| Reply from the portal | The reply is queued for the agent's browser; the extension fills it into LinkedIn's compose box and the **agent clicks Send** |
| Status shows "replied", lead category set in the portal | Thread shows *Awaiting reply* / *sent from portal*; owner sets status and category |
| One view per person | LinkedIn threads are matched to the CRM contact by profile URL, so email and LinkedIn appear in one timeline |
| Two agents never contact the same person unknowingly | One owner per contact; other agents can't reply from the portal (409), and see an "owned by …" banner on that person's LinkedIn profile |

## Why it's built this way (ban risk)

Nothing logs into LinkedIn from a server, and nothing is automated inside
LinkedIn: the extension **reads only what is already on the agent's screen,
never navigates or scrolls on its own, and never clicks Send**. LinkedIn sees
a normal person using LinkedIn in their own browser. That keeps the risk of
account restrictions low. It is not zero: LinkedIn's terms don't allow
extensions to collect data from its pages.

Limits that follow from this design:
- Messages sync while the agent has LinkedIn open in Chrome.
- A reply from the portal goes out when the agent next has that conversation open and clicks Send.
- Past conversations (the last ~10 months) sync as agents open them. A guided "work through history" mode is a planned addition.

## Try it locally

```bash
pip install -r requirements.txt
python linkedin-extension/dev_server.py
```

Then:

1. In Chrome, open `chrome://extensions`, turn on **Developer mode**, click
   **Load unpacked**, and choose the `linkedin-extension/extension` folder.
2. Click the extension icon. Portal URL `http://localhost:8091`, token `dev-priya`, then **Save and test**.
3. Open the mock LinkedIn page: http://localhost:8091/mock-linkedin/messaging.
   The BookLender panel (bottom right) says "Synced".
4. Open the portal: http://localhost:8091/portal and sign in with `dev-priya`.
   Jane shows her email and LinkedIn messages in one timeline; Marcus was
   created from LinkedIn.
5. Reply to Jane in the portal. Switch to the mock LinkedIn tab: the reply is
   filled in. Click **Send**; the portal shows it as *sent from portal*.
6. Click **Simulate incoming message** on the mock page; the portal marks
   Jane *Awaiting reply*.
7. Switch the extension token to `dev-raj` and open
   http://localhost:8091/mock-linkedin/in/jwhitfield-people: the banner says
   Jane is owned by priya. Signing in to the portal as `dev-raj`, replying to
   Jane is blocked.

**Reset mock** on the mock page restores its seed conversations; restarting
the server resets the portal data.

### Automated checks

```bash
cd middleware && python -m pytest tests/test_linkedin_inbox.py -v   # backend
pip install playwright
python linkedin-extension/e2e_test.py --shots /tmp/shots            # real Chromium + extension
```

`e2e_test.py` loads the extension into Chromium and runs steps 2–7 above. Set
`CHROMIUM_PATH` if Playwright's own browser isn't installed.

## Before a pilot on real LinkedIn

- **Calibrate the selectors.** `extension/sites.js` has two adapters: `mock`
  (tested) and `linkedin`. The `linkedin` selectors are a best guess at
  LinkedIn's markup and have **not** been run against a live account.
  Calibrate them on a real LinkedIn messaging page and a Sales Navigator inbox.
- **Portal hosting.** Point the extension at the hosted portal URL (https).
  The options page asks for permission to reach it once.
- **Agent tokens.** Set `LINKEDIN_AGENT_TOKENS=name:token,…` on the
  middleware. These are per-agent secrets; give each agent their own.
- **Distribution.** Load unpacked for the pilot. For the team, publish
  privately in the Chrome Web Store, or push it through Google Workspace admin.
- **Zoho write-back.** Status, category and LinkedIn activity are stored in
  the middleware's inbox store. Writing them to Zoho Contacts is the next step.

## Files

```
extension/manifest.json   Chrome MV3 manifest
extension/background.js   the only part that calls the portal API (holds the token)
extension/content.js      sync, reply fill-in, Send detection, profile banner
extension/sites.js        page adapters: mock (tested) and linkedin (to calibrate)
extension/options.html    portal URL + agent token
mock/                     mock LinkedIn messaging and profile pages
dev_server.py             portal + API + mock on http://localhost:8091
e2e_test.py               end-to-end test in Chromium
```

Backend: `middleware/booklender/inbox.py` (store),
`middleware/booklender/linkedin_api.py` (API), and
`middleware/booklender/static/portal.html` (inbox page). The production
middleware serves the same API and page (`/linkedin/*`, `/portal`).
