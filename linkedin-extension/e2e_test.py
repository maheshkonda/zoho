#!/usr/bin/env python3
"""End-to-end check of the extension in a real Chromium, against the local
mock LinkedIn page and portal (no LinkedIn account involved).

    pip install playwright
    python linkedin-extension/e2e_test.py [--shots DIR]

Uses the Chromium that Playwright finds; set CHROMIUM_PATH to use another.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dev_server  # noqa: E402

PORT = 8097
BASE = f"http://localhost:{PORT}"
REPLY = "Hi Jane, for 800 employees it is about $4 per employee per month. Happy to walk you through it."


def start_server():
    os.environ[dev_server.TOKENS_ENV] = "priya:dev-priya,raj:dev-raj"
    server = uvicorn.Server(uvicorn.Config(dev_server.create_app(), host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            httpx.get(BASE + "/portal", timeout=1)
            return server
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError("dev server did not start")


def api(path, token="dev-priya", method="GET", json=None):
    r = httpx.request(method, BASE + path, headers={"Authorization": "Bearer " + token}, json=json)
    return r.status_code, r.json()


def wait_for(cond, what, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.25)
    raise AssertionError("timed out waiting for: " + what)


def step(msg):
    print("  ✓", msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=None, help="directory for screenshots")
    args = ap.parse_args()
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    def shot(page, name):
        if shots:
            page.screenshot(path=str(shots / f"{name}.png"), full_page=False)

    start_server()
    ext = str(HERE / "extension")
    with sync_playwright() as p, tempfile.TemporaryDirectory() as profile:
        launch = dict(
            headless=False,
            args=["--headless=new", f"--disable-extensions-except={ext}", f"--load-extension={ext}"],
            viewport={"width": 1280, "height": 800},
        )
        if os.environ.get("CHROMIUM_PATH"):
            launch["executable_path"] = os.environ["CHROMIUM_PATH"]
        ctx = p.chromium.launch_persistent_context(profile, **launch)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        ext_id = sw.url.split("/")[2]

        def sign_in(token):
            opts = ctx.new_page()
            opts.goto(f"chrome-extension://{ext_id}/options.html")
            opts.fill("#portalUrl", BASE)
            opts.fill("#token", token)
            opts.click("#save")
            expect(opts.locator("#result")).to_contain_text("Connected as")
            opts.close()

        print("Agent Priya")
        sign_in("dev-priya")
        step("extension signed in to the portal as priya")

        li = ctx.new_page()
        li.goto(BASE + "/mock-linkedin/messaging?thread=thread-2a9f")
        expect(li.locator("#bl-panel .bl-status")).to_contain_text("Synced", timeout=10000)
        _, data = api("/linkedin/portal/threads")
        names = {t["contact"]["name"]: t for t in data["threads"] if t["channel"] == "linkedin"}
        assert {"Jane Whitfield", "Marcus Lee"} <= set(names), names.keys()
        jane = names["Jane Whitfield"]
        assert jane["awaiting_reply"] and jane["contact"]["owner"] == "priya"
        _, detail = api(f"/linkedin/portal/threads/{jane['thread_id']}")
        assert [m["channel"] for m in detail["timeline"]] == ["email", "linkedin", "linkedin"]
        assert names["Marcus Lee"]["contact"]["source"] == "linkedin-inbox"
        step("LinkedIn threads synced; Jane matched to her CRM record (email + LinkedIn in one timeline)")
        step("Marcus Lee (not in CRM) created as a new contact")
        shot(li, "1-linkedin-synced")

        portal = ctx.new_page()
        portal.goto(BASE + "/portal")
        portal.fill("#token", "dev-priya")
        portal.click("#signin")
        portal.locator(".thread", has_text="Jane Whitfield").filter(has_text="LinkedIn").first.click()
        expect(portal.locator("#timeline")).to_contain_text("Could you share pricing")
        expect(portal.locator("#timeline")).to_contain_text("learning stipend")
        portal.fill("#replyText", REPLY)
        portal.click("#sendReply")
        expect(portal.locator("#timeline")).to_contain_text("queued for the LinkedIn tab")
        step("Priya replied from the portal; reply queued for her browser")
        shot(portal, "2-portal-reply-queued")

        li.bring_to_front()
        expect(li.locator("#compose")).to_have_text(REPLY, timeout=10000)
        wait_for(lambda: api("/linkedin/ext/outbox")[1]["items"][0]["status"] == "FILLED", "outbox FILLED")
        expect(li.locator("#bl-panel .bl-status")).to_contain_text("click Send")
        step("extension filled the reply into LinkedIn's compose box (not sent)")
        shot(li, "3-linkedin-reply-filled")

        li.click("#send")
        expect(li.locator("#messages")).to_contain_text("$4 per employee")
        wait_for(lambda: not api("/linkedin/ext/outbox")[1]["items"], "outbox cleared after Send")
        expect(li.locator("#bl-panel .bl-status")).to_contain_text("Recorded in the portal", timeout=10000)
        time.sleep(2)  # let the post-send resync run
        _, detail = api(f"/linkedin/portal/threads/{jane['thread_id']}")
        copies = [m for m in detail["timeline"] if m["body"] == REPLY]
        assert len(copies) == 1 and copies[0]["via"] == "portal", copies
        step("Priya clicked Send in LinkedIn; recorded once in the portal (no duplicate after resync)")

        li.click("#simulate")
        wait_for(lambda: any(t["awaiting_reply"] and t["contact"]["name"] == "Jane Whitfield"
                             for t in api("/linkedin/portal/threads")[1]["threads"]), "new inbound synced")
        portal.bring_to_front()
        expect(portal.locator("#timeline")).to_contain_text("set up a call next week", timeout=10000)
        step("new incoming LinkedIn message appeared in the portal as 'Awaiting reply'")
        _, detail = api(f"/linkedin/portal/threads/{jane['thread_id']}")
        assert len([m for m in detail["timeline"] if m["body"] == REPLY]) == 1, "portal reply duplicated"
        step("portal reply still recorded exactly once after further syncs")
        shot(portal, "4-portal-timeline")

        code, _ = api(f"/linkedin/portal/contacts/{jane['contact_id']}", method="POST",
                      json={"status": "HOT", "category": "HR"})
        assert code == 200
        step("Priya set Jane's status to HOT")

        print("Agent Raj (different agent, same browser profile switched)")
        sign_in("dev-raj")
        prof = ctx.new_page()
        prof.goto(BASE + "/mock-linkedin/in/jwhitfield-people")
        expect(prof.locator("#bl-banner")).to_contain_text("owned by priya", timeout=10000)
        expect(prof.locator("#bl-banner")).to_contain_text("HOT")
        step("Raj opens Jane's profile: banner warns she is owned by priya (status HOT)")
        shot(prof, "5-profile-banner-raj")

        code, body = api(f"/linkedin/portal/threads/{jane['thread_id']}/reply", token="dev-raj",
                         method="POST", json={"text": "Hi Jane, Raj here"})
        assert code == 409 and "priya" in body["detail"], body
        step("Raj's reply from the portal is blocked (409: owned by priya)")

        ctx.close()
    print("\nAll end-to-end checks passed.")


if __name__ == "__main__":
    main()
