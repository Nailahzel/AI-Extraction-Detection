"""Real browser smoke test; saves desktop and mobile evidence screenshots."""

import argparse
import json
import re

from playwright.sync_api import sync_playwright, expect
from modelshield.config import ROOT


def run(url, channel, layout_only=False):
    errors = []
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1080}, device_scale_factor=1
        )
        page.emulate_media(reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/classifier-lab", wait_until="networkidle")
        page.wait_for_selector("#connection:has-text('System online')")
        if layout_only:
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload(wait_until="networkidle")
            print(
                page.evaluate(
                    "() => ({width:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth,items:[...document.querySelectorAll('body *')].filter(e=>e.scrollWidth>e.clientWidth+2).map(e=>({tag:e.tagName,cls:String(e.className),client:e.clientWidth,scroll:e.scrollWidth,right:e.getBoundingClientRect().right,overflow:getComputedStyle(e).overflow,display:getComputedStyle(e).display})).slice(0,30)})"
                )
            )
            browser.close()
            return
        # Reset through the actual administrator UI.
        page.locator("a.nav-item[data-page='lab']").click()
        page.locator("#reset-button").click()
        page.locator("#confirm-reset").click()
        expect(page.locator("#metric-requests")).to_have_text("0")
        expect(page.locator("#predict-text")).to_be_in_viewport()
        expect(page.locator("#toast")).to_be_hidden(timeout=7000)
        page.screenshot(path=str(reports / "playground.png"), full_page=True)
        page.locator("a.nav-item[data-page='overview']").click()
        page.screenshot(path=str(reports / "dashboard-idle.png"), full_page=True)
        page.locator("#demo-button").click()
        expect(page.locator("#metric-denied")).not_to_have_text("0", timeout=20000)
        expect(page.locator("#metric-requests")).to_have_text(
            re.compile(r"^(?:[7-9]\d|[1-9]\d{2,})$"), timeout=20000
        )
        page.screenshot(path=str(reports / "dashboard.png"), full_page=True)
        page.locator(".overview-bottom").screenshot(
            path=str(reports / "alert-evidence.png")
        )
        page.locator(".alert-item").first.click()
        expect(page.locator("#incident-dialog")).to_be_visible()
        expect(page.locator("#incident-content")).to_contain_text("Signals at the time")
        recorded = page.locator("#incident-content").inner_text()
        with page.expect_download() as incident_download:
            page.locator("#download-incident").click()
        assert incident_download.value.suggested_filename.startswith("ALT-")
        page.screenshot(path=str(reports / "incident.png"), full_page=True)
        page.wait_for_timeout(1100)
        assert page.locator("#incident-content").inner_text() == recorded
        page.locator("[data-close='incident-dialog']").click()
        page.locator("tr[data-client='attacker-01']").click()
        page.wait_for_selector("#detail-dialog[open]")
        assert "Signal contributions" in page.locator("#detail-content").inner_text()
        page.screenshot(path=str(reports / "investigation.png"), full_page=True)
        page.locator("[data-close='detail-dialog']").first.click()
        page.locator("a.nav-item[data-page='traffic']").click()
        assert page.locator("#event-table tr").count() > 0
        page.locator("a.nav-item[data-page='policy']").click()
        assert page.locator("#policy-bands .policy-band").count() == 4
        page.locator("a.nav-item[data-page='validation']").click()
        page.wait_for_selector(".validation-metric", timeout=10000)
        expect(page.locator("#experiment-content")).to_contain_text(
            "Can the API answers train a copy?"
        )
        expect(page.locator("#experiment-content")).to_contain_text(
            "Compare the defenses"
        )
        page.locator("#experiment-content").screenshot(
            path=str(reports / "experiments.png")
        )
        with page.expect_download() as download:
            page.locator("#download-results").click()
        assert download.value.suggested_filename == "modelshield-benchmark.json"
        page.locator("#stop-demo").click()
        page.locator("a.nav-item[data-page='lab']").click()
        page.locator("#predict-form button[type='submit']").click()
        page.wait_for_selector("#predict-result:has-text('HTTP 200')")
        page.locator("#predict-text").fill(
            "Absolutely fantastic—another update that crashes every ten minutes and deletes all my work. Exactly what I needed!”"
        )
        page.locator("#predict-form button[type='submit']").click()
        expect(page.locator("#predict-result")).to_contain_text('"label": "negative"')
        expect(page.locator("#predict-result")).to_contain_text("HTTP 200")
        page.locator("#reset-button").click()
        page.locator("#confirm-reset").click()
        expect(page.locator("#metric-requests")).to_have_text("0")
        page.locator("[data-scenario='distributed']").click()
        expect(page.locator("#campaign-count")).not_to_have_text("0", timeout=20000)
        page.locator("a.nav-item[data-page='campaigns']").click()
        page.wait_for_selector(".campaign-card")
        page.screenshot(path=str(reports / "campaign.png"), full_page=True)
        page.locator("#stop-demo").click()
        page.locator("a.nav-item[data-page='overview']").click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(url + "/classifier-lab#overview", wait_until="networkidle")
        page.wait_for_selector("#connection:has-text('System online')")
        expect(page.locator("#toast")).to_be_hidden(timeout=7000)
        page.screenshot(path=str(reports / "dashboard-mobile.png"), full_page=True)
        overflow = page.evaluate(
            "[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1 && getComputedStyle(e).position!=='fixed' && e.closest('.table-scroll')===null).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right})).slice(0,15)"
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        ), f"Mobile page overflows horizontally: {overflow}"
        page.locator("#menu-button").click()
        page.locator("a.nav-item[data-page='lab']").click()
        expect(page.locator("#page-lab")).to_be_visible()
        expect(page.locator("#predict-text")).to_be_in_viewport()
        page.screenshot(path=str(reports / "playground-mobile.png"), full_page=True)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        ), "Mobile lab overflows horizontally"
        browser.close()
    if errors:
        raise AssertionError(errors)
    result = {
        "status": "passed",
        "javascript_errors": errors,
        "checks": [
            "live telemetry",
            "guided simulation",
            "real HTTP 429 enforcement",
            "investigation drawer",
            "preserved incident evidence and JSON download",
            "saved copying and baseline experiments",
            "traffic log",
            "policy view",
            "benchmark download",
            "manual prediction",
            "manual input visible on desktop and mobile",
            "sarcastic complaint prediction",
            "reset",
            "cross-key campaign",
            "390px mobile layout",
            "mobile navigation",
        ],
    }
    (reports / "browser-check.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--channel", default="msedge", choices=["msedge", "chrome", "chromium"]
    )
    parser.add_argument(
        "--layout-only",
        action="store_true",
        help="Print mobile overflow diagnostics without running a simulation.",
    )
    args = parser.parse_args()
    run(args.url, args.channel, args.layout_only)
