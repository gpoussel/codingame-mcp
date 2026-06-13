"""Throwaway discovery tool: capture CodinGame write requests from the browser.

Launches a VISIBLE Chromium, opens the jump-the-queue puzzle, and records every
``POST .../services/...`` call (URL, positional-args body, response) to a JSONL
file as it happens. Log in (if not already), write a trivial solution, then
trigger Save / Play testcases / Submit -- each click appends a line.

Not part of the shipped package. Run with:

    uv run --with playwright python scripts/capture_codingame.py

If CODINGAME_REMEMBER_ME is set it is injected so you start logged in; otherwise
just log in manually in the window. Close the browser window to stop and flush.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from playwright.sync_api import Response, sync_playwright

PUZZLE_URL = "https://www.codingame.com/training/easy/jump-the-queue"
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_PATH = SCRIPT_DIR / "captured.jsonl"
# Persistent browser profile so a manual login survives across relaunches.
PROFILE_DIR = SCRIPT_DIR / ".pw-profile"
# A local, gitignored file holding the rememberMe cookie. The user creates it
# themselves so the secret never passes through the assistant transcript.
COOKIE_FILE = SCRIPT_DIR / ".remember_me"
COOKIE_DOMAIN = "www.codingame.com"


def _read_cookie() -> str:
    """Return the rememberMe cookie from the local file, else the env var."""
    if COOKIE_FILE.exists():
        value = COOKIE_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    return os.environ.get("CODINGAME_REMEMBER_ME", "").strip()


def main() -> None:
    out = OUT_PATH.open("w", encoding="utf-8")
    seen = 0

    def on_response(response: Response) -> None:
        nonlocal seen
        req = response.request
        if req.method != "POST" or "/services/" not in req.url:
            return
        try:
            body = response.text()
        except Exception:  # noqa: BLE001 - some responses are not retrievable
            body = None
        record = {
            "service": req.url.split("/services/", 1)[1],
            "url": req.url,
            "post_data": req.post_data,
            "status": response.status,
            "response": body,
        }
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
        out.flush()
        seen += 1
        print(f"[{seen}] {record['service']}  args={req.post_data}", flush=True)

    cookie = _read_cookie()

    with sync_playwright() as p:
        # Persistent context: the login from a previous run is reused, so an
        # accidental window close no longer forces logging in again.
        # AutomationControlled off reduces CodinGame's anti-debug `debugger;`
        # pauses ("debugger suspended") triggered when controlled via CDP.
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        if cookie:
            context.add_cookies(
                [{"name": "rememberMe", "value": cookie, "domain": COOKIE_DOMAIN, "path": "/"}]
            )
            print("Injected rememberMe cookie -> you should start logged in.", flush=True)
        else:
            print(
                "No cookie found. Either log in manually, or create scripts/.remember_me\n"
                "containing your rememberMe cookie value (gitignored, never shown to me).",
                flush=True,
            )

        context.on("response", on_response)

        page = context.pages[0] if context.pages else context.new_page()

        # CodinGame's anti-debug spams `debugger;` to freeze the page under CDP.
        # Tell the V8 debugger to never honour those pauses. Re-applied on every
        # navigation since a fresh document can reset the debugger agent state.
        cdp = context.new_cdp_session(page)
        cdp.send("Debugger.enable")
        cdp.send("Debugger.setSkipAllPauses", {"skip": True})

        def _reapply_skip(_frame) -> None:
            try:
                cdp.send("Debugger.setSkipAllPauses", {"skip": True})
            except Exception as exc:  # noqa: BLE001
                print(f"(skip-pauses reapply failed: {exc})", flush=True)

        page.on("framenavigated", _reapply_skip)

        page.goto(PUZZLE_URL)

        print(
            "\nBrowser open. Log in if needed, write a trivial solution, then click\n"
            "Save/Draft, Play testcases, and Submit. Close the window when done.\n"
            f"Captured calls are written live to: {OUT_PATH}\n",
            flush=True,
        )

        done = threading.Event()
        context.on("close", lambda: done.set())
        done.wait()

    out.close()
    print(f"\nDone. {seen} service calls captured in {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
