"""Real local model + HTTP + two separate browser contexts; uses temporary audit data."""

import json
from tempfile import TemporaryDirectory
import time

from playwright.sync_api import expect, sync_playwright

from modelshield.config import ROOT
from scripts.experiment_support import local_server


def main():
    reports = ROOT / "reports"
    errors, checks = [], []
    with TemporaryDirectory(prefix="modelshield-chat-check-") as temp, local_server(
        temp
    ) as (url, auth):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            chat_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            operator_context = browser.new_context(
                viewport={"width": 1440, "height": 1100}
            )
            chat, monitor = chat_context.new_page(), operator_context.new_page()
            for page in (chat, monitor):
                page.on("pageerror", lambda error: errors.append(str(error)))
            chat.goto(url + "/chat")
            expect(chat.locator("#client-key")).to_have_value("normal-01")
            assert not any(
                cookie["name"] == "modelshield_admin"
                for cookie in chat_context.cookies()
            )
            assert chat_context.request.get(url + "/api/chat/snapshot").status == 401
            checks.append(
                "Chat works without operator credentials; monitoring is protected"
            )
            monitor.goto(url + "/dashboard")
            expect(monitor.locator("#connection")).to_contain_text("Monitor connected")
            assert (
                monitor.locator("#message, #batch-questions, #predict-text").count()
                == 0
            )
            checks.append("Monitoring page contains no chat or prediction input")
            chat.locator("#message").fill(
                "My name is Maya. Please greet me in one short sentence."
            )
            chat.locator("#send").click()
            expect(chat.locator(".assistant").last).to_contain_text(
                "Maya", timeout=120000
            )
            expect(chat.locator("#send")).to_be_enabled()
            expect(monitor.locator("#total-answered")).to_have_text("1")
            expect(monitor.locator("#total-flagged")).to_have_text("0")
            checks.append("Real model answers and normal client stays green")
            chat.locator("#message").fill("What is my name? Answer with just my name.")
            chat.locator("#send").click()
            expect(chat.locator(".assistant").last).to_contain_text(
                "Maya", timeout=120000
            )
            expect(chat.locator("#send")).to_be_enabled()
            checks.append("Real follow-up uses conversation history")
            chat.screenshot(path=str(reports / "chat.png"), full_page=True)
            chat.locator("#demo-key").select_option("probe-01")
            chat.locator("#batch-tab").click()
            chat.locator("#example-batch").click()
            expect(chat.locator("#batch-count")).to_have_text("30 / 30 questions")
            started = time.perf_counter()
            chat.locator("#send-batch").click()
            expect(monitor.locator(".alert-card")).not_to_have_count(0, timeout=15000)
            alert_seconds = round(time.perf_counter() - started, 3)
            expect(chat.locator("#chat-feedback")).to_contain_text(
                "30 / 30 complete", timeout=180000
            )
            expect(chat.locator("#chat-feedback")).to_contain_text("0 errors")
            expect(monitor.locator("#total-requests")).to_have_text("32")
            checks.append(
                "Thirty real HTTP requests raise a red flag and receive 429 restrictions"
            )
            monitor.locator(".alert-card").first.click()
            expect(monitor.locator("#detail-body")).to_contain_text(
                "Signals at arrival"
            )
            expect(monitor.locator("#detail-body")).to_contain_text("rate")
            before = monitor.locator("#detail-body").inner_text()
            monitor.wait_for_timeout(1700)
            assert monitor.locator("#detail-body").inner_text() == before
            checks.append("Incident evidence remains unchanged during live refresh")
            monitor.screenshot(path=str(reports / "chat-incident.png"), full_page=True)
            monitor.locator("#close-detail").click()
            monitor.screenshot(path=str(reports / "chat-monitor.png"), full_page=True)
            chat.locator("#new-chat").click()
            chat.locator("#single-tab").click()
            chat.locator("#message").fill("Hello again")
            chat.locator("#send").click()
            expect(chat.locator(".assistant").last).to_contain_text(
                "Request paused", timeout=10000
            )
            expect(chat.locator("#send")).to_be_enabled()
            checks.append("New conversation cannot clear a key restriction")
            chat.locator("#demo-key").select_option("normal-02")
            chat.locator("#message").fill("What is two plus two? Give only the number.")
            chat.locator("#send").click()
            expect(chat.locator(".assistant").last).to_contain_text("4", timeout=120000)
            expect(chat.locator("#send")).to_be_enabled()
            checks.append(
                "Another client still gets a real answer while the test client is blocked"
            )
            chat.locator("#batch-tab").click()
            chat.locator("#batch-questions").fill("\n".join(["Hello"] * 31))
            chat.locator("#send-batch").click()
            expect(chat.locator("#chat-feedback")).to_contain_text("1–30 questions")
            checks.append("Oversized manual batch is rejected before sending")
            with monitor.expect_download() as download:
                monitor.locator("#export").click()
            assert download.value.suggested_filename == "modelshield-chat-evidence.json"
            checks.append("Operator can export the chat evidence")
            for page, filename in [
                (chat, "chat-mobile.png"),
                (monitor, "chat-monitor-mobile.png"),
            ]:
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(reports / filename), full_page=True)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
            checks.append("Chat and monitoring layouts fit a mobile viewport")
            result = operator_context.request.get(url + "/api/chat/snapshot").json()
            assert not errors, errors
            checks.append("No browser JavaScript errors")
            report = {
                "checks": checks,
                "passed": len(checks),
                "browser_errors": errors,
                "model": result["model"],
                "alert_visible_seconds": alert_seconds,
                "totals": result["totals"],
                "scope": "End-to-end integration with the installed real local model. Not an extraction-success benchmark.",
            }
            (reports / "chat-check.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, indent=2), flush=True)
            browser.close()


if __name__ == "__main__":
    main()
