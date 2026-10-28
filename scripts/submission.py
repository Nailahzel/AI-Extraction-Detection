"""Generate the exact five-page competition submission from measured evidence."""

import argparse
import json
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from modelshield.config import ROOT

W, H = A4
M = 43
INK, MUTED, ACCENT = map(HexColor, ["#273334", "#65756e", "#28746a"])
BG, LINE, DARK = map(HexColor, ["#f5f5f0", "#dfe4df", "#253634"])


class Submission:
    def __init__(self, path, team, members):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.c.setTitle("ModelShield | GITEX Cyber Defense Submission")
        self.c.setAuthor(team)
        self.team, self.members, self.pages = team, members, 0

    def text(self, text, x, y, size=10, color=INK, bold=False):
        self.c.setFillColor(color)
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.drawString(x, y, text)

    def paragraph(
        self, text, y, width=W - 2 * M, x=M, size=10, color=MUTED, leading=None
    ):
        style = ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=size,
            leading=leading or size * 1.55,
            textColor=color,
            alignment=TA_LEFT,
        )
        p = Paragraph(text, style)
        _, height = p.wrap(width, H)
        p.drawOn(self.c, x, y - height)
        return y - height

    def box(self, x, y, w, h, fill=white, border=LINE, r=10):
        self.c.setFillColor(fill)
        self.c.setStrokeColor(border)
        self.c.setLineWidth(0.6)
        self.c.roundRect(x, y, w, h, r, fill=1, stroke=1)

    def begin(self, label, title, subtitle):
        self.pages += 1
        self.c.setFillColor(BG)
        self.c.rect(0, 0, W, H, fill=1, stroke=0)
        self.text("MODELSHIELD", M, H - 40, 9, ACCENT, True)
        self.text(label.upper(), W - 220, H - 40, 8, MUTED)
        self.text(title, M, H - 91, 27, INK, True)
        self.paragraph(subtitle, H - 112, size=10)

    def end(self):
        self.c.setStrokeColor(LINE)
        self.c.line(M, 44, W - M, 44)
        self.text(self.team + " / GITEX Cyber Defense", M, 29, 8, MUTED)
        self.text(f"{self.pages:02d} / 05", W - M - 35, 29, 8, MUTED)
        self.c.showPage()

    def metric(self, x, y, w, label, value, detail):
        self.box(x, y, w, 99)
        self.text(label, x + 15, y + 77, 8, MUTED)
        self.text(value, x + 15, y + 40, 28, ACCENT, True)
        self.text(detail, x + 15, y + 18, 7, MUTED)

    def save(self):
        assert self.pages == 5
        self.c.save()


def experiment_page(doc, copy, comparison):
    off = next(r for r in copy["runs"] if r["name"] == "unprotected")
    on = next(r for r in copy["runs"] if r["name"] == "protected")
    if on["agreement"] is None or off["agreement"] is None:
        copy_conclusion = "Copy agreement could not be compared: insufficient training data in at least one run."
    elif on["agreement"] < off["agreement"]:
        copy_conclusion = "Protection lowered copy agreement in this measured run. This is not proof of preventing copying."
    else:
        copy_conclusion = "Protection did not lower copy agreement in this measured run. Fewer answers alone do not establish a weaker copy."
    full = next(r for r in comparison["results"] if r["configuration"] == "full")
    rate = next(r for r in comparison["results"] if r["configuration"] == "rate_only")
    comparison_conclusion = (
        "The full detector exceeded the rate limiter's detection rate; compare false positives alongside that gain."
        if full["detection_rate"] > rate["detection_rate"]
        else "The full detector did not exceed the rate limiter's detection rate on this challenge set."
    )
    origin = (
        "Scenarios were authored here, not independently by a teammate."
        if comparison["dataset_origin"].startswith("New locally authored")
        else "Evaluator-supplied scenarios; independence depends on how they were collected."
    )
    doc.begin(
        "05 / Results and conclusions",
        "Classifier copying results",
        "Earlier sentiment experiments; these results do not measure chatbot protection.",
    )
    y = H - 164
    doc.text("COPYING THROUGH THE API", M, y, 10, ACCENT, True)
    y = (
        doc.paragraph(
            f"Same seed and candidate order; fresh detector state. Up to {copy['protocol']['attempt_budget']} attempts and {copy['protocol']['time_budget_seconds']} seconds per run. A second classifier learns released labels only. The evaluator compares labels on {copy['protocol']['test_count']} separate sentences. Agreement is imitation, not a percentage stolen.",
            y - 12,
            size=9,
        )
        - 18
    )
    for x, label in [
        (M, "MODE"),
        (M + 157, "ANSWERS / TRIES"),
        (M + 276, "AGREEMENT"),
        (M + 377, "CUSTOMERS"),
    ]:
        doc.text(label, x, y, 8, ACCENT, True)
    y -= 21
    for r in copy["runs"]:
        doc.text(r["name"].replace("_", " "), M, y, 9)
        doc.text(f"{r['released']} / {r['attempted']}", M + 171, y, 9)
        doc.text(
            (
                f"{r['agreement']:.1%}"
                if r["agreement"] is not None
                else "Insufficient data"
            ),
            M + 280,
            y,
            9,
        )
        doc.text(
            f"{r['legitimate']['allowed']} / {r['legitimate']['attempted']}",
            M + 401,
            y,
            9,
        )
        y -= 23
    y = (
        doc.paragraph(
            f"<b>Interpretation:</b> {copy_conclusion} A patient collector can wait for more answers. These short, synthetic experiments do not establish protection for other models or real customer traffic.",
            y - 2,
            size=9,
        )
        - 20
    )
    doc.text("CALIBRATED DEFENSE COMPARISON", M, y, 10, ACCENT, True)
    y = (
        doc.paragraph(
            "All enabled configurations meet the same 5% calibration false-positive target. Separate settings are frozen before challenge evaluation. The rate limiter has its own request capacity; both behavioral variants use equal two-second throttles. Production settings stay unchanged.",
            y - 12,
            size=9,
        )
        - 16
    )
    for r in comparison["results"]:
        doc.text(r["configuration"].replace("_", " "), M, y, 9)
        doc.text(
            f"{r['detected']}/{r['attack_sessions']} attacks detected",
            M + 156,
            y,
            9,
            MUTED,
        )
        doc.text(
            f"{r['false_positives']}/{r['benign_sessions']} benign flagged",
            M + 342,
            y,
            9,
            MUTED,
        )
        y -= 20
    y = (
        doc.paragraph(
            f"<b>{comparison_conclusion}</b> {origin} Settings were not retuned to improve these results. Inspect the per-scenario report for misses and false positives.",
            y - 3,
            size=9,
        )
        - 16
    )
    screenshot = ROOT / "reports" / "alert-evidence.png"
    if screenshot.exists():
        picture = ImageReader(str(screenshot))
        iw, ih = picture.getSize()
        height = min(125, y - 83, (W - 2 * M) * ih / iw)
        width = height * iw / ih
        doc.c.drawImage(
            picture,
            M + (W - 2 * M - width) / 2,
            y - height,
            width=width,
            height=height,
            mask="auto",
        )
        doc.text(
            "Live alert evidence is stored with its timestamp, signals, decision and policy.",
            M,
            y - height - 12,
            7,
            MUTED,
        )
    doc.end()


def build_chat_submission(team, members):
    evidence = json.loads(
        (ROOT / "reports/chat-check.json").read_text(encoding="utf-8")
    )
    measured = json.loads(
        (ROOT / "reports/chat-evaluation.json").read_text(encoding="utf-8")
    )
    output = ROOT / "reports/ModelShield-submission.pdf"
    doc = Submission(output, team, members)
    doc.begin(
        "01 / Title",
        "ModelShield",
        "A conversational AI service with separate, live extraction monitoring.",
    )
    doc.box(M, 352, W - 2 * M, 291, DARK, DARK, 13)
    doc.text("CHAT. OBSERVE.", M + 28, 589, 34, white, True)
    doc.text("RESTRICT THE BURST.", M + 28, 541, 29, HexColor("#a4dfbc"), True)
    doc.paragraph(
        "Ask real questions on the chatbot page. Watch the requests and red flags on the operator dashboard. The API can withhold answers from a suspicious key while other clients continue.",
        503,
        x=M + 28,
        width=W - 2 * M - 56,
        size=13,
        color=HexColor("#b0c2bd"),
        leading=21,
    )
    doc.text(team, M + 28, 390, 12, white, True)
    if members:
        doc.paragraph(
            escape(members), 374, x=M + 28, width=W - 2 * M - 56, size=8, color=white
        )
    doc.text("TWO PAGES, ONE PROTECTED SERVICE", M, 312, 10, ACCENT, True)
    doc.paragraph(
        "<b>Chat:</b> http://127.0.0.1:8765/chat<br/><b>Jury dashboard:</b> http://127.0.0.1:8765/dashboard<br/><b>Run:</b> python enthi.py<br/><b>First-time chat setup:</b> python -m scripts.setup_chat",
        292,
        size=11,
    )
    doc.paragraph(
        "Local Qwen2.5-0.5B-Instruct, FastAPI, llama.cpp, three request-side signals, per-key restrictions, and retained incident evidence. The classifier lab remains available for the earlier copying experiments.",
        183,
        size=10,
    )
    doc.end()

    doc.begin(
        "02 / Project objective",
        "Watch how access is used",
        "A valid API key can be used to collect answers for training an imitation.",
    )
    y = H - 170
    for title, body in [
        (
            "The problem",
            "Model extraction collects a model's outputs through repeated queries. An attacker does not necessarily need to compromise the server. This prototype looks for suspicious collection patterns while requests are arriving.",
        ),
        (
            "Who could deploy it",
            "An AI service operator could place these checks between authenticated customers and a model runtime. It adds request-level explanations and selective answer withholding to API access controls. Production use would require customer-specific validation and durable shared state.",
        ),
        (
            "The customer experience",
            "A separate chatbot provides short conversations and batches of up to 30 questions. It receives no operator risk scores. The dashboard shows requests, replies, restrictions, and red flags. Its Requirements &amp; evidence view maps all five deliverables to working features and scoped measurements.",
        ),
        (
            "The demonstration",
            "Send a few ordinary messages, then send a rapid batch of closely varied questions from a test client. Show the alert, its contributing signals, and HTTP 429 responses. A second client should still receive answers. Starting a new conversation does not clear the key's penalty.",
        ),
        (
            "The claim we can support",
            "The prototype detects and restricts the demonstrated querying patterns. It does not prove malicious intent or guarantee prevention of cloning. Legitimate bulk traffic can look identical, and slow extraction can evade the current rules.",
        ),
    ]:
        doc.text(title, M, y, 12, INK, True)
        y = doc.paragraph(body, y - 13, size=10) - 26
    doc.end()

    doc.begin(
        "03 / Proposed solution",
        "Check before answering",
        "Chat signals use arrival timing and input wording; no sentiment or invented LLM confidence.",
    )
    doc.box(M, 638, W - 2 * M, 42, DARK, DARK)
    doc.text(
        "KEY > VALIDATE > SCORE > GATE > LOCAL MODEL > RECHECK > ANSWER",
        M + 12,
        655,
        8,
        HexColor("#b8d6c8"),
        True,
    )
    y = 611
    for title, body in [
        (
            "Rate / up to 45 points",
            "Counts arrivals in the preceding 10 seconds. The contribution rises from zero at four requests to 45 at sixteen. Requests are counted before model generation, including requests rejected by the behavioral gate.",
        ),
        (
            "Diversity / up to 20 points",
            "Mean pairwise cosine distance across the latest 32 hashed character 3-5-gram vectors. This measures lexical variation, not semantic meaning.",
        ),
        (
            "Repetition / up to 35 points",
            "The larger of duplicate share and the share of consecutive pairs with cosine similarity at least 0.80. Diversity and repetition are scaled by sample count and recent activity, each reaching full weight at eight.",
        ),
        (
            "Speed bumps and restrictions",
            "Below 35: normal. 35-39.9: watch. Risk 40-49.9 spaces generation starts by one second; 50-59.9 by three seconds. At 60+: throttle for five seconds; at 80+: block for 30 seconds. Server checks run before inference and before releasing an answer. Live waiting and actual delay appear on the dashboard.",
        ),
        (
            "Operator-approved bulk passes",
            "The dashboard grants up to 30 requests for 1-60 minutes, with a concurrency cap. Approved volume receives rate credit; strong repetition removes it. SQLite preserves usage and revocation across restarts. The operator can run three live scenarios at /dashboard#protection. Fixed integration checks do not prove improved copying resistance.",
        ),
        (
            "Runtime and audit",
            "The CPU model runs in an owned, authenticated loopback llama.cpp process with its web UI disabled. There are two generation slots and a bounded queue. The operator-only SQLite chat audit retains 5,000 questions and replies; live alerts preserve the signals at the decision.",
        ),
    ]:
        doc.text(title, M, y, 11, INK, True)
        y = doc.paragraph(body, y - 12, size=9) - 21
    doc.paragraph(
        "<b>Scope:</b> one server process. Runtime windows and penalties reset on restart; audit records survive. The tiny model can make mistakes. These chat heuristics are separate from the classifier policy and have no cross-key correlation component.",
        y,
        size=9,
    )
    doc.end()

    doc.begin(
        "04 / Solution validation",
        "Measured behavior and limits",
        "Real-model browser checks and synthetic request-pattern checks answer different questions.",
    )
    bw = (W - 2 * M - 22) / 3
    doc.metric(
        M,
        576,
        bw,
        "ATTACKS FLAGGED",
        f"{measured['detection_rate']:.1%}",
        f"{measured['detected_attacks']} / {measured['attack_sessions']} development sessions",
    )
    doc.metric(
        M + bw + 11,
        576,
        bw,
        "FALSE POSITIVES",
        f"{measured['false_positive_rate']:.0%}",
        f"{measured['false_positives']} / {measured['benign_sessions']} benign sessions",
    )
    doc.metric(
        M + 2 * (bw + 11),
        576,
        bw,
        "VISIBLE ALERT",
        f"{evidence['alert_visible_seconds']:.2f}s",
        "One real browser burst run",
    )
    y = 547
    for name, result in measured["profiles"].items():
        doc.text(name.replace("_", " ").capitalize(), M, y, 10, INK)
        doc.text(
            f"{result['flagged']} / {result['sessions']} flagged",
            W - M - 90,
            y,
            10,
            MUTED,
        )
        y -= 28
    y = (
        doc.paragraph(
            "<b>Method:</b> five profiles across seeds 700-711, 30 arrivals per session, fixed policy, virtual time. Detection = flagged attack sessions / attack sessions. False positives = flagged benign sessions / benign sessions. These are development scenarios, not independent holdout estimates. Truth labels never enter the detector.",
            y - 6,
            size=9,
        )
        - 20
    )
    y = (
        doc.paragraph(
            "<b>Failure cases:</b> legitimate bulk questions use the same observable timing and inputs as diverse extraction, so all are flagged. All slow extraction sessions are missed. A faster alert does not establish that a clone became harder to train.",
            y,
            size=9,
        )
        - 20
    )
    y = (
        doc.paragraph(
            f"<b>Real integration:</b> {evidence['passed']} browser checks passed with the installed language model: real replies and follow-up context, separate operator authentication, 30-request enforcement, another key still answering, immutable incident evidence, export, mobile layout, and no browser JavaScript errors. The alert time includes browser polling and is one observed run.",
            y,
            size=9,
        )
        - 20
    )
    doc.paragraph(
        "<b>Reproduce:</b> python -m scripts.chat_check; python -m scripts.evaluate_chat; python -m pytest<br/><b>Evidence:</b> reports/chat-check.json and reports/chat-evaluation.json. Earlier classifier measurements appear separately on page 5.",
        y,
        size=9,
    )
    doc.end()
    experiment_page(
        doc,
        json.loads((ROOT / "reports/copy-experiment.json").read_text(encoding="utf-8")),
        json.loads(
            (ROOT / "reports/defense-comparison.json").read_text(encoding="utf-8")
        ),
    )
    doc.save()
    print(f"Created exactly five pages: {output}")
    return output


def build(team="ModelShield Team", members=""):
    if all(
        (ROOT / "reports" / name).exists()
        for name in [
            "chat-check.json",
            "chat-evaluation.json",
            "copy-experiment.json",
            "defense-comparison.json",
        ]
    ):
        return build_chat_submission(team, members)
    report_path = ROOT / "reports" / "evaluation.json"
    if not report_path.exists():
        raise SystemExit("Run python -m scripts.evaluate first.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result, policy = report["test"], report["policy"]
    output = ROOT / "reports" / "ModelShield-submission.pdf"
    doc = Submission(output, team, members)
    # Page 1: title and team.
    doc.begin(
        "01 / Title",
        "ModelShield",
        "Monitoring requests to an AI model API.",
    )
    doc.box(M, 344, W - 2 * M, 303, DARK, DARK, 13)
    doc.text("MODEL EXTRACTION", M + 28, 590, 35, white, True)
    doc.text("MONITORING", M + 28, 545, 35, HexColor("#a4dfbc"), True)
    doc.paragraph(
        "This prototype looks for repeated probing and shows which API keys deserve attention. It can withhold answers while other keys continue using the model.",
        501,
        width=W - 2 * M - 63,
        x=M + 29,
        size=13,
        color=HexColor("#a4b8be"),
        leading=21,
    )
    doc.text(team, M + 29, 386, 12, white, True)
    if members:
        doc.paragraph(
            escape(members),
            369,
            width=W - 2 * M - 60,
            x=M + 29,
            size=8,
            color=HexColor("#98a9b3"),
        )
    doc.text("HOW THE PROTOTYPE FITS TOGETHER", M, 309, 9, ACCENT, True)
    bw = (W - 2 * M - 24) / 3
    for i, (title, body) in enumerate(
        [
            ("Protected API", "FastAPI + local sentiment model"),
            ("Behavioral defense", "Four signals + cross-key correlation"),
            ("Dashboard", "Request history + explained alerts"),
        ]
    ):
        x = M + i * (bw + 12)
        doc.box(x, 211, bw, 78)
        doc.text(title, x + 12, 262, 10, INK, True)
        doc.paragraph(body, 246, width=bw - 24, x=x + 12, size=8)
    doc.paragraph(
        "<b>Working demo:</b> python enthi.py &nbsp; | &nbsp; http://127.0.0.1:8765<br/><b>Submission assets:</b> source code, automated tests, reproducible traffic, measured benchmark, and live dashboard.",
        174,
        size=10,
    )
    doc.end()
    # Page 2: objective.
    doc.begin(
        "02 / Project objective",
        "Why watch model queries?",
        "Valid API access can still be used to collect a model's answers for copying.",
    )
    y = H - 167
    for title, body in [
        (
            "The business problem",
            "An extraction client repeatedly queries a model and records the returned labels or probabilities. Those answers can become training data for a substitute. The client does not need to exploit the server: valid API access can be enough.",
        ),
        (
            "Who would deploy it",
            "AI SaaS vendors, enterprise AI platforms, and providers of proprietary classifiers could place this detector beside their prediction service. The prototype protects a small sentiment classifier; the behavioral approach can be adapted and independently validated for other classification APIs.",
        ),
        (
            "Why an ordinary rate limit is incomplete",
            "A legitimate batch job can generate a burst. An extraction client can spread its probes over time or across keys. ModelShield combines temporal behavior with input coverage, uncertain answers, controlled changes, and corroborating cross-key evidence.",
        ),
        (
            "What the prototype should do",
            "Flag suspicious sessions, show the reasons, and withhold answers for that key. Other clients should keep receiving predictions. An operator can inspect the evidence; the score does not prove that a model was copied.",
        ),
    ]:
        doc.text(title, M, y, 13, INK, True)
        y = doc.paragraph(body, y - 14, size=10) - 29
    doc.box(M, 103, W - 2 * M, 106, DARK, DARK)
    doc.text("DEMONSTRATION TARGETS", M + 19, 184, 9, HexColor("#a4dfbc"), True)
    doc.paragraph(
        "At least 90% simulated attack detection. Fewer than 5% false positives. Alert within 10 seconds. These are targets, not universal results: the new challenge set exposes missed attacks and copying remains possible.",
        168,
        width=W - 2 * M - 38,
        x=M + 19,
        size=10,
        color=HexColor("#a9b9c3"),
    )
    doc.end()
    # Page 3: solution.
    doc.begin(
        "03 / Proposed solution",
        "How requests are scored",
        "The API and evaluator use the same detector. Each key has its own recent request history.",
    )
    doc.box(M, 638, W - 2 * M, 45, DARK, DARK, 8)
    doc.text(
        "API KEY  >  PENALTY GATE  >  MODEL  >  RISK ENGINE  >  ANSWER / HTTP 429",
        M + 13,
        657,
        8,
        HexColor("#b8d6c8"),
        True,
    )
    doc.text(
        "RISK = 25% RATE + 15% DIVERSITY + 35% BOUNDARY + 25% SEQUENCE",
        M,
        612,
        9,
        ACCENT,
        True,
    )
    y = 585
    rows = [
        (
            "Query rate",
            "10-second burst, normalized against a 36/min starter or bounded learned median baseline.",
        ),
        (
            "Input diversity",
            "Mean pairwise cosine distance among the latest 48 hashed word/bigram vectors. Lexical, not semantic.",
        ),
        (
            "Boundary probing",
            "Fraction of model answers below 65% confidence; a proxy for decision-boundary exploration.",
        ),
        (
            "Sequential probing",
            "Fraction of consecutive, distinct inputs with cosine similarity from 0.48 to 0.985.",
        ),
    ]
    for title, body in rows:
        doc.text(title, M, y, 11, INK, True)
        y = doc.paragraph(body, y - 11, size=9) - 17
    y = (
        doc.paragraph(
            "Signals are clipped to [0,1], weighted, and scaled by min(1, observations / 8). Rate alone contributes at most 25 points. After 16 trusted intervals, a bounded median adapts the baseline. Only low-risk, confident activity contributes.",
            y + 1,
            size=9,
        )
        - 25
    )
    doc.text("RESPONSE THRESHOLDS", M, y, 9, ACCENT, True)
    y -= 17
    for label, body in [
        (
            f"0-{policy['monitor_threshold']-1}",
            "Release the answer and record observations.",
        ),
        (
            f"{policy['monitor_threshold']}-{policy['throttle_threshold']-1}",
            "Monitor; release the prediction.",
        ),
        (
            f"{policy['throttle_threshold']}-{policy['block_threshold']-1}",
            f"Throttle; withhold answer and return Retry-After: {policy['throttle_seconds']}.",
        ),
        (
            f"{policy['block_threshold']}-100",
            f"Block that key for {policy['cooldown_seconds']} seconds; withhold answers.",
        ),
    ]:
        doc.text(label, M, y, 9, INK, True)
        doc.text(body, M + 57, y, 9, MUTED)
        y -= 19
    doc.paragraph(
        "<b>Cross-key campaign detection:</b> at least three keys, three shared normalized input hashes per linked pair, 45% overlap, at least 15 combined observations, five unique probes, and 40% uncertain answers. A 65-88 campaign score can override the per-key score; each member is enforced on its next request.",
        y - 10,
        size=9,
    )
    doc.end()
    # Page 4: validation.
    doc.begin(
        "04 / Solution validation",
        "How we tested it",
        "Calibration and evaluation use separate sessions; v2 replays the previously inspected holdout.",
    )
    y = doc.paragraph(
        f"<b>Calibration:</b> 84 sessions, seeds 100-111, separate subject vocabulary. Fixed weights; select a threshold from 55, 60, 65, 70, 75. Prefer false positives at most 5%, then maximize detection minus false positives, then minimize median latency. Selected threshold: <b>{policy['throttle_threshold']}</b>.<br/><br/><b>v2 regression:</b> 210 sessions, seeds 10000-10029. These reuse the inspected v1 holdout after the sentiment update, not new unseen tests. Calibration subjects differ. The earlier development pilot (1000-1019) was excluded after invalid probes. Sessions span 45 virtual seconds; truth labels never enter the detector. A three-key campaign counts once.",
        H - 163,
        size=10,
    )
    y -= 27
    doc.text("PROFILE", M, y, 8, ACCENT, True)
    doc.text("SESSIONS", M + 215, y, 8, ACCENT, True)
    doc.text("FLAGGED", M + 290, y, 8, ACCENT, True)
    doc.text("MEDIAN DETECTION", M + 365, y, 8, ACCENT, True)
    y -= 24
    for profile in result["profiles"]:
        doc.text(
            profile["profile"].capitalize()
            + (" / attack" if profile["attack"] else " / benign"),
            M,
            y,
            10,
            INK,
        )
        doc.text(str(profile["sessions"]), M + 232, y, 10, MUTED)
        doc.text(str(profile["flagged"]), M + 310, y, 10, MUTED)
        value = profile["median_detection_seconds"]
        doc.text(f"{value:.3f}s" if value is not None else "-", M + 389, y, 10, MUTED)
        doc.c.setStrokeColor(LINE)
        doc.c.line(M, y - 9, W - M, y - 9)
        y -= 30
    y = (
        doc.paragraph(
            "<b>Definitions:</b> detection rate = flagged attack sessions / all attack sessions. False-positive rate = flagged benign sessions / all benign sessions. Time to detect = first threshold crossing minus session start. Timing uses simulated arrival time, not wall-clock hardware latency; only detected attacks enter latency statistics.",
            y - 3,
            size=9,
        )
        - 17
    )
    doc.paragraph(
        f"<b>95% Wilson intervals:</b> detection {result['detection_ci95'][0]:.1%}-{result['detection_ci95'][1]:.1%}; false positives {result['false_positive_ci95'][0]:.1%}-{result['false_positive_ci95'][1]:.1%}.<br/><b>Reproduce:</b> python -m scripts.evaluate<br/><b>Evidence:</b> reports/evaluation.json includes per-session outcomes and the policy fingerprint.",
        y,
        size=9,
    )
    doc.end()
    # Page 5: results.
    copy_path = ROOT / "reports" / "copy-experiment.json"
    comparison_path = ROOT / "reports" / "defense-comparison.json"
    if copy_path.exists() and comparison_path.exists():
        experiment_page(
            doc,
            json.loads(copy_path.read_text(encoding="utf-8")),
            json.loads(comparison_path.read_text(encoding="utf-8")),
        )
        doc.save()
        print(f"Created exactly five pages: {output}")
        return output
    doc.begin(
        "05 / Results and conclusions",
        "What the tests showed",
        "The included scenarios work end to end. Slow attacks and unfamiliar traffic still need more work.",
    )
    bw = (W - 2 * M - 22) / 3
    doc.metric(
        M,
        594,
        bw,
        "ATTACKS DETECTED",
        f"{result['detection_rate']:.0%}",
        f"{result['detected_attacks']} / {result['attack_sessions']} synthetic sessions",
    )
    doc.metric(
        M + bw + 11,
        594,
        bw,
        "FALSE POSITIVES",
        f"{result['false_positive_rate']:.0%}",
        f"{result['false_positives']} / {result['benign_sessions']} benign sessions",
    )
    doc.metric(
        M + 2 * (bw + 11),
        594,
        bw,
        "MEDIAN DETECTION",
        f"{result['median_detection_seconds']:.2f}s",
        f"P95 {result['p95_detection_seconds']:.2f}s; detected attacks",
    )
    screenshot = ROOT / "reports" / "alert-evidence.png"
    if not screenshot.exists():
        screenshot = ROOT / "reports" / "dashboard.png"
    if screenshot.exists():
        image = ImageReader(str(screenshot))
        iw, ih = image.getSize()
        image_h = min(295, (W - 2 * M) * ih / iw)
        image_w = image_h * iw / ih
        doc.c.drawImage(
            image,
            M + (W - 2 * M - image_w) / 2,
            574 - image_h,
            width=image_w,
            height=image_h,
            mask="auto",
        )
        doc.text(
            "Actual browser capture: suspicious predictions withheld while normal clients continue.",
            M,
            565 - image_h,
            7,
            MUTED,
        )
        y = 542 - image_h
    else:
        y = (
            doc.paragraph(
                "Run python -m scripts.browser_check before regenerating this PDF to include the live dashboard screenshot.",
                561,
                size=11,
            )
            - 25
        )
    doc.text("WHAT WORKED IN THESE TESTS", M, y, 10, ACCENT, True)
    y = (
        doc.paragraph(
            "All simulated attack sessions were flagged, and all benign sessions stayed below the action threshold. The live demo shows the penalties and their reasons. These results apply to the included traffic, not every possible extraction attempt.",
            y - 12,
            size=9,
        )
        - 17
    )
    doc.text("WHAT STILL NEEDS WORK", M, y, 10, ACCENT, True)
    doc.paragraph(
        "Slow probing took about 13.4s median, beyond the 10s target. Shared synthetic generators limit generalization. Sentiment probabilities are not calibrated on real customer text. Correlation can miss non-overlapping campaigns. In-memory penalties reset on restart.<br/><b>Next:</b> independently collected traffic, production classifier validation, semantic representations, and a shared state store for multiple workers.",
        y - 12,
        size=9,
    )
    doc.end()
    doc.save()
    print(f"Created exactly five pages: {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", default="ModelShield Team")
    parser.add_argument("--members", default="")
    args = parser.parse_args()
    build(args.team, args.members)
