"""Browser verification of monitor navigation and saved demo results (legacy command name)."""

import json
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from modelshield.config import ROOT
from scripts.experiment_support import local_server


def main():
    checks, errors = [], []
    with TemporaryDirectory(prefix="modelshield-jury-check-") as temp, local_server(
        temp
    ) as (url, _):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1100})
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url + "/dashboard#requirements", wait_until="networkidle")
            expect(page.locator("#live-view")).to_be_visible()
            expect(page.locator("#connection")).to_contain_text("Monitor connected")
            expect(page.locator("#total-requests")).to_have_text("0")
            checks.append("Old dashboard bookmarks open live monitoring")
            page.locator('a[href="#protection"]').click()
            expect(page.locator("#protection")).to_be_in_viewport()
            expect(page.locator(".protection-stage")).to_have_count(5)
            page.locator("#live-tab").click()
            expect(page.locator("#page-title")).to_be_in_viewport()
            checks.append("Live monitoring and protection navigation remain usable")
            page.goto(url + "/dashboard#feature-demo")
            expect(page.locator("#feature-demo")).to_be_in_viewport()
            expect(page.locator(".feature-demo-card")).to_have_count(18)
            card = page.locator('[data-feature="conversation"]')
            card.locator("summary").click()
            expect(card.locator(".feature-proof button").first).to_be_visible()
            card.locator(".feature-proof button").first.click()
            expect(page.locator("#detail-body")).to_contain_text("Maya")
            page.locator("#close-detail").click()
            assert context.request.get(url + "/api/chat/snapshot").json()["totals"]["requests"] == 0
            checks.append("Saved feature results display real request evidence without generating traffic")
            small_chat = context.new_page()
            small_chat.set_viewport_size({"width": 390, "height": 844})
            small_chat.goto(url + "/chat")
            expect(small_chat.locator("#use-bulk-pass")).to_be_hidden()
            small_chat.locator("#batch-tab").click()
            small_chat.locator("#batch-options summary").click()
            expect(small_chat.locator("#use-bulk-pass")).to_be_visible()
            expect(small_chat.locator("#bulk-access-status")).to_be_visible()
            small_chat.locator("#use-bulk-pass").uncheck()
            expect(small_chat.locator("#use-bulk-pass")).not_to_be_checked()
            assert small_chat.evaluate("document.documentElement.scrollWidth <= innerWidth")
            small_chat.close()
            checks.append("Batch options stay out of conversations and remain usable in a narrow chatbot window")
            page.goto(url + "/dashboard#live")
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(ROOT / "reports/monitor-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            checks.append(
                "Monitor metrics and controls fit a mobile viewport"
            )
            assert not errors, errors
            checks.append("No browser JavaScript errors")
            result = {"status": "passed", "checks": checks, "javascript_errors": errors}
            (ROOT / "reports/requirements-check.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            print(json.dumps(result, indent=2), flush=True)
            browser.close()


if __name__ == "__main__":
    main()
