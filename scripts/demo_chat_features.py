"""Visible, bounded feature tour on the running local demo. Keeps existing audit data."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from modelshield.config import ROOT
from modelshield.chat_scenarios import QUESTIONS, scenario_questions


FEATURES = [
    ("conversation", "Real local conversation", "A customer talks to the local model without operator access."),
    ("context", "Conversation memory", "A follow-up uses the previous messages in the same conversation."),
    ("validation", "Input checks and operator separation", "Oversized batches stop in the browser; a chat customer cannot read operator evidence."),
    ("short_wait", "One-second speed bump", "A short suspicious burst is paced by the server before generation."),
    ("long_wait", "Three-second speed bump", "A more repetitive burst receives stronger pacing. Actual waiting is measured."),
    ("approved", "Thirty approved questions", "An operator approves a bounded workload; a manual batch uses the same saved pass."),
    ("concurrency", "Live queue and concurrency cap", "The approved workload queues while at most two requests generate answers at once."),
    ("exhaustion", "Allowance exhausted", "The thirty-first request using the same pass is withheld."),
    ("unapproved", "Ordinary limits without a pass", "Turning off pass use returns a rapid varied batch to normal detector rules."),
    ("revocation", "Revoke queued answers", "An operator revokes a pass while its manual batch is still processing."),
    ("expiry", "Automatic pass expiry", "A one-minute pass expires naturally during a queued batch; it is not backdated."),
    ("probing", "Repeated probing despite approval", "A pass does not disable repetition checks; a probing batch can be blocked."),
    ("new_chat", "New conversation keeps restrictions", "Starting a new conversation does not erase the API key's current penalty."),
    ("isolation", "Other clients keep working", "Another key receives a normal answer while the probing client is blocked."),
    ("recovery", "Cooldown and retained incident evidence", "Access recovers after the real cooldown; saved incident evidence remains."),
    ("stop", "Stop a traffic test", "An operator cancels a running local test; submitted requests stay in the audit."),
    ("persistence", "Saved usage survives restart", "A completed request consumes a pass slot before a controlled server restart."),
    ("evidence", "Inspect, filter and export evidence", "The dashboard shows actual questions, responses and signal evidence without opening code."),
]


def arrange(page, left, width, height):
    session = page.context.new_cdp_session(page)
    window = session.send("Browser.getWindowForTarget")
    session.send("Browser.setWindowBounds", {
        "windowId": window["windowId"],
        "bounds": {"windowState": "normal", "left": left, "top": 0, "width": width, "height": height},
    })
    session.detach()


def main(base, restart_check=True, keep_open=True, resume=False):
    if urlparse(base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("This demonstration only targets the local service.")
    report_path = ROOT / "reports/chat-feature-demo.json"
    report = {"id": "tour-" + uuid4().hex, "status": "running", "started_at": time.time(),
              "target": base, "current": "Preparing the visible chatbot demonstration.",
              "scope": "Real local chatbot and dashboard interactions. Saved examples, not a detection-accuracy or cloning-success benchmark.",
              "history_reset": False, "features": [dict(id=key, title=title, explanation=text, status="waiting") for key, title, text in FEATURES]}
    if resume:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["target"] != base or any(row["status"] != "passed" for row in report["features"][:16]):
            raise RuntimeError("Resume requires the first sixteen demonstrations to be complete on this server.")
        report.update(status="running", current="Resuming the restart and export checks.")
    current = None
    browsers = None
    errors = []

    def save():
        report["updated_at"] = time.time()
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(report_path)

    save()
    with httpx.Client(base_url=base, trust_env=False, timeout=20) as api, sync_playwright() as playwright:
        def snapshot():
            response = api.get("/api/chat/snapshot")
            if response.status_code == 401:
                api.get("/dashboard").raise_for_status()
                response = api.get("/api/chat/snapshot")
            response.raise_for_status()
            return response.json()

        before = snapshot()
        if not before["demo_mode"]:
            raise RuntimeError("The visible tour is restricted to local demo mode.")
        if before["totals"]["pending"]:
            raise RuntimeError("Wait for current chat requests to finish before this tour.")
        report["server_started_at"] = before["started_at"]
        report["policy"] = before["policy"]
        browsers = playwright.chromium.launch(channel="msedge", headless=False)
        customer = browsers.new_context(no_viewport=True)
        operator = browsers.new_context(no_viewport=True)
        dashboard = operator.new_page()
        dashboard.on("pageerror", lambda error: errors.append(str(error)))
        dashboard.goto(base + "/dashboard#feature-demo")
        expect(dashboard.locator("#connection")).to_contain_text("Monitor connected")
        screen = dashboard.evaluate("({width:screen.availWidth,height:screen.availHeight})")
        width = max(480, screen["width"] // 2)
        arrange(dashboard, width, width, screen["height"])
        pages, all_conversations = [], set()
        phase_at = time.time()

        def phase(key):
            nonlocal current, phase_at
            current = next(row for row in report["features"] if row["id"] == key)
            phase_at = time.time()
            current.update(status="running", started_at=phase_at)
            report["current"] = current["title"] + ": " + current["explanation"]
            save()
            print("DEMO: " + current["title"], flush=True)
            dashboard.evaluate("location.hash = 'feature-demo'")

        def all_events():
            result = api.get("/api/chat/export")
            result.raise_for_status()
            return result.json()["events"]

        if resume:
            saved_ids = {request_id for feature in report["features"] for request_id in feature.get("request_ids", [])}
            all_conversations.update(row["conversation_id"] for row in all_events() if row["id"] in saved_ids)

        def records(page, since=None):
            cutoff = phase_at if since is None else since
            return sorted([row for row in all_events() if row["conversation_id"] in page.demo_conversations and row["at"] >= cutoff], key=lambda row: row["at"])

        def finish(result, events=(), observations=()):
            current.update(status="passed", result=result, finished_at=time.time(),
                           observations=list(observations), request_ids=[r["id"] for r in events])
            samples = []
            choices = [next((r for r in events if r["status"] == status), None) for status in ("answered", "withheld", "error")]
            if events:
                choices += [max(events, key=lambda row: row.get("speed_bump", {}).get("wait_ms", 0)), events[-1]]
            for row in choices:
                if row and row["id"] not in {item["id"] for item in samples}:
                    samples.append(row)
            current["samples"] = samples
            save()
            print("VERIFIED: " + result, flush=True)
            if pages:
                pages[-1].screenshot(path=str(ROOT / "reports" / f"feature-{current['id']}-chat.png"), full_page=False)
            dashboard.screenshot(path=str(ROOT / "reports" / f"feature-{current['id']}-dashboard.png"), full_page=False)

        def chat_page(key, title):
            page = customer.new_page()
            page.demo_conversations = set()
            page.demo_statuses = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            def capture(request):
                if request.url.endswith("/chat/messages") and request.method == "POST":
                    cid = request.post_data_json["conversation_id"]
                    page.demo_conversations.add(cid)
                    all_conversations.add(cid)
            page.on("request", capture)
            page.on("response", lambda response: page.demo_statuses.append(response.status) if response.url.endswith("/chat/messages") else None)
            page.goto(base + "/chat")
            expect(page.locator("#client-key")).to_have_value("normal-01")
            if key in {"normal-01", "normal-02", "probe-01", "batch-01", "attacker-01"}:
                page.locator("#demo-key").select_option(key)
            else:
                page.locator("#connection-settings summary").click()
                page.locator("#client-key").fill(key)
                page.locator("#client-key").dispatch_event("change")
            page.evaluate("title => { document.title = title + ' · ModelShield demo'; }", title)
            arrange(page, 0, width, screen["height"])
            page.bring_to_front()
            pages.append(page)
            return page

        def single(page, question, text=None):
            page.locator("#single-tab").click()
            page.locator("#message").fill(question)
            page.locator("#send").click()
            expect(page.locator("#send")).to_be_enabled(timeout=190000)
            if text:
                expect(page.locator(".assistant").last).to_contain_text(text)

        def batch(page, questions, *, use_pass=True, wait=True):
            page.locator("#batch-tab").click()
            if not page.locator("#batch-options").evaluate("element => element.open"):
                page.locator("#batch-options summary").click()
            page.locator("#use-bulk-pass").set_checked(use_pass)
            page.locator("#batch-questions").fill("\n".join(questions))
            expect(page.locator("#batch-count")).to_have_text(f"{len(questions)} / 30 questions")
            page.locator("#send-batch").click()
            if wait:
                expect(page.locator("#chat-feedback")).to_contain_text(f"{len(questions)} / {len(questions)} complete", timeout=190000)
                expect(page.locator("#send-batch")).to_be_enabled(timeout=10000)

        def approve(key, limit=30, minutes=10, concurrency=2):
            state = snapshot()
            existing = next((r for r in state["bulk_passes"] if r["client_id"] == key and r["status"] in {"active", "exhausted"}), None)
            if existing:
                if not existing["purpose"].startswith("Guided demo"):
                    raise RuntimeError(f"{key} has a separately approved pass; it was not modified.")
                api.post(f"/api/chat/passes/{existing['id']}/revoke").raise_for_status()
            dashboard.evaluate("location.hash = 'protection'")
            dashboard.locator("#bulk-client").select_option(key)
            dashboard.locator("#bulk-limit").fill(str(limit))
            dashboard.locator("#bulk-minutes").fill(str(minutes))
            if not dashboard.locator("#bulk-options").evaluate("element => element.open"):
                dashboard.locator("#bulk-options summary").click()
            dashboard.locator("#bulk-concurrency").select_option(str(concurrency))
            dashboard.locator("#bulk-purpose").fill(f"Guided demo: {limit} varied questions for {key}")
            dashboard.locator("#issue-bulk-pass").click()
            expect(dashboard.locator("#protection-feedback")).to_contain_text(f"Approved {limit} requests for {key}")
            return next(row for row in snapshot()["bulk_passes"] if row["client_id"] == key and row["status"] == "active")

        def wait_until(predicate, timeout=65):
            deadline = time.monotonic() + timeout
            while not predicate():
                if time.monotonic() >= deadline:
                    raise RuntimeError("The expected live state did not appear before the demo deadline.")
                dashboard.wait_for_timeout(250)

        try:
            if not resume:
                phase("conversation")
                normal = chat_page("normal-01", "01 · Normal conversation")
                single(normal, "My name is Maya. Please greet me in one short sentence.", "Maya")
                actual = records(normal)
                assert actual[-1]["status"] == "answered"
                finish("The local model greeted Maya; the question and released answer are in the dashboard.", actual)

                phase("context")
                single(normal, "What is my name? Answer with just my name.", "Maya")
                finish("The follow-up answered Maya using the same conversation history.", records(normal))

                phase("validation")
                count_before = snapshot()["totals"]["requests"]
                normal.locator("#batch-tab").click()
                normal.locator("#batch-questions").fill("\n".join(["Hello"] * 31))
                normal.locator("#send-batch").click()
                expect(normal.locator("#chat-feedback")).to_contain_text("1–30 questions")
                assert snapshot()["totals"]["requests"] == count_before
                assert customer.request.get(base + "/api/chat/snapshot").status == 401
                assert not any(cookie["name"] == "modelshield_admin" for cookie in customer.cookies())
                finish("31 questions were rejected in the browser before any model request; operator data returned HTTP 401 to the chat-only browser.", observations=["These checks intentionally create no inference row. The two successful conversation requests prove the customer can chat without an operator cookie."])

                phase("short_wait")
                short = chat_page("probe-01", "02 · One-second pacing")
                questions = scenario_questions("speed_bump")
                questions[-2:] = ["Why is the sky blue?", "What makes bread rise?"]
                batch(short, questions, use_pass=False)
                actual = records(short)
                assert len(actual) == 8 and all(row["status"] == "answered" for row in actual)
                delayed = [row for row in actual if row["speed_bump"]["seconds"] == 1 and row["speed_bump"]["wait_ms"] > 0]
                assert delayed, "One-second pacing was not observed"
                finish(f"Eight answers released; {len(delayed)} requests recorded the one-second pacing level.", actual)

                phase("long_wait")
                longer = chat_page("swarm-01", "03 · Three-second pacing")
                batch(longer, scenario_questions("speed_bump"), use_pass=False)
                actual = records(longer)
                assert all(row["status"] == "answered" for row in actual)
                assert any(row["speed_bump"]["seconds"] == 3 and row["speed_bump"]["wait_ms"] > 0 for row in actual)
                finish("The stronger burst recorded three-second pacing while still receiving eight answers.", actual)

                phase("approved")
                approved = approve("batch-01")
                bulk = chat_page("batch-01", "04 · Approved thirty-question batch")
                expect(bulk.locator("#bulk-access-status")).to_contain_text("0 / 30 used")
                bulk.locator("#batch-tab").click()
                bulk.locator("#varied-batch").click()
                expect(bulk.locator("#batch-count")).to_have_text("30 / 30 questions")
                batch(bulk, QUESTIONS, wait=False)
                max_generating = 0
                queue_seen = False
                while bulk.locator("#send-batch").is_disabled():
                    state = snapshot()
                    queue = [r for r in state["queue"] if r["client_id"] == "batch-01"]
                    max_generating = max(max_generating, sum(r["stage"] == "generating" for r in queue))
                    queue_seen |= len(queue) > 2
                    dashboard.wait_for_timeout(300)
                actual = records(bulk)
                assert len(actual) == 30 and all(row["status"] == "answered" for row in actual)
                finish("All 30 approved questions received real answers; the pass reached 30 / 30 used.", actual)
                phase("concurrency")
                assert queue_seen and 1 <= max_generating <= 2
                finish(f"Observed a live backlog and a maximum of {max_generating} simultaneous generations for the two-slot pass.", observations=["This is the observed live run; automated concurrency tests separately check enforcement under racing requests."])

                phase("exhaustion")
                batch(bulk, ["What is an API?"])
                actual = records(bulk)
                assert len(actual) == 1 and actual[0]["action"] == "bulk_limit"
                assert "exhausted" in actual[0]["error"]
                finish("The next manual batch request was withheld because all 30 slots were used.", actual)

                phase("unapproved")
                batch(bulk, QUESTIONS, use_pass=False)
                actual = records(bulk)
                assert any(row["action"] == "throttle" for row in actual)
                finish(f"Without pass use, the varied burst triggered ordinary throttling: {sum(r['status']=='withheld' for r in actual)} of 30 answers withheld.", actual)

                # Start a real one-minute clock while demonstrating another feature.
                expiring = approve("swarm-02", limit=30, minutes=1, concurrency=1)
                expiry_page = chat_page("swarm-02", "06 · Expiring pass")
                phase("revocation")
                revoked = approve("normal-02", limit=15, concurrency=1)
                revoke_page = chat_page("normal-02", "05 · Operator revocation")
                batch(revoke_page, QUESTIONS[:15], wait=False)
                wait_until(lambda: sum(r["client_id"] == "normal-02" for r in snapshot()["queue"]) >= 3, 15)
                row = dashboard.locator("#bulk-pass-list tr").filter(has_text=revoked["id"])
                row.get_by_role("button", name="Revoke", exact=True).click()
                expect(row).to_contain_text("revoked")
                expect(revoke_page.locator("#chat-feedback")).to_contain_text("15 / 15 complete", timeout=190000)
                actual = records(revoke_page)
                assert any(r["action"] == "bulk_limit" and "revoked" in r.get("error", "") for r in actual)
                finish(f"Revoking the pass withheld {sum(r['status']=='withheld' for r in actual)} of 15 submitted answers; already released answers remain in the audit.", actual)

                phase("expiry")
                expiry_page.bring_to_front()
                while time.time() < expiring["expires_at"] - 3:
                    report["current"] = f"Waiting for the real one-minute pass clock: {max(0, round(expiring['expires_at'] - time.time()))} seconds remain. No timestamps are being changed."
                    save()
                    dashboard.wait_for_timeout(1000)
                batch(expiry_page, QUESTIONS, wait=False)
                expect(expiry_page.locator("#chat-feedback")).to_contain_text("30 / 30 complete", timeout=190000)
                actual = records(expiry_page)
                assert any(r["action"] == "bulk_limit" and "expired" in r.get("error", "") for r in actual)
                finish(f"The pass expired naturally; {sum(r['status']=='withheld' for r in actual)} queued answers were withheld after expiry.", actual, ["The pass had a one-minute lifetime and a one-generation concurrency cap."])

                phase("probing")
                approve("attacker-01")
                attacker = chat_page("attacker-01", "07 · Repeated probes blocked")
                attacker.locator("#batch-tab").click()
                attacker.locator("#example-batch").click()
                batch(attacker, scenario_questions("probing"))
                actual = records(attacker)
                state = snapshot()
                attack_state = next(c for c in state["clients"] if c["id"] == "attacker-01")
                assert attack_state["status"] == "block"
                incident_ids = {a["incident_id"] for a in state["alerts"] if a["client_id"] == "attacker-01"}
                assert any("removes the bulk" in " ".join(a["reasons"]) for a in state["alerts"] if a["client_id"] == "attacker-01")
                finish(f"Repeated probing removed the rate credit and blocked the key; {sum(r['status']=='withheld' for r in actual)} of 30 answers were withheld.", actual)

                phase("new_chat")
                retry = chat_page("attacker-01", "08 · New chat cannot bypass a block")
                retry.locator("#new-chat").click()
                single(retry, "Hello again", "Request paused")
                actual = records(retry)
                assert actual[-1]["action"] == "block"
                finish("A fresh conversation under the same key still received the active block.", actual)

                phase("isolation")
                control = chat_page("normal-01", "09 · Another customer still works")
                single(control, "What is two plus two? Answer with only the number.", "4")
                actual = records(control)
                assert actual[-1]["status"] == "answered"
                assert next(c for c in snapshot()["clients"] if c["id"] == "attacker-01")["status"] == "block"
                finish("A different customer received 4 while the probing key was still blocked.", actual)

                phase("recovery")
                wait_until(lambda: next(c for c in snapshot()["clients"] if c["id"] == "attacker-01")["retry_after"] == 0, 40)
                recovered = chat_page("attacker-01", "10 · Recovered after cooldown")
                single(recovered, "What is two plus two? Give only the number.", "4")
                actual = records(recovered)
                assert actual[-1]["status"] == "answered"
                assert incident_ids <= {a["incident_id"] for a in snapshot()["alerts"]}
                finish("The real cooldown ended, a new answer was released, and the original incident records remained.", actual)

                phase("stop")
                dashboard.evaluate("location.hash = 'protection'")
                api.post("/api/chat/tests/start", json={"client_id": "swarm-03", "scenario": "speed_bump"}).raise_for_status()
                wait_until(lambda: snapshot()["totals"]["pending"] > 0, 10)
                api.post("/api/chat/tests/stop").raise_for_status()
                wait_until(lambda: not snapshot()["test_run"]["running"], 15)
                state = snapshot()
                assert state["totals"]["pending"] == 0
                demo_id = state["test_run"]["id"]
                all_conversations.add(demo_id)
                stopped = [r for r in all_events() if r["conversation_id"] == demo_id]
                finish("The API traffic test was cancelled; its submitted requests remain recorded, with interruptions shown as errors.", stopped,
                       ["This test was started and stopped through the operator API. Cancellation errors are expected demo outcomes."])

            phase("persistence")
            durable = approve("normal-01", limit=3)
            durable_page = chat_page("normal-01", "11 · Persistent pass usage")
            batch(durable_page, [QUESTIONS[0]])
            saved = next(p for p in snapshot()["bulk_passes"] if p["id"] == durable["id"])
            actual = records(durable_page)
            assert saved["used"] == 1
            if restart_check:
                report["current"] = "Ready for the controlled server restart. All requests have finished; checking that one used pass slot and saved transcripts survive."
                report["restart_requested"] = True
                save()
                print("RESTART_READY: Restart python enthi.py in the server terminal; this tour will resume automatically.", flush=True)
                previous_start = snapshot()["started_at"]
                deadline = time.monotonic() + 900
                while time.monotonic() < deadline:
                    try:
                        state = snapshot()
                        if state["started_at"] != previous_start:
                            break
                    except httpx.HTTPError:
                        pass
                    dashboard.wait_for_timeout(500)
                else:
                    raise RuntimeError("No server restart occurred within the demonstration window.")
                dashboard.reload()
                expect(dashboard.locator("#connection")).to_contain_text("Monitor connected")
                after_pass = next(p for p in state["bulk_passes"] if p["id"] == durable["id"])
                assert after_pass["used"] == saved["used"] and after_pass["expires_at"] == saved["expires_at"]
                assert all(r["id"] in {item["id"] for item in all_events()} for r in actual)
                expect(durable_page.locator("#bulk-access-status")).to_contain_text("1 / 3 used", timeout=10000)
                report["server_restarted_at"] = state["started_at"]
                finish("After an actual server restart, the pass still showed 1 / 3 used and the previous question and answer remained saved.", actual,
                       ["Live risk windows, counters and alert cards reset on restart in this prototype. Saved request evidence and pass records survive."])
            else:
                current.update(status="not run", result="Restart demonstration was explicitly skipped; usage is saved but restart was not demonstrated here.")
                save()

            phase("evidence")
            dashboard.evaluate("location.hash = 'live'")
            dashboard.locator("#event-filter").select_option("withheld")
            expect(dashboard.locator("#events .event-row")).not_to_have_count(0)
            dashboard.locator("#events .event-row").first.click()
            expect(dashboard.locator("#detail-body")).to_contain_text("Signals at arrival")
            dashboard.locator("#close-detail").click()
            dashboard.locator("#event-filter").select_option("all")
            with dashboard.expect_download() as download:
                dashboard.locator("#export").click()
            export = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
            tour_events = [r for r in export["events"] if r["conversation_id"] in all_conversations]
            (ROOT / "reports/chat-feature-demo-transcripts.json").write_text(json.dumps({"tour_id": report["id"], "events": tour_events}, indent=2), encoding="utf-8")
            assert not errors, errors
            finish(f"Inspected withheld requests and signals, showed all five requirement cards, and exported {len(tour_events)} requests from this tour.",
                   observations=["The saved transcript artifact includes only this demonstration's conversations, not earlier customer history.", "No browser JavaScript errors occurred during the tour."])
            # Leave a fresh, real probing conversation and a matching live alert
            # visible after the restart, while retaining the earlier approved case.
            attacker = chat_page("attacker-01", "12 · Live probing demonstration")
            batch(attacker, scenario_questions("probing"), use_pass=False)
            final_probe = records(attacker)
            assert any(row["action"] == "block" for row in final_probe)
            report["final_live_probe"] = {"captured_at": time.time(), "requests": len(final_probe),
                                           "withheld": sum(row["status"] == "withheld" for row in final_probe)}
            tour_events = [row for row in all_events() if row["conversation_id"] in all_conversations]
            (ROOT / "reports/chat-feature-demo-transcripts.json").write_text(json.dumps({"tour_id": report["id"], "events": tour_events}, indent=2), encoding="utf-8")
            report.update(status="complete", current="Demonstration complete. Expand a feature below and select a request to inspect its original question, result and signals.",
                          totals=dict(Counter(r["status"] for r in tour_events)), browser_errors=errors)
            save()
            dashboard.evaluate("location.hash = 'feature-demo'")
            expect(dashboard.locator("#feature-demo-status")).to_contain_text("complete", timeout=10000)
            proof = dashboard.locator('[data-feature="probing"]')
            proof.locator("summary").click()
            expect(proof.locator(".feature-proof button").first).to_be_visible()
            proof.locator(".feature-proof button").first.click()
            expect(dashboard.locator("#detail-body")).to_contain_text("Signals at arrival")
            dashboard.screenshot(path=str(ROOT / "reports/chat-feature-demo-final.png"), full_page=False)
            attacker.bring_to_front()
            dashboard.bring_to_front()
            print("DEMO_COMPLETE " + json.dumps({"features": len(FEATURES), "passed": sum(r['status']=='passed' for r in report['features']), "totals": report["totals"]}), flush=True)
            if keep_open:
                print("Browser windows and example chat tabs remain open for inspection.", flush=True)
                while browsers.is_connected() and not dashboard.is_closed():
                    try:
                        dashboard.wait_for_timeout(1000)
                    except Exception:
                        break
        except Exception as error:
            report.update(status="incomplete", current="Demonstration stopped: " + str(error))
            if current:
                current.update(status="failed", result=str(error))
            save()
            if browsers.is_connected():
                dashboard.screenshot(path=str(ROOT / "reports/chat-feature-demo-interrupted.png"), full_page=False)
            raise
        finally:
            if browsers.is_connected():
                browsers.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--skip-restart", action="store_true")
    parser.add_argument("--close-when-done", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Resume a tour after the first sixteen features passed")
    options = parser.parse_args()
    main(options.base_url, restart_check=not options.skip_restart, keep_open=not options.close_when_done, resume=options.resume)
