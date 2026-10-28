"""Exercise dashboard approvals and speed bumps through the real local chat model."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from playwright.sync_api import expect, sync_playwright

from modelshield.config import ROOT
from scripts.experiment_support import local_server


def main():
    checks, errors, runs = [], [], []
    with TemporaryDirectory(prefix="modelshield-protection-") as temp, local_server(temp) as (url, _):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            operator = browser.new_context(viewport={"width": 1440, "height": 1100})
            customer = browser.new_context(viewport={"width": 1440, "height": 1000})
            dashboard, chat = operator.new_page(), customer.new_page()
            for page in (dashboard, chat):
                page.on("pageerror", lambda error: errors.append(str(error)))
            dashboard.goto(url + "/dashboard#protection")
            expect(dashboard.locator("#connection")).to_contain_text("Monitor connected")
            expect(dashboard.locator(".protection-stage")).to_have_count(5)
            expect(dashboard.locator("#protection")).to_be_in_viewport()
            assert operator.request.get(url + "/api/chat/snapshot").json()["totals"]["requests"] == 0
            checks.append("Protection view explains five response levels without generating traffic")
            chat.goto(url + "/chat")
            expect(chat.locator("#client-key")).to_have_value("normal-01")
            assert customer.request.get(url + "/api/chat/snapshot").status == 401
            assert customer.request.post(url + "/api/chat/passes", data={"client_id": "batch-01", "purpose": "Not allowed"}).status == 401
            checks.append("Chat customer cannot issue passes or inspect operator records")
            chat.locator("#message").fill("What is two plus two? Give only the number.")
            chat.locator("#send").click()
            expect(chat.locator(".assistant").last).to_contain_text("4", timeout=120000)
            checks.append("Real local model answers a normal conversation")
            print("Normal conversation verified", flush=True)

            def start(scenario, client):
                response = operator.request.post(url + "/api/chat/tests/start", data={"client_id": client, "scenario": scenario})
                assert response.ok, response.text()

            def finish():
                deadline = time.monotonic() + 220
                while operator.request.get(url + "/api/chat/snapshot").json()["test_run"]["running"]:
                    assert time.monotonic() < deadline, "Traffic test did not finish"
                    dashboard.wait_for_timeout(500)
                snapshot = operator.request.get(url + "/api/chat/snapshot").json()
                run = snapshot["test_run"]
                assert run["completed"] == run["total"], run
                assert not run.get("error"), run
                runs.append(run)
                return snapshot

            start("speed_bump", "probe-01")
            expect(dashboard.locator("#speed-delayed")).not_to_have_text("0", timeout=30000)
            snapshot = finish()
            assert snapshot["test_run"]["responses"] == {"200": 8}, snapshot["test_run"]
            delayed = [r for r in snapshot["events"] if r["client_id"] == "probe-01" and r["speed_bump"]["wait_ms"] > 0]
            assert delayed and max(r["speed_bump"]["wait_ms"] for r in delayed) >= 900
            expect(dashboard.locator("#speed-time")).not_to_have_text("0.0 s")
            checks.append("Eight real probes show measured server-side waiting and still receive answers")
            print("Speed bump verified", flush=True)
            dashboard.locator("#protection").scroll_into_view_if_needed()
            dashboard.screenshot(path=str(ROOT / "reports/protection-speed-bump.png"), full_page=True)

            dashboard.locator("#bulk-client").select_option("batch-01")
            dashboard.locator("#issue-bulk-pass").click()
            expect(dashboard.locator("#protection-feedback")).to_contain_text("Approved 30 requests")
            expect(dashboard.locator("#bulk-pass-list")).to_contain_text("0 / 30 used")
            checks.append("Operator issues a 30-request pass from the dashboard")
            start("bulk", "batch-01")
            snapshot = finish()
            assert snapshot["test_run"]["responses"] == {"200": 30}, snapshot["test_run"]
            approved = next(row for row in snapshot["bulk_passes"] if row["client_id"] == "batch-01")
            assert approved["status"] == "exhausted" and approved["used"] == 30
            assert not any(row["client_id"] == "batch-01" for row in snapshot["alerts"])
            expect(dashboard.locator("#bulk-pass-list")).to_contain_text("30 / 30 used")
            checks.append("Approved varied batch returns 30 real answers with no behavioral restriction")
            print("Approved 30-question batch verified", flush=True)
            chat.locator("#demo-key").select_option("batch-01")
            chat.locator("#batch-tab").click()
            chat.locator("#batch-options summary").click()
            expect(chat.locator("#bulk-access-status")).to_contain_text("30 / 30 used")
            chat.locator("#batch-questions").fill("What is an API?")
            chat.locator("#send-batch").click()
            expect(chat.locator(".assistant").last).to_contain_text("exhausted", timeout=15000)
            expect(chat.locator("#send-batch")).to_be_enabled()
            checks.append("Manual chatbot sees the same allowance and cannot exceed it")

            dashboard.locator("#bulk-client").select_option("attacker-01")
            dashboard.locator("#issue-bulk-pass").click()
            expect(dashboard.locator("#protection-feedback")).to_contain_text("Approved 30 requests for attacker-01")
            start("probing", "attacker-01")
            snapshot = finish()
            assert snapshot["test_run"]["responses"].get("429", 0) > 0
            assert any(row["client_id"] == "attacker-01" and "removes the bulk" in " ".join(row["reasons"]) for row in snapshot["alerts"])
            checks.append("Repeated probing removes approved rate credit and causes a visible restriction")
            print("Probing with an approved pass still restricted", flush=True)
            dashboard.screenshot(path=str(ROOT / "reports/protection-dashboard.png"), full_page=True)

            # A fresh, short pass exercises manual batch attachment and operator revocation.
            dashboard.locator("#bulk-client").select_option("normal-02")
            dashboard.locator("#bulk-limit").fill("3")
            dashboard.locator("#issue-bulk-pass").click()
            expect(dashboard.locator("#protection-feedback")).to_contain_text("Approved 3 requests")
            chat.locator("#demo-key").select_option("normal-02")
            expect(chat.locator("#bulk-access-status")).to_contain_text("0 / 3 used")
            chat.locator("#batch-questions").fill("Why is the sky blue?\nWhat makes bread rise?")
            chat.locator("#send-batch").click()
            expect(chat.locator("#chat-feedback")).to_contain_text("2 / 2 complete", timeout=120000)
            expect(chat.locator("#chat-feedback")).to_contain_text("2 answered")
            expect(chat.locator("#bulk-access-status")).to_contain_text("2 / 3 used")
            assert chat.locator(".assistant").filter(has_text="Approved bulk allowance used").count() == 2
            checks.append("Manual batch attaches the operator pass and displays its consumed allowance")
            chat.screenshot(path=str(ROOT / "reports/protection-chat.png"), full_page=True)
            row = dashboard.locator("#bulk-pass-list tr").filter(has_text="normal-02")
            row.get_by_role("button", name="Revoke", exact=True).click()
            expect(row).to_contain_text("revoked")
            expect(chat.locator("#bulk-access-status")).to_contain_text("No current bulk pass", timeout=10000)
            checks.append("Revocation is visible in the dashboard and separate customer page")

            with dashboard.expect_download() as download:
                dashboard.locator("#export").click()
            exported = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
            assert exported["bulk_passes"] and any(row.get("speed_bump", {}).get("wait_ms", 0) for row in exported["events"])
            checks.append("Evidence export includes approvals, usage and measured waiting")
            dashboard.reload()
            expect(dashboard.locator("#bulk-pass-list")).to_contain_text("30 / 30 used")
            for page in [dashboard, chat]:
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            dashboard.screenshot(path=str(ROOT / "reports/protection-mobile.png"), full_page=True)
            checks.append("Refresh preserves usage and both pages fit a mobile viewport")
            assert not errors, errors
            checks.append("No browser JavaScript errors")
            final = operator.request.get(url + "/api/chat/snapshot").json()
            report = {"saved_at": time.time(), "scope": "Real local-model/browser integration on temporary data. Fixed demo scenarios, not a detection-accuracy or copying-success benchmark.",
                      "passed": len(checks), "checks": checks, "browser_errors": errors,
                      "policy": final["policy"], "runs": runs, "totals": final["totals"], "bulk_passes": final["bulk_passes"]}
            (ROOT / "reports/protection-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2), flush=True)
            browser.close()


if __name__ == "__main__":
    main()
