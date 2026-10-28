"""Exercise the manual batch UI in a real browser; resets the target demo session."""

import argparse
import json

from playwright.sync_api import expect, sync_playwright

from modelshield.config import ROOT


def run(url, channel="msedge"):
    errors, requests, checks = [], [], []
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1080})
        page.emulate_media(reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                requests.append(request.post_data_json)
                if request.url.endswith("/predict") and request.method == "POST"
                else None
            ),
        )
        page.goto(url + "/classifier-lab#lab", wait_until="networkidle")
        expect(page.locator("#connection")).to_contain_text("System online")
        page.locator("[data-input-mode='batch']").click()

        def snapshot():
            response = page.request.get(url + "/api/snapshot")
            assert response.ok
            return response.json()

        def reset():
            page.locator("#reset-button").click()
            page.locator("#confirm-reset").click()
            expect(page.locator("#confirm-dialog")).not_to_be_visible()
            expect(page.locator("#metric-requests")).to_have_text("0")
            requests.clear()

        def send_and_finish(count):
            page.locator("#batch-send").click()
            expect(page.locator("#batch-progress")).to_contain_text(
                f"Batch complete · {count} / {count}", timeout=30000
            )
            expect(page.locator("#batch-rows tr")).to_have_count(count)

        reset()
        page.locator("#batch-send").click()
        expect(page.locator("#batch-error")).to_contain_text("1–30 inputs")
        page.locator("#batch-text").fill("\n".join(["one input"] * 31))
        page.locator("#batch-send").click()
        expect(page.locator("#batch-error")).to_contain_text("1–30 inputs")
        page.locator("#batch-text").fill("x" * 2001)
        page.locator("#batch-send").click()
        expect(page.locator("#batch-error")).to_contain_text("2,000 characters")
        assert not requests and snapshot()["totals"]["requests"] == 0
        checks.append("empty, over-30 and overlong inputs rejected before sending")

        page.locator("[data-batch-example='ordinary']").click()
        ordinary = page.locator("#batch-text").input_value()
        assert not requests
        # Empty lines are separators, never extra API calls.
        page.locator("#batch-text").fill(
            "\n  \n" + ordinary.replace("\n", "\n\n") + "\n"
        )
        expect(page.locator("#batch-count")).to_have_text("15 / 30 inputs")
        send_and_finish(15)
        expect(page.locator("#batch-summary h3")).to_have_text("No flag observed")
        data = snapshot()
        assert data["totals"]["requests"] == 15 and data["totals"]["denied"] == 0
        assert not data["alerts"]
        assert [r["text"] for r in requests] == ordinary.splitlines()
        assert next(c for c in data["clients"] if c["id"] == "probe-01")["total"] == 15
        checks.append("15 ordinary inputs become 15 ordered API calls with no flag")

        reset()
        page.locator("[data-batch-example='probing']").click()
        probing = page.locator("#batch-text").input_value()
        assert not requests
        send_and_finish(30)
        expect(page.locator("#batch-summary h3")).to_have_text(
            "Flagged activity observed"
        )
        expect(page.locator("#batch-summary")).to_contain_text("New alert evidence:")
        data = snapshot()
        assert data["totals"]["requests"] == 30 and data["totals"]["denied"] > 0
        assert data["alerts"] and all(
            a["client_id"] == "probe-01" for a in data["alerts"]
        )
        assert [r["text"] for r in requests] == probing.splitlines()
        row = page.locator("#batch-rows tr").filter(has_text="HTTP 429").first
        row.locator("summary").click()
        expect(row.locator("pre")).to_contain_text('"retry_after"')
        assert '"label"' not in row.locator("pre").inner_text()
        page.locator("#batch-results").screenshot(
            path=str(reports / "batch-results.png")
        )
        checks.append(
            "30 probing inputs produce real 429 responses and explained alerts"
        )

        # Earlier activity must be visible, not presented as a clean new test.
        page.locator("#batch-text").fill("The movie was excellent.")
        send_and_finish(1)
        expect(page.locator("#batch-summary")).to_contain_text("already flagged")
        expect(page.locator("#batch-summary h3")).to_have_text(
            "Flagged activity observed"
        )
        checks.append("existing risk and penalties are identified before a new batch")

        page.locator("[data-input-mode='single']").click()
        page.locator("#predict-key").select_option("normal-01")
        page.locator("#predict-form button[type='submit']").click()
        expect(page.locator("#predict-result")).to_contain_text("HTTP 200")
        page.locator("[data-input-mode='batch']").click()
        checks.append(
            "another key can still receive predictions after batch enforcement"
        )

        reset()
        page.locator("a.nav-item[data-page='policy']").click()
        page.locator("#enforce-toggle").uncheck()
        expect(page.locator("#mode-label")).to_have_text("Observing")
        page.locator("a.nav-item[data-page='lab']").click()
        page.locator("#batch-text").fill(probing)
        send_and_finish(30)
        expect(page.locator("#batch-summary h3")).to_have_text(
            "Flagged activity observed"
        )
        expect(page.locator("#batch-summary")).to_contain_text("Observe mode is on")
        data = snapshot()
        assert data["totals"]["requests"] == 30 and data["totals"]["denied"] == 0
        assert data["alerts"] and all(a["action"] == "observed" for a in data["alerts"])
        checks.append(
            "observe mode raises alerts while all 30 responses remain HTTP 200"
        )

        reset()
        page.locator("a.nav-item[data-page='policy']").click()
        page.locator("#enforce-toggle").check()
        expect(page.locator("#mode-label")).to_have_text("Enforcing")
        page.locator("a.nav-item[data-page='lab']").click()
        page.locator("#batch-text").fill(ordinary)
        page.locator("#batch-delay").select_option("1000")
        page.locator("#batch-send").click()
        expect(page.locator("#batch-rows tr").first).to_contain_text("HTTP 200")
        for selector in (
            "#batch-send",
            "#reset-button",
            "#enforce-toggle",
            "#demo-button",
        ):
            expect(page.locator(selector)).to_be_disabled()
        page.locator("#batch-stop").click()
        expect(page.locator("#batch-progress")).to_contain_text("Batch stopped")
        count = len(requests)
        assert 1 <= count < 15
        page.wait_for_timeout(1200)
        assert len(requests) == count == snapshot()["totals"]["requests"]
        checks.append("stop preserves completed responses and stops remaining requests")
        checks.append(
            "duplicate submission, reset, mode and simulation controls lock during a batch"
        )

        reset()
        page.locator("#batch-delay").select_option("100")
        page.locator("#batch-text").fill(ordinary)
        page.route("**/predict", lambda route: route.abort())
        page.locator("#batch-send").click()
        expect(page.locator("#batch-progress")).to_contain_text("Batch interrupted")
        expect(page.locator("#batch-summary h3")).to_have_text("Result incomplete")
        expect(page.locator("#batch-summary")).to_contain_text("Nothing was retried")
        assert len(requests) == 1 and snapshot()["totals"]["requests"] == 0
        page.unroute("**/predict")
        checks.append("network failure produces an incomplete result without retrying")

        reset()

        # Allow preflight telemetry, then fail the snapshot after the real response.
        def fail_after_prediction(route):
            if requests:
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"Telemetry unavailable"}',
                )
            else:
                route.continue_()

        page.route("**/api/snapshot", fail_after_prediction)
        page.locator("#batch-send").click()
        expect(page.locator("#batch-progress")).to_contain_text("Batch interrupted")
        expect(page.locator("#batch-summary h3")).to_have_text("Result incomplete")
        expect(page.locator("#batch-rows tr")).to_contain_text("HTTP 200")
        expect(page.locator("#batch-rows tr")).to_contain_text("Unavailable")
        assert len(requests) == 1 and snapshot()["totals"]["requests"] == 1
        page.unroute("**/api/snapshot")
        checks.append(
            "missing telemetry preserves the response without inventing a risk score"
        )

        reset()
        literal = '<img src=x onerror="window.batchInjection=true">'
        page.locator("#batch-text").fill(literal)
        send_and_finish(1)
        expect(page.locator(".batch-input")).to_have_text(literal)
        assert not page.evaluate("Boolean(window.batchInjection)")
        checks.append("pasted HTML is displayed as text")

        reset()
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#batch-text").fill("\n".join(ordinary.splitlines()[:10]))
        send_and_finish(10)
        expect(page.locator("#batch-summary h3")).to_have_text("No flag observed")
        assert len(requests) == snapshot()["totals"]["requests"] == 10
        checks.append("10 manually pasted inputs complete on mobile")
        page.locator("#batch-text").scroll_into_view_if_needed()
        page.locator("#batch-text").focus()
        expect(page.locator("#batch-text")).to_be_in_viewport()
        expect(page.locator("#toast")).to_be_hidden(timeout=7000)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(reports / "batch-mobile.png"), full_page=True)
        checks.append("390px mobile batch layout has no page overflow")
        assert not errors, errors
        browser.close()
    result = {"status": "passed", "javascript_errors": errors, "checks": checks}
    (reports / "batch-check.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--channel", default="msedge", choices=["msedge", "chrome", "chromium"]
    )
    args = parser.parse_args()
    run(args.url, args.channel)
