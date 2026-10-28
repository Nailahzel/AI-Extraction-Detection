"""Build the detailed report and five-page jury brief from inspected evidence.

Run with: python -m scripts.jury_report
The report is an editorial snapshot, not a new benchmark. Evidence guards prevent
silently republishing this interpretation after its underlying results change.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import pymupdf
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
W, H = A4
M = 43
CW = W - 2 * M
INK = HexColor("#172d36")
MUTED = HexColor("#546873")
ACCENT = HexColor("#126f65")
PALE = HexColor("#eaf4ef")
BG = HexColor("#fafbf8")
LINE = HexColor("#d7e2df")
AMBER = HexColor("#925d14")
RED = HexColor("#b24643")
DATE = "10 September 2026"

SOURCES = [
    ("OWASP, LLM10:2025 Unbounded Consumption", "https://genai.owasp.org/llmrisk/llm102025-unbounded-consumption/"),
    ("Tramèr et al., Stealing Machine Learning Models via Prediction APIs, USENIX Security 2016", "https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/tramer"),
    ("Juuti et al., PRADA: Protecting against DNN Model Stealing Attacks, 2018; revised 2019", "https://arxiv.org/abs/1805.02628"),
    ("Dziedzic et al., Increasing the Cost of Model Extraction with Calibrated Proof of Work, ICLR 2022", "https://iclr.cc/virtual/2022/spotlight/6514"),
    ("Qwen, official Qwen2.5-0.5B-Instruct GGUF model card", "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"),
    ("ggml-org, pinned llama.cpp release b10894", "https://github.com/ggml-org/llama.cpp/releases/tag/b10894"),
]
EVIDENCE_FILES = [
    "chat-evaluation.json", "evaluation.json", "defense-comparison.json",
    "copy-experiment.json", "chat-check.json", "protection-check.json",
    "requirements-check.json", "chat-feature-demo.json",
    "chat-feature-demo-transcripts.json", "jury-report-tests.xml",
]


def link(number):
    return f'<a href="{SOURCES[number - 1][1]}" color="#126f65">[{number}]</a>'


def evidence(name):
    return f"<font color='#546873'>Evidence: reports/{escape(name)}.</font>"


def read_evidence():
    data = {}
    for name in EVIDENCE_FILES:
        if name.endswith(".json"):
            data[name.removesuffix(".json")] = json.loads((REPORTS / name).read_text(encoding="utf-8"))
    suites = ElementTree.parse(REPORTS / "jury-report-tests.xml").getroot()
    data["tests"] = {k: sum(int(s.attrib[k]) for s in suites) for k in ("tests", "errors", "failures", "skipped")}
    data["test_time"] = sum(float(s.attrib["time"]) for s in suites)
    chat = data["chat-evaluation"]
    tour = data["chat-feature-demo"]
    full = next(r for r in data["defense-comparison"]["results"] if r["configuration"] == "full")
    copies = {r["name"]: r for r in data["copy-experiment"]["runs"]}
    guards = [
        data["tests"] == {"tests": 88, "errors": 0, "failures": 0, "skipped": 0},
        (chat["detected_attacks"], chat["attack_sessions"], chat["false_positives"], chat["benign_sessions"]) == (24, 36, 12, 24),
        (full["detected"], full["attack_sessions"], full["false_positives"], full["benign_sessions"]) == (12, 30, 0, 18),
        (copies["unprotected"]["released"], copies["protected"]["released"]) == (120, 30),
        (copies["unprotected"]["agreement_matches"], copies["protected"]["agreement_matches"]) == (68, 72),
        tour["status"] == "complete" and len(tour["features"]) == 18,
        all(f["status"] == "passed" for f in tour["features"]),
        tour["totals"] == {"withheld": 118, "answered": 70, "error": 8},
        data["chat-check"]["passed"] == 12,
        data["protection-check"]["passed"] == 13,
        len(data["requirements-check"]["checks"]) == 11,
    ]
    if not all(guards):
        raise ValueError("Evidence changed: review the report's interpretation before generating this edition.")
    return data


def register_fonts():
    fonts = Path("C:/Windows/Fonts")
    for name, filename in [("MS", "segoeui.ttf"), ("MS-Bold", "segoeuib.ttf"), ("MS-Italic", "segoeuii.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily("MS", normal="MS", bold="MS-Bold", italic="MS-Italic", boldItalic="MS-Bold")


class Report:
    def __init__(self, path, team, total, compact=False):
        self.path, self.team, self.total, self.compact = path, team, total, compact
        self.c = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
        self.c.setTitle("ModelShield | " + ("Five-page jury report" if compact else "Detailed project report"))
        self.c.setAuthor(team)
        self.c.setSubject("GITEX Cyber Defense: model extraction detection, enforcement and measured evidence")
        self.c.setKeywords("ModelShield, GITEX, model extraction, validation, bulk passes, speed bumps")
        self.page = 0
        self.y = H
        self.sections = set()
        self.page_titles = []

    def text(self, value, x, y, size=10, color=INK, bold=False):
        self.c.setFont("MS-Bold" if bold else "MS", size)
        self.c.setFillColor(color)
        self.c.drawString(x, y, value)

    def begin(self, section, title, subtitle):
        self.page += 1
        self.page_titles.append(title)
        self.c.setFillColor(BG)
        self.c.rect(0, 0, W, H, fill=1, stroke=0)
        self.c.setFillColor(ACCENT)
        self.c.rect(M, H - 43, 18, 4, fill=1, stroke=0)
        self.text("MODELSHIELD", M + 27, H - 43, 9, ACCENT, True)
        self.c.setFont("MS", 8)
        self.c.setFillColor(MUTED)
        self.c.drawRightString(W - M, H - 43, section.upper())
        self.c.bookmarkPage(f"page-{self.page}")
        if section not in self.sections:
            self.c.addOutlineEntry(section, f"page-{self.page}", level=0, closed=False)
            self.sections.add(section)
        elif not self.compact:
            self.c.addOutlineEntry(title, f"page-{self.page}", level=1, closed=False)
        self.y = H - 74
        self.p(escape(title), size=24 if not self.compact else 22, leading=29, color=INK, bold=True, gap=7)
        self.p(subtitle, size=9.1, leading=12.6, gap=17, color=MUTED)

    def check(self, height):
        if self.y - height < 64:
            raise ValueError(f"Page {self.page} ({self.page_titles[-1]}) overflows by {64 - self.y + height:.1f} pt")

    def p(self, value, size=None, leading=None, color=INK, bold=False, gap=9):
        size = size or (9.8 if self.compact else 10)
        style = ParagraphStyle("p", fontName="MS-Bold" if bold else "MS", fontSize=size,
                               leading=leading or size * 1.38, textColor=color)
        paragraph = Paragraph(value, style)
        _, height = paragraph.wrap(CW, H)
        self.check(height)
        paragraph.drawOn(self.c, M, self.y - height)
        self.y -= height + gap

    def h2(self, title):
        self.p(escape(title), size=11.5, leading=15, bold=True, color=ACCENT, gap=6)

    def table(self, headers, rows, widths=None, size=None):
        size = size or (8.9 if self.compact else 9)
        widths = widths or [CW / len(headers)] * len(headers)
        widths = [CW * w / sum(widths) for w in widths]
        style = ParagraphStyle("cell", fontName="MS", fontSize=size, leading=size * 1.3, textColor=INK)
        head_style = ParagraphStyle("head", parent=style, fontName="MS-Bold", textColor=white)
        cells = [[Paragraph(escape(str(h)), head_style) for h in headers]]
        cells.extend([[Paragraph(str(v), style) for v in row] for row in rows])
        table = Table(cells, colWidths=widths, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, PALE]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7 if not self.compact else 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7 if not self.compact else 5),
            ("LINEBELOW", (0, 1), (-1, -1), .35, LINE),
        ]))
        _, height = table.wrap(CW, H)
        self.check(height)
        table.drawOn(self.c, M, self.y - height)
        self.y -= height + 13

    def note(self, title, body, caution=False):
        color = AMBER if caution else ACCENT
        style = ParagraphStyle("note", fontName="MS", fontSize=9 if self.compact else 9.5,
                               leading=12.6, textColor=INK)
        p = Paragraph(f"<b>{escape(title)}</b><br/>{body}", style)
        _, height = p.wrap(CW - 28, H)
        height += 23
        self.check(height)
        self.c.setFillColor(HexColor("#fff4df") if caution else PALE)
        self.c.roundRect(M, self.y - height, CW, height, 5, stroke=0, fill=1)
        self.c.setFillColor(color)
        self.c.rect(M, self.y - height, 3, height, stroke=0, fill=1)
        p.drawOn(self.c, M + 14, self.y - height + 12)
        self.y -= height + 13

    def metrics(self, cards):
        height, gutter = 82, 12
        self.check(height)
        width = (CW - gutter * (len(cards) - 1)) / len(cards)
        for i, (value, label, detail) in enumerate(cards):
            x = M + i * (width + gutter)
            self.c.setFillColor(PALE)
            self.c.roundRect(x, self.y - height, width, height, 6, stroke=0, fill=1)
            self.text(value, x + 12, self.y - 31, 25, ACCENT, True)
            self.text(label, x + 12, self.y - 50, 9, INK, True)
            self.text(detail, x + 12, self.y - 66, 7.2, MUTED)
        self.y -= height + 17

    def picture(self, filename, height, caption):
        reader = ImageReader(str(REPORTS / filename))
        iw, ih = reader.getSize()
        width = min(CW, height * iw / ih)
        height = width * ih / iw
        self.check(height)
        self.c.drawImage(reader, M + (CW - width) / 2, self.y - height, width, height, mask="auto")
        self.y -= height + 6
        self.p(caption, size=8, leading=11, color=MUTED, gap=13)

    def pipeline(self):
        labels = [("01  CLIENT", "API key + question"), ("02  GATE", "Validate / score / pace"),
                  ("03  MODEL", "Private local inference"), ("04  RELEASE", "Recheck / answer / audit")]
        height, gap = 64, 12
        self.check(height)
        width = (CW - 3 * gap) / 4
        for i, (title, detail) in enumerate(labels):
            x = M + i * (width + gap)
            self.c.setFillColor(INK if i == 2 else PALE)
            self.c.roundRect(x, self.y - height, width, height, 5, stroke=0, fill=1)
            self.text(title, x + 9, self.y - 24, 8, white if i == 2 else ACCENT, True)
            self.text(detail, x + 9, self.y - 43, 6.8, white if i == 2 else INK)
            if i < 3:
                self.text("›", x + width + 3, self.y - 36, 12, ACCENT)
        self.y -= height + 16

    def bars(self, values, title):
        self.h2(title)
        self.check(29 * len(values) + 22)
        x = M + 173
        width = CW - 223
        for label, value, color in values:
            self.text(label, M, self.y - 12, 9)
            self.c.setFillColor(LINE)
            self.c.rect(x, self.y - 16, width, 11, stroke=0, fill=1)
            if value:
                self.c.setFillColor(color)
                self.c.rect(x, self.y - 16, width * value, 11, stroke=0, fill=1)
            self.text(f"{value:.1%}", x + width + 8, self.y - 13, 9, color, True)
            self.y -= 29
        self.p("Bar scale: 0–100%. Denominators and evaluation scope are given below.", size=8, color=MUTED)

    def end(self):
        self.c.setStrokeColor(LINE)
        self.c.line(M, 46, W - M, 46)
        self.text(f"{self.team}  |  GITEX Cyber Defense  |  {DATE}", M, 30, 7.2, MUTED)
        self.c.setFont("MS", 8)
        self.c.setFillColor(MUTED)
        self.c.drawRightString(W - M, 30, f"{self.page:02d} / {self.total:02d}")
        self.c.showPage()

    def save(self):
        if self.page != self.total:
            raise ValueError(f"Expected {self.total} pages, wrote {self.page}")
        self.c.save()


DELIVERABLES = [
    ("Working inference API", "POST /predict serves the local, open-source TF-IDF + logistic-regression text classifier. POST /chat/messages adds a real local Qwen chatbot.", "Requirements &amp; evidence; Classifier lab; /chat"),
    ("Normal + extraction traffic", "Seeded classifier profiles include normal, burst, boundary, slow and distributed traffic. Chat has normal/extraction scripts and editable batches of up to 30 questions.", "Live monitoring; Attack lab; chat batch form"),
    ("At least 2–3 signals", "Classifier: rate, diversity, low-confidence share and consecutive-query variation. Chat: rate, lexical diversity and repetition.", "Client details; incident signal contributions"),
    ("Real-time response", "Live alerts, recorded reasons, server pacing, HTTP 429 throttles and temporary blocks. Checks occur again before chat answers are released.", "Red flags; restricted clients; Protection"),
    ("Measured quality", "Saved detection and false-positive rates, profile failures, calibrated baselines and a classifier-copy experiment. Integration checks are identified separately.", "Requirements &amp; evidence; report downloads"),
]
RUBRIC = [
    ("Fit / business problem", "20%", "Model API operators can investigate suspicious answer collection and limit further releases.", "§2; API + traffic demo"),
    ("Solution relevance", "15%", "Local open models, bounded queues, API controls and current risk guidance; practical deployment limits are explicit.", "§2–3; sources [1], [5], [6]"),
    ("Working prototype", "25%", "README launch, real-model browser checks, repeated runs, restart persistence and invalid-input handling.", "§4; tests + 18-feature tour"),
    ("Technical correctness", "25%", "Inspectable formulas, atomic pass accounting, frozen comparisons and honest separation of regression / challenge results.", "§3–5; quality + copy reports"),
    ("Innovation", "15%", "Graduated pacing plus bounded operator approvals, with repeated-probe override and visible request-level evidence.", "§3; live protection demo"),
]


def chat_table(d, report):
    names = {
        "normal_conversation": "Paced normal conversation (benign)",
        "legitimate_bulk_questions": "Legitimate bulk, no pass (benign)",
        "repeated_extraction_probes": "Repeated extraction (attack)",
        "diverse_extraction_queries": "Diverse extraction (attack)",
        "slow_extraction_probes": "Slow extraction (attack)",
    }
    report.table(["Profile", "Flagged / sessions", "Meaning"], [
        (names[k], f"{v['flagged']} / {v['sessions']}", "False positives" if k == "legitimate_bulk_questions" else "Missed attacks" if k == "slow_extraction_probes" else "Expected outcome")
        for k, v in d["chat-evaluation"]["profiles"].items()
    ], [53, 22, 25])


def comparison_table(d, report):
    report.table(["Classifier configuration", "Detected attacks", "False positives", "Median time*"], [
        (r["configuration"].replace("_", " "), f"{r['detected']}/{r['attack_sessions']} ({r['detection_rate']:.0%})",
         f"{r['false_positives']}/{r['benign_sessions']}", "—" if r["median_detection_seconds"] is None else f"{r['median_detection_seconds']:g} s")
        for r in d["defense-comparison"]["results"]
    ], [34, 25, 22, 19])


def copy_table(d, report):
    report.table(["Classifier copying run", "Answers / attempts", "Copy agreement", "Benign allowed"], [
        (r["name"].replace("_", " "), f"{r['released']} / {r['attempted']}",
         f"{r['agreement_matches']}/{r['evaluation_inputs']} ({r['agreement']:.1%})",
         f"{r['legitimate']['allowed']}/{r['legitimate']['attempted']}")
        for r in d["copy-experiment"]["runs"]
    ], [30, 23, 28, 19])


def detailed(d, team):
    r = Report(REPORTS / "ModelShield-detailed-report.pdf", team, 16)
    r.begin("1. Title slide", "ModelShield", "Detailed project report • GITEX Cyber Defense hackathon • Prototype and evidence snapshot")
    r.p("Spot suspicious answer collection.<br/>Control access while it is happening.", size=23, leading=31, bold=True, gap=17)
    r.p("A working inference API, a separate local chatbot, and a security dashboard that shows why a client was delayed, throttled or blocked.", size=12, leading=17, color=MUTED, gap=19)
    r.metrics([("5 / 5", "Brief items mapped", "Implementation coverage"), ("18 / 18", "Demo features passed", "Saved real-model tour"), ("88 / 88", "Automated tests passed", "Fresh verification run")])
    r.picture("jury-overview.png", 270, "Actual application screenshot: the operator's Requirements &amp; evidence view maps the five deliverables to inspectable evidence.")
    r.note("What this report establishes", "The prototype detects demonstrated extraction-like patterns and controls answer release. Its own measurements also expose false positives and missed attacks. Prevention of successful model cloning has not been established.")
    r.p("<b>Prepared for:</b> the competition jury &nbsp; | &nbsp; <b>Team:</b> " + escape(team) + "<br/><b>Report date:</b> " + DATE + " &nbsp; | &nbsp; <b>Chat policy:</b> chat-heuristics-v2", size=9, gap=0)
    r.end()

    r.begin("2. Project objective", "The problem and the customer", "Fit to the brief and business problem • 20% of the jury rubric")
    r.h2("The asset is the model's useful behaviour")
    r.p("An organisation can keep its model files private and still expose valuable behaviour through an API. A collector sends many chosen inputs, saves the answers, then trains a substitute to imitate them. The defence therefore needs to observe request patterns while answers are being collected. API-based extraction is an established research problem. " + link(2))
    r.h2("Who would deploy ModelShield?")
    r.p("The intended deployer is an AI platform team exposing a proprietary classifier or conversational service. Its security operator needs to identify suspicious keys, explain incidents, preserve evidence and apply proportionate restrictions. The intended buyer is the organisation responsible for that model API; no customer interviews, paid deployments or revenue claims are presented here.")
    r.table(["Current operator task", "What the prototype supplies"], [
        ("Search disconnected request logs after an incident", "A live feed connecting each request, response status, key, signal contribution and recorded incident."),
        ("Apply one flat limit to every customer", "Graduated pacing and restrictions, plus a time-limited allowance for an explicitly approved bulk workflow."),
        ("Decide whether an alert means the model was copied", "Separate detection metrics, answer-release counts and measured classifier-copy agreement."),
    ], [40, 60])
    r.h2("A precise objective")
    r.p("Build and demonstrate an API gateway for inference that notices high-rate, diverse or repeatedly varied query sequences and can withhold further answers. Keep a normal user's conversation usable, and give the operator enough evidence to distinguish a suspicious pattern from an approved bulk task.")
    r.note("Threat model", "The attacker can submit requests using an authenticated client key and train on released answers. They do not control the host or administrator account. A burst is evidence of a pattern, not proof of intent. Slow collection and multiple chat keys remain important evasion routes.")
    r.h2("Why this approach is relevant now")
    r.p("OWASP's 2025 LLM guidance includes excessive inference and model replication, and recommends quotas, bounded queues, throttling and monitoring. ModelShield combines those operational controls with observable request-pattern scoring. The attack is not new; this project applies established ideas to an inspectable local prototype. " + link(1))
    r.end()

    r.begin("2. Project objective", "The brief, mapped to evidence", "All five minimum deliverables are implemented; implementation coverage is different from detection effectiveness.")
    r.table(["Minimum deliverable", "Implemented behaviour", "Where the jury sees it"], DELIVERABLES, [25, 49, 26], size=8.6)
    r.h2("How this report addresses the judging rubric")
    r.table(["Criterion", "Weight", "Evidence-led case", "Location"], RUBRIC, [24, 10, 43, 23], size=8.3)
    r.p("The weights total 100%. These are mappings to evidence, not self-awarded scores. The text classifier meets the brief's exact classifier requirement; the conversational model is an additional demonstration.", size=9, color=MUTED)
    r.end()

    r.begin("3. Proposed solution", "Architecture and model boundary", "A customer uses the chatbot. An operator watches and controls the same requests in the dashboard.")
    r.pipeline()
    r.h2("One request, from input to evidence")
    r.p("The API authenticates the key and validates the request. For chat, it records the arrival and reserves an approved pass slot if one is supplied. It calculates risk, applies pacing or a restriction, and admits work to the bounded model queue. The request is checked again after queueing and before any generated answer is released. The operator can then inspect the recorded question, released answer or denial, waiting time and signal reasons.")
    r.table(["Surface / component", "Purpose and boundary"], [
        ("/chat → POST /chat/messages", "Real conversations and manual batches of up to 30 independent questions. Customer credentials do not grant operator access."),
        ("/dashboard", "Live feed, client risk, red flags, evidence export, requirement mapping, speed bumps, bulk approvals and feature demonstrations. Live polling is every 1.5 seconds."),
        ("/classifier-lab → POST /predict", "Separate sentiment-classifier inference, four-signal monitoring, distributed-query correlation and classifier-only experiments."),
        ("SQLite + in-memory windows", "Persisted chat audit and bulk-pass state; volatile current risk windows and live counters. The distinction matters after restart."),
    ], [37, 63])
    r.h2("Two models, two evaluation scopes")
    r.p("<b>Core brief:</b> Sentinel / TF-IDF sentiment v2 uses word/bigram TF-IDF features and logistic regression, trained on 2,432 original synthetic rows. The project code and corpus use the MIT license. Positive/negative classification supplies an observable inference target; it is not the model-theft detector.")
    r.p("<b>Conversation extension:</b> Qwen2.5-0.5B-Instruct Q4_K_M runs through a private local llama.cpp process. The official GGUF model is Apache-2.0 licensed. The application pins its downloaded model and runtime; it does not train a new conversational model. " + link(5) + " " + link(6))
    r.note("Deployment scope", "The exercised setup is Windows x64, Python 3.13, CPU inference and one application worker. After setup, conversation does not need a cloud API or internet. The optional Swagger /docs page uses CDN scripts; /openapi.json and the local dashboard remain available offline.")
    r.end()

    r.begin("3. Proposed solution", "How suspicion is calculated", "Explicit heuristics make the decision inspectable. A risk score is not the probability that a user is stealing a model.")
    r.h2("Chat policy: three request-side signals")
    r.table(["Signal", "Calculation", "Maximum"], [
        ("Rate R", "R = clip((q − 4) / 12), where q is arrivals in the preceding 10 seconds.", "45 points"),
        ("Diversity D", "Mean pairwise cosine distance between recent hashed character 3–5-gram vectors.", "20 points"),
        ("Repetition P", "The larger of exact duplicate share and consecutive-pair similarity ≥ 0.80 share.", "35 points"),
    ], [20, 63, 17])
    r.note("Chat score before approval credit", "S = 45R + 20DAE + 35PAE<br/>E = min(1, n/8); A = min(1, q/8); clip limits a value to [0, 1].<br/>The 60-second window retains at most 256 arrivals; n is the recent vector count, capped at 32. Character features use 2,048 dimensions. Sparse early evidence is downweighted.")
    r.p("These are lexical features, not semantic embeddings. Distant topics and near-duplicate questions are observable; the system cannot establish why the customer asked them. No sentiment label or fabricated LLM-confidence value enters this chat score.")
    r.h2("Classifier policy: four distinct signals")
    r.table(["Signal", "Normalised contribution before evidence weight"], [
        ("Rate • 25 points", "clip((burst_rpm / baseline_rpm − 1) / 3). The starter baseline is 36/min; after 16 trusted intervals, a median-based estimate is bounded to 12–120/min."),
        ("Diversity • 15 points", "clip((mean lexical cosine distance − 0.35) / 0.5)."),
        ("Boundary • 35 points", "clip((low-confidence share − 0.10) / 0.65); low confidence means &lt; 0.65."),
        ("Sequence • 25 points", "clip(controlled variation share / 0.65); distinct adjacent inputs count when cosine similarity is from 0.48 up to, but not including, 0.985."),
    ], [28, 72], size=8.8)
    r.p("The weighted classifier sum is multiplied by min(1, observations/8). Confidence is an uncertainty proxy, not a calibrated probability of attack. Classifier thresholds are monitor 35, throttle 55 for 2 seconds, and block 80 for 30 seconds.", size=9)
    r.p("Implementation references: modelshield/chat_engine.py; modelshield/engine.py; modelshield/config.py.", size=8, color=MUTED)
    r.end()

    r.begin("3. Proposed solution", "Speed bumps and bulk approval", "The two additions connect suspicion to a proportionate response and explicit customer context.")
    r.table(["Chat risk", "Customer experience", "Operator evidence"], [
        ("Below 35", "Normal service", "Request, reply and current signals"),
        ("35 to &lt;40", "Watched; answers still allowed", "Raised score and contributing signals"),
        ("40 to &lt;50", "One-second server pacing", "Waiting status and measured wait time"),
        ("50 to &lt;60", "Three-second server pacing", "Stronger pacing level and queue activity"),
        ("60 to &lt;80", "Five-second throttle; HTTP 429", "Restriction reason and Retry-After"),
        ("80 or above", "Thirty-second block; HTTP 429", "Restricted client and incident evidence"),
    ], [18, 42, 40])
    r.p("Pacing is enforced under a per-key lock before a model slot is acquired. Parallel requests cannot all wait the same interval and then start together. A queued request retains its assigned spacing; later ordinary requests can recover as the rolling evidence decays. Rejected retries do not extend an already active block.")
    r.h2("The legitimate bulk-use pass")
    r.p("An operator approves a named client for 1–30 requests, 1–60 minutes and 1–2 simultaneous generations, with a recorded purpose. The customer still supplies its own API key. A pass ID alone grants no access. Only one unexpired, unrevoked pass is allowed per key, including an exhausted pass; the operator must explicitly revoke it before issuing a replacement.")
    r.note("Credit is limited, and monitoring continues", "Approved arrivals receive a share of the rate points back: rate credit = raw rate points × approved arrivals / all arrivals in the last 10 seconds. Diversity and repetition still count. With at least 8 recent inputs and repetition ≥ 0.65, all rate credit is removed.")
    r.p("Each accepted reservation consumes one slot atomically and persists the usage before inference. Refreshing or restarting cannot refill it. Revocation and expiry are checked again while work is queued and before generated answers are released. Accepted reservations remain counted if they later fail, are cancelled or are withheld.")
    r.note("What approval does not establish", "Approval supplies trusted operator context; it does not make the detector understand intent. An approved malicious user may still collect varied answers within the allowance. Requests that omit the pass use the ordinary policy. This is per-key accounting, not a tenant-wide identity or spending budget.", caution=True)
    r.end()

    r.begin("3. Proposed solution", "Engineering depth and innovation", "Innovation is the tested combination and its visibility, with prior work acknowledged.")
    r.h2("A simple combination with an operational purpose")
    r.p("Pattern monitoring predates this project: PRADA examines distributions of consecutive API queries. Calibrated proof-of-work research also explores increasing the cost of extraction. ModelShield uses server-side delays, not proof-of-work puzzles, and makes no claim to have invented either pattern detection or graduated friction. " + link(3) + " " + link(4))
    r.p("The project's contribution is an inspectable workflow: a customer can submit a legitimate batch, an operator can approve a bounded allowance, repeated probing can remove that allowance's rate credit, and both parties see the resulting behaviour. The same request evidence supports the live demonstration and the jury's review.")
    r.table(["Engineering choice", "Why it matters / practical limit"], [
        ("Queue and release checks", "Two model slots, up to 32 pending requests and per-key concurrency limits bound work. Restriction / expiry / revocation is rechecked before release. A generated but withheld answer still consumed compute."),
        ("Operator separation", "Admin bearer token or HttpOnly, SameSite=Strict cookie; origin checks protect cookie-authenticated mutations. Public demo identities and automatic local operator cookies belong to loopback demo mode."),
        ("Private pinned runtime", "The local model service uses a random private credential, loopback binding and no web UI. Pinned SHA-256 checks and safe archive paths protect setup against mismatched downloads and path traversal."),
        ("Evidence retention", "Chat stores up to 5,000 questions and replies locally. Classifier audit stores metadata without raw prompts. Operators can export evidence; raw chat retention needs a deployment privacy policy."),
    ], [29, 71], size=8.8)
    r.h2("An additional classifier-only correlation mechanism")
    r.p("The classifier links keys sharing at least three normalised input fingerprints with at least 45% overlap relative to the smaller set. A candidate campaign needs at least three keys, 15 pooled events, five unique inputs and 40% low-confidence predictions. Shared text is evidence of coordination, not proof of shared identity. This correlation is not implemented for chat.", size=9.5)
    r.note("Cryptography and deployment claims kept precise", "SHA-256 fingerprints are deterministic hashes, not encryption; known text can be guessed. The audit is not cryptographically signed or tamper-proof. No custom encryption or nonce scheme is claimed. Production needs TLS, non-demo credentials, shared enforcement state, retention controls and independent traffic validation.", caution=True)
    r.end()

    r.begin("4. Solution validation", "Reproduce the working prototype", "Commands below follow the README's exercised Windows / Python 3.13 workflow.")
    r.h2("First-time setup, from the project folder")
    r.note("PowerShell", "<font name='Courier' size='9'>python -m venv .venv<br/>.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt<br/>.\\.venv\\Scripts\\python.exe -m scripts.setup_chat<br/>.\\.venv\\Scripts\\python.exe enthi.py</font>")
    r.p("The setup downloads about 491 MB of model weights and an 18 MB Windows CPU runtime from official repositories, verifies pinned checksums and installs them locally. Keep this completed before the jury session. The classifier requires no separate model download. Other operating systems' classifier commands are documented but were not exercised here.")
    r.table(["Open in the browser", "Show the jury"], [
        ("http://127.0.0.1:8765/chat", "Ask a normal question, then a follow-up. Use Batch questions for up to 30 manually entered questions."),
        ("http://127.0.0.1:8765/dashboard", "Watch requests, responses, live signals, red flags and restricted clients in another tab."),
        ("/dashboard#protection", "Run the fixed speed-bump, approved-bulk and probing examples; inspect waiting time and approval usage."),
        ("/dashboard<br/>/dashboard#feature-demo", "Show live traffic, client signals and the expandable saved feature checklist. Measured quality is recorded in the reports."),
    ], [46, 54])
    r.h2("Normal traffic, then extraction traffic")
    r.note("With the server running", "<font name='Courier' size='8.8'>.\\.venv\\Scripts\\python.exe -m scripts.chat_traffic --profile normal --count 3<br/>.\\.venv\\Scripts\\python.exe -m scripts.chat_traffic --profile extraction --count 30</font>")
    r.p("For a visible guided tour, run <b>python -m scripts.demo_chat_features</b> with the virtual environment active. It opens chat and monitoring together. At the restart checkpoint, restart enthi.py in its terminal; the tour checks durable pass usage and saved transcripts. --resume continues a saved checkpoint; --skip-restart explicitly omits that test.")
    r.h2("Repeat safely and make state visible")
    r.p("A new conversation does not clear the key's risk. For a clean manual comparison, stop sending on that key for at least 60 seconds, or use an unused demo key. Audit evidence remains visible. If an operator tab loses its cookie after restart, refresh /dashboard. Use --port 8766 if 8765 is occupied.")
    r.end()

    r.begin("4. Solution validation", "Tests, failures and persistence", "Working-prototype evidence • 25% of the rubric • automated checks and real-model checks have different scopes.")
    r.metrics([("88", "Tests passed", "0 failed / errored / skipped"), ("7.014 s", "Captured alert visibility", "One real browser scenario"), ("18", "Tour features passed", "Scripted demonstrations")])
    r.table(["Evidence file", "Observed outcome", "What it verifies"], [
        ("jury-report-tests.xml", f"88 passed; {d['test_time']:.1f} s", "Fresh pytest run on this report date. Automated behaviour checks, not 88 independent security attacks."),
        ("chat-check.json", "12 checks passed", "Real Qwen responses and context; 30-request restriction, client isolation, operator authentication, mobile layout and export."),
        ("protection-check.json", "13 checks passed", "Measured pacing, 30 approved answers, probing with approval, quotas, revocation, refresh and narrow-screen controls."),
        ("requirements-check.json", "11 checks passed", "All requirement cards, evidence scope, valid downloads, no traffic caused by viewing, mobile layout and missing-report handling."),
    ], [33, 24, 43], size=8.8)
    r.p("The browser suites overlap and are not added together as independent accuracy samples. Their saved runs reported no JavaScript errors. The 7.014-second alert timing includes the UI observation path in one captured run; it is not an average, SLA or universal detection deadline.", size=9)
    r.h2("Unexpected input and interrupted work")
    r.p("The API bounds request bodies to 16 KiB and chat messages to 2,000 characters, validates history and conversation IDs, and rejects malformed input. The browser rejects a 31-question batch before inference. Invalid credentials cannot grant operator access. Behavioural restrictions return 429; unavailable inference or an overloaded queue returns 503. Cancellations are recorded as errors, not successful answers.")
    r.h2("What a restart preserves")
    r.p("SQLite preserves pass usage, expiry and revocation, together with saved questions and replies. The tour observed a pass remain at 1/3 used after an actual restart. Current risk windows, live counters and active in-memory alerts reset. Incomplete requests are recovered as errors. This is a single-worker prototype, not distributed persistent enforcement.")
    r.note("How to repeat the checks", "Install requirements-dev.txt, then run python -m pytest. Microsoft Edge is required for python -m scripts.chat_check, scripts.protection_check and scripts.requirements_check. The integration checks use isolated temporary servers/data; the visible tour uses and records the local demo clients.")
    r.end()

    r.begin("4. Solution validation", "The 18-feature demonstration", "Features 1–9 • Real chatbot interactions, with saved operator evidence for each completed step.")
    features = d["chat-feature-demo"]["features"]
    r.table(["Feature", "Observed result"], [
        (f"<b>{i + 1:02d}. {escape(f['title'])}</b>", escape(f["result"])) for i, f in enumerate(features[:9])
    ], [35, 65], size=9.1)
    r.h2("The customer sees the same enforcement")
    r.p("The approved batch displayed 30 completed questions, 30 answers and an exhausted 30/30 allowance. Pacing appeared as waiting while answers were still delivered. A later request using the exhausted pass was withheld. These outcomes came from real inference calls, not dashboard-only animations.")
    r.note("Show it live", "Open /chat beside /dashboard#protection. Select the same demo identity on both sides. Demonstrate a normal question, a short probing burst that is paced, and a 30-question varied batch with an operator-issued pass. The dashboard records usage, waiting and outcomes as they happen.")
    r.p(evidence("chat-feature-demo.json") + " The validation / operator-separation item includes browser and authentication checks that do not invoke the model; it is labelled accordingly.", size=8.5, color=MUTED)
    r.end()

    r.begin("4. Solution validation", "Restriction, recovery and evidence", "Features 10–18 • Approval does not remove monitoring, and a new conversation cannot erase a key's penalty.")
    r.table(["Feature", "Observed result"], [
        (f"<b>{i + 10:02d}. {escape(f['title'])}</b>", escape(f["result"])) for i, f in enumerate(features[9:])
    ], [35, 65], size=8.9)
    totals = d["chat-feature-demo"]["totals"]
    r.note("Final saved tour totals", f"{sum(totals.values())} requests: {totals['answered']} answered, {totals['withheld']} withheld and {totals['error']} errors from intentional cancellation. The export step captured 166 requests; a final 30-request probe brought the complete saved transcript to 196. No model accuracy percentage is inferred from these counts.")
    r.p("The completed tour included a resumed restart checkpoint. It is not evidence of an unattended, uninterrupted run from start to finish. Saved tour outcomes are kept separate from live counters, which reset on server restart.", size=9, color=MUTED)
    r.p(evidence("chat-feature-demo.json") + " " + evidence("chat-feature-demo-transcripts.json"), size=8.3, color=MUTED)
    r.end()

    r.begin("4. Solution validation", "Measurement design and correctness", "Technical depth and correctness • 25% of the rubric • preserve denominators, baselines and data provenance.")
    r.h2("What detection rate and false-positive rate mean")
    r.note("Session-level metrics", "Detection rate = attack sessions reaching the restriction threshold / all attack sessions.<br/>False-positive rate = benign sessions reaching that threshold / all benign sessions.<br/>For chat, detection means throttle or block, not just watching or pacing. Multiple denied requests within one session do not become multiple detected attacks.")
    r.table(["Evidence family", "Protocol and limitation"], [
        ("Chat development evaluation", "60 synthetic sessions, virtual arrival times, standard access without bulk passes. No actual waiting, LLM generation or independent holdout. The detector never receives the attack/benign label."),
        ("Earlier classifier regression", "84 calibration sessions; weights fixed and throttle threshold selected on calibration. The 210-session suite was inspected during v1 and reused after the v2 update: it is regression evidence, not fresh unseen evaluation."),
        ("New classifier challenges", "Calibration seeds 210–213; challenge seeds 31000–31005. Settings frozen before evaluation. Locally authored challenge families are new relative to calibration but are not an independent teammate dataset."),
        ("Classifier-copy experiment", "Fresh state and identical candidate order per run; seed 7319, up to 120 attempts or 8 seconds. A label-only copier trains on released answers and is compared on 90 separate local synthetic sentences."),
    ], [30, 70], size=9)
    r.h2("A fair baseline and honest separation")
    r.p("The classifier comparison calibrates a real 60-second rate limiter independently, selecting capacity 160 against the same ≤5% calibration false-positive target. The four-signal and full variants use threshold 55 and identical two-second throttles, without the production 30-second block. This isolates the comparison; it does not silently change the running production policy.")
    r.p("The copy learner uses character 3–5-gram TF-IDF and logistic regression with C=2. It sees released labels only, not protected weights, the protected training corpus, administrative controls or confidence values. Evaluation sentences have different subjects and templates. Hashes identify the protocol and data; they do not establish independent authorship.")
    r.note("Statistics are bounded by the dataset", "The saved classifier challenge's 95% Wilson intervals are 24.6–57.7% for detection and 0–17.6% for false positives. Zero observed false positives among 18 benign sessions is not proof of zero operational risk. Related synthetic scenarios also limit independence assumptions.", caution=True)
    r.end()

    r.begin("5. Results and conclusions", "Chat quality: what was measured", "Standard access without approved passes • synthetic development scenarios • not a model-cloning benchmark")
    chat = d["chat-evaluation"]
    r.bars([("Attack detection: 24 / 36", chat["detection_rate"], ACCENT), ("False positives: 12 / 24", chat["false_positive_rate"], RED)], "Measured session outcomes")
    chat_table(d, r)
    r.h2("What the result means")
    r.p("The detector flagged repeated and diverse extraction bursts in these generated sessions and kept paced normal conversations clear. It missed every slow-extraction session. It also restricted every unapproved legitimate-bulk session, because that profile deliberately has the same observable inputs and timing as the diverse attacker. These labels describe the generator's intent; they are not facts the detector can infer.")
    r.h2("What the pass demonstration adds")
    r.p("In the separate real-model feature tour, all 30 approved varied questions were answered. Repeated probing under approval later removed the rate credit and withheld 25/30 answers. In the isolated protection integration check, a different probing run withheld 30/30. These are separate runs with different state and timing, not contradictory accuracy estimates.")
    r.note("Do not report a new 0% chat false-positive rate", "The approved workflow shows that operator context can permit a legitimate burst. The baseline remains 66.7% detection and 50.0% false positives on its stated synthetic sessions. A policy-level evaluation that includes approval decisions, misuse and representative customer traffic has not yet been performed.", caution=True)
    r.p(evidence("chat-evaluation.json") + " " + evidence("protection-check.json") + " " + evidence("chat-feature-demo.json"), size=8.5, color=MUTED)
    r.end()

    r.begin("5. Results and conclusions", "Classifier and copying results", "These experiments concern the sentiment classifier. They do not establish protection of the conversational model.")
    r.h2("New local challenge families")
    comparison_table(d, r)
    r.p("*Median detection time is virtual elapsed time among detected sessions, not API latency. The behavioural variants reached the threshold sooner in their detected sessions (5.1 s versus 32 s), but full detection did not exceed the rate-only baseline: both detected 12/30 attacks with 0/18 false positives. No added detection-rate gain from correlation was shown on this challenge set.", size=9)
    r.p("The earlier inspected regression suite reported 120/120 detected attacks and 0/90 false positives. That 100%/0% result is a regression diagnostic; presenting it as an unseen real-world accuracy estimate would overstate the evidence.", size=9)
    r.h2("Actual attempt to train a copy through the API")
    copy_table(d, r)
    r.p("The 90 evaluation sentences contain 30 positive and 60 negative reference labels; always predicting the majority label would agree 66.7% of the time. Copy agreement measures imitation of this classifier, not a percentage of model ownership stolen.", size=9)
    r.note("Fewer released answers did not make the measured copy weaker", "Protection reduced released labels from 120 to 30: a 75% reduction in this short run. Yet copy agreement rose from 75.6% to 80.0%. The retry-aware collector also achieved 80.0% using 28 released labels. Therefore this experiment does not demonstrate lower cloning success or prove prevention.", caution=True)
    r.p("All three runs allowed the separate legitimate key's 16/16 requests. A single short, fixed-seed experiment is not a statistical comparison of copying resistance. Patient collectors, different query selection and other model families require further evaluation.", size=9)
    r.p(evidence("defense-comparison.json") + " " + evidence("evaluation.json") + " " + evidence("copy-experiment.json"), size=8.3, color=MUTED)
    r.h2("Recreate measurements in the active virtual environment")
    r.p("<font name='Courier' size='8.4'>python -m scripts.evaluate_chat<br/>python -m scripts.evaluate<br/>python -m scripts.compare_defenses --phase calibrate<br/>python -m scripts.compare_defenses --phase evaluate<br/>python -m scripts.copy_experiment</font>", size=8.5, leading=10, gap=0)
    r.end()

    r.begin("5. Results and conclusions", "The defensible conclusion", "ModelShield is a working, inspectable defence prototype with measurable strengths and explicit limits.")
    r.table(["Supported by this project", "Not established by this project"], [
        ("All five minimum deliverables have working components and saved evidence.", "A perfect detector, universal attack prevention, or a guaranteed competition result."),
        ("Burst patterns can lead to visible alerts and server-enforced withholding.", "That every alert proves malicious intent or every missed alert means safety."),
        ("Approved bulk use can complete, while repetitive probing can override rate credit.", "That approvals remove false positives across a representative customer population."),
        ("Pass usage and transcripts survived an actual restart; keys remained isolated in checks.", "Persistent risk enforcement across restarts or consistent enforcement across multiple workers."),
        ("The classifier copy experiment released fewer labels under protection.", "That the copied classifier became worse, or that an LLM copy was prevented."),
    ], [50, 50], size=9.2)
    r.h2("Next validation priorities")
    r.p("<b>1. Independent traffic.</b> Freeze the detector and evaluate teammate-authored attacks and representative legitimate bulk tasks. Publish per-profile detection, false positives, confidence intervals and legitimate-request latency.")
    r.p("<b>2. Stronger copying evaluation.</b> Repeat multiple seeds and budgets, include collectors that respect delays, compare equivalent customer cost, and evaluate imitation on independent data. Chat requires its own copying study.")
    r.p("<b>3. Deployment hardening.</b> Move risk and atomic reservations into shared state before multiple workers, strengthen customer identity and tenant quotas, add TLS and secret provisioning, and define retention and access policies.")
    r.p("<b>4. Target the demonstrated gaps.</b> Evaluate slow and distributed chat extraction and approval misuse before adding more complexity. Semantic features or longer observation windows are candidates for experiments, not current capabilities.")
    r.note("Closing statement for the jury", "ModelShield turns inference traffic into visible, enforceable evidence. It shows a normal conversation, a suspicious burst, proportionate speed bumps and a bounded customer allowance in one working demonstration. We can show exactly what passed, what failed, and what must improve before production deployment.")
    r.p("Suggested demonstration order: normal chat → paced probes → approved 30-question batch → probing restriction → another key still works → saved evidence and measured limitations. Natural expiry, cooldown and restart checks take longer than a short stage demo; use their saved records when time is limited.", size=9, color=MUTED)
    r.end()

    r.begin("5. Results and conclusions", "References and evidence register", "Primary external sources were checked on 10 September 2026. Project measurements come from local saved artifacts.")
    r.h2("External sources")
    for i, (title, url) in enumerate(SOURCES, 1):
        r.p(f'<b>[{i}]</b> <a href="{url}" color="#126f65">{escape(title)}</a>', size=9, leading=12.3, gap=8)
    r.h2("Local evidence used in this edition")
    purposes = [
        "Chat development quality and failed profiles", "Earlier classifier regression and provenance", "Calibrated classifier baselines and challenges",
        "Label-only classifier-copy experiment", "Real chatbot / dashboard integration", "Real pacing / approval integration",
        "Requirements dashboard, downloads and mobile", "18-feature results and representative samples",
        "Complete saved tour conversations", "Fresh automated test results for this report",
    ]
    r.table(["File under reports/", "Evidence purpose"], list(zip(EVIDENCE_FILES, purposes)), [46, 54], size=8.3)
    r.p("<b>Evidence identity.</b> jury-report-manifest.json records full SHA-256 digests of the source reports, selected implementation files, screenshots and both generated PDFs. These hashes identify this edition's inputs; they do not sign the audit or establish data independence.", size=9)
    r.p("<b>Model identity.</b> Classifier corpus fingerprint: 30691ebf6b7f8aca. Chat weights: Qwen2.5-0.5B-Instruct Q4_K_M, pinned GGUF revision 9217f5db79a29953eb74d5343926648285ec7e67. Runtime: llama.cpp b10894, pinned Windows CPU build (upstream marks this release as a prerelease).", size=8.5)
    r.p("<b>Reading map.</b> Title: p. 1. Objective and jury criteria: pp. 2–3. Proposed solution: pp. 4–7. Validation: pp. 8–12. Results, conclusions and references: pp. 13–16.", size=9, color=MUTED)
    r.end()
    r.save()
    return r


def jury_brief(d, team):
    r = Report(REPORTS / "ModelShield-jury-report.pdf", team, 5, compact=True)
    r.begin("1. Title slide", "ModelShield", "Five-page jury report • GITEX Cyber Defense • " + DATE)
    r.p("Model extraction monitoring<br/>with proportionate access controls.", size=25, leading=33, bold=True, gap=17)
    r.p("A small open-source classifier behind an API, a real local chatbot, and a separate dashboard that explains suspicious traffic and visibly enforces restrictions.", size=12, leading=17, color=MUTED, gap=20)
    r.metrics([("5 / 5", "Deliverables mapped", "Working components"), ("18 / 18", "Demo features passed", "Saved real-model evidence"), ("88 / 88", "Automated tests passed", "Fresh test run")])
    r.pipeline()
    r.picture("jury-overview.png", 205, "Actual Requirements &amp; evidence view. The jury can inspect the API, profiles, signals, alerts and measured quality without reading source code.")
    r.note("Our claim", "We detect demonstrated extraction-like patterns and control further answer release. Our measured limitations remain visible: this prototype does not establish that a model cannot be cloned.")
    r.p("<b>Team:</b> " + escape(team) + " &nbsp; | &nbsp; <b>Companion:</b> ModelShield-detailed-report.pdf (16 pages)", size=8.5)
    r.end()

    r.begin("2. Project objective", "Protect behaviour exposed by an API", "Business fit • 20% | Relevance • 15%")
    r.p("A collector can repeatedly query a private model's public API and train a substitute from the answers. ModelShield is for AI platform teams and security operators who need to spot suspicious collection, explain the evidence and restrict further release. This is an established extraction problem. " + link(2))
    r.p("It brings live request evidence and graduated controls into the workflow currently handled by manual log review and flat per-key limits. It would complement a production API gateway and authentication layer. The buyer/deployer is an intended customer profile; commercial adoption has not been validated.")
    r.table(["Minimum deliverable", "Working implementation / visible proof"], [
        ("Small model + inference API", "POST /predict: open-source TF-IDF / logistic-regression classifier. POST /chat/messages: additional local Qwen conversation demo."),
        ("Normal + extraction traffic", "Seeded traffic scripts, normal and attack profiles, plus editable chatbot batches of up to 30 questions."),
        ("Multiple signals", "Classifier: four signals. Chat: rate, lexical diversity and repetition. Dashboard shows contributions and reasons."),
        ("Real-time alerts / response", "Dashboard red flags, pacing, HTTP 429 throttles and blocks, with rechecks before chat answers are released."),
        ("Measured quality", "Detection and false-positive counts, failed profiles, calibrated classifier baselines and a copy experiment, with separate scopes."),
    ], [30, 70])
    r.p("<b>Why relevant now:</b> OWASP LLM10:2025 includes excessive inference and functional model replication; it recommends limits, bounded queues and monitoring. This prototype applies those controls in a local, inspectable system. " + link(1))
    r.h2("Jury scoring map — no self-awarded scores")
    r.table(["Criterion", "Weight", "Evidence in this five-page report"], [
        ("Fit to brief / business", "20%", "p. 2: deployer, threat and five deliverables"),
        ("Relevance", "15%", "pp. 2–3: current guidance and deployment constraints"),
        ("Working prototype", "25%", "p. 4: reproduction, tests and real-model tour"),
        ("Technical correctness", "25%", "pp. 3–5: scoring, atomic controls and scoped results"),
        ("Innovation", "15%", "p. 3: graduated pacing + monitored bulk approvals"),
    ], [37, 12, 51])
    r.end()

    r.begin("3. Proposed solution", "Speed bumps, with room for real use", "Innovation • 15% | Technical depth • 25%")
    r.pipeline()
    r.p("<b>Models:</b> the classifier uses 2,432 original synthetic training rows (MIT project/corpus). Qwen2.5-0.5B-Instruct Q4_K_M uses a pinned private llama.cpp CPU runtime for real conversation. Model weights are separately Apache-2.0 licensed; setup downloads are checksum-verified. " + link(5) + " " + link(6))
    r.p("<b>Chat score:</b> 45R + 20DAE + 35PAE. R = clip((q−4)/12), with q arrivals in 10 seconds. D is mean lexical cosine distance; P is the larger of duplicate share or adjacent similarity ≥0.80 share. E=min(1,n/8), A=min(1,q/8), with n≤32 recent vectors. The score is a heuristic, not a theft probability.")
    r.table(["Risk", "Server response"], [
        ("&lt;35 / 35 to &lt;40", "Normal / watch; requests remain allowed"),
        ("40 to &lt;50 / 50 to &lt;60", "One-second / three-second pacing"),
        ("60 to &lt;80 / ≥80", "Five-second throttle / thirty-second block, HTTP 429"),
    ], [34, 66])
    r.p("<b>Bulk approval:</b> an operator grants 1–30 requests for 1–60 minutes with 1–2 concurrent generations. Rate credit follows the approved share of arrivals. Diversity and repetition still count; at least 8 inputs with repetition ≥0.65 remove all credit. Atomic reservations consume and persist a slot before inference. Queued and generated answers are rechecked for restriction, expiry and revocation.")
    r.p("<b>Classifier depth:</b> four weighted signals—rate 25, diversity 15, boundary uncertainty 35, sequence variation 25—plus corroborated shared-input correlation across at least three keys. These are separate from chat; chat has no cross-key correlation or confidence signal.")
    r.note("What is innovative here", "The practical combination is proportional friction, a bounded legitimate-customer allowance and inspectable evidence linking each request to its treatment. Prior query-distribution defence and calibrated friction research are acknowledged. These speed bumps are delays, not proof-of-work puzzles. " + link(3) + " " + link(4))
    r.p("<b>Constraints:</b> single-worker Windows prototype; at most two model generations and 32 pending requests. Audit and pass usage persist, while live risk resets on restart. SHA-256 is hashing, not encryption or signed audit. Production needs TLS, managed credentials, shared state and a retention policy.", size=8.8)
    r.end()

    r.begin("4. Solution validation", "Show it running, then inspect the proof", "Working prototype • 25% | Technical correctness • 25%")
    r.note("README launch • Windows, Python 3.13", "<font name='Courier' size='8.7'>python -m venv .venv<br/>.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt<br/>.\\.venv\\Scripts\\python.exe -m scripts.setup_chat<br/>.\\.venv\\Scripts\\python.exe enthi.py</font>")
    r.p("First setup downloads about 491 MB of weights and an 18 MB CPU runtime. Conversation then works locally without a cloud key or GPU. Open <b>http://127.0.0.1:8765/chat</b> beside <b>/dashboard</b>. Ask normal questions, then send a rapid probing batch. Watch the alert reasons and withheld replies.")
    r.table(["Validation evidence", "Saved result and scope"], [
        ("Fresh automated suite", "88/88 tests passed; 0 failures, errors or skips. reports/jury-report-tests.xml."),
        ("Browser checks", "12 chat, 13 protection and 11 requirements checks passed. Real model, auth, mobile, evidence and queue/pacing workflows; overlapping integration checks, not accuracy samples."),
        ("Real alert visibility", "7.014 seconds in one captured chat-check scenario, including UI observation. Not a latency guarantee."),
        ("18-feature tour", "Normal chat/context; input/auth checks; both pacing levels; approved bulk; concurrency; quota; ordinary limits; revoke; expire; probe override; new-chat restriction; isolation; recovery; stop; restart; export."),
    ], [30, 70])
    r.p("<b>Observed tour:</b> 30/30 approved varied questions answered; repeated probing with approval withheld 25/30. Revocation withheld 15/15; natural expiry withheld 29/30. Another key still received answers. Persisted usage stayed 1/3 after an actual restart. Completed tour: 196 requests, 70 answers, 118 withheld, 8 intentional cancellation errors. A restart checkpoint was resumed.")
    r.p("<b>Repeatability:</b> use an unused key or wait at least 60 seconds for a clean comparison. New conversation does not reset key risk. The 31-question browser validation case sends no inference. API schemas also bound input/history and a 16 KiB body; overload and model failures are recorded separately.")
    r.note("The live and saved demo are both accessible", "Use /dashboard#protection for bulk approvals and waiting counters; /dashboard#feature-demo for the saved checklist. Send live traffic from /chat. python -m scripts.demo_chat_features runs the visible tour; it includes an operator restart checkpoint.")
    r.p("<b>Evaluation discipline:</b> session-level detection / false-positive rates; attack labels never enter the detector; calibration precedes challenge evaluation. Earlier inspected classifier data is labelled regression. Synthetic traffic is not independent customer evidence.", size=8.6)
    r.end()

    r.begin("5. Results and conclusions", "Working controls, measured limitations", "Measured quality is reported with scope and denominators; fewer answers do not automatically mean a weaker copy.")
    r.table(["Evaluation", "Attack detection", "False positives"], [
        ("Chat baseline: standard access, no pass", "24/36 = 66.7%", "12/24 = 50.0%"),
        ("New classifier challenges: full detector", "12/30 = 40.0%", "0/18 = 0% observed"),
        ("Same classifier challenges: rate-only", "12/30 = 40.0%", "0/18 = 0% observed"),
        ("Earlier classifier regression (inspected)", "120/120 = 100%", "0/90 = 0% observed"),
    ], [48, 26, 26])
    r.p("The chat baseline kept 12/12 paced normal sessions clear, flagged 12/12 legitimate bulk sessions without approval, and missed 12/12 slow attacks. It is a 60-session virtual-time development check, not an independent holdout or a test of actual pacing. The separate 30/30 approved integration result does not convert that baseline into a 0% false-positive detector.")
    r.p("On the new classifier challenges, full detection did not beat rate-only detection. Median virtual time among detections was 5.1 s for full versus 32 s for rate-only. With only 18 benign sessions, the saved 95% Wilson interval for false positives extends to 17.6%. Locally authored synthetic challenges limit generalisation.")
    r.h2("Did the model become harder to copy?")
    copy_table(d, r)
    r.p("Same seed/order, fresh state; up to 120 attempts or 8 seconds; label-only copier; 90 separate local synthetic evaluation sentences. The majority-label agreement baseline is 66.7%. Protection released 75% fewer labels, but copy agreement increased from 75.6% to 80.0%. This does not establish reduced cloning success, and no LLM-copy experiment is claimed.")
    r.note("Conclusion and next step", "All five deliverables are implemented and demonstrable. The useful contribution is visible request-pattern defence with proportionate pacing and monitored bulk approvals. Next: independent traffic, approval-misuse evaluation, multi-seed copying studies and shared persistent enforcement before production.")
    r.p("<b>Evidence:</b> reports/chat-evaluation.json; defense-comparison.json; evaluation.json; copy-experiment.json; chat-feature-demo.json. Full feature results, formulas, protocols, limits and references appear in the 16-page companion. External references [1]–[6] are clickable beside the claims they support.", size=8, color=MUTED)
    r.end()
    r.save()
    return r


def verify(report):
    pdf = pymupdf.open(report.path)
    if len(pdf) != report.total:
        raise ValueError("Incorrect PDF page count")
    links = 0
    words = 0
    for index, page in enumerate(pdf, 1):
        text = page.get_text()
        if len(text) < 300 or "\ufffd" in text or "\x00" in text:
            raise ValueError(f"Missing or invalid PDF text on page {index}")
        for block in page.get_text("blocks"):
            if block[6] != 0:
                continue
            x0, y0, x1, y1 = block[:4]
            if x0 < 30 or x1 > W - 30 or y0 < 20 or y1 > H - 18:
                raise ValueError(f"Text outside safe margins on page {index}: {block[:4]}")
        words += len(page.get_text("words"))
        links += len(page.get_links())
    if len([entry for entry in pdf.get_toc() if entry[0] == 1]) != 5:
        raise ValueError("Expected five top-level section bookmarks")
    preview = REPORTS / "jury-report-previews"
    preview.mkdir(exist_ok=True)
    for i, page in enumerate(pdf):
        page.get_pixmap(matrix=pymupdf.Matrix(1.15, 1.15)).save(preview / f"{report.path.stem}-{i + 1:02d}.png")
    pdf.close()
    return {"file": report.path.name, "pages": report.total, "words": words, "links": links,
            "section_bookmarks": 5, "layout_checks": "passed", "page_titles": report.page_titles}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", default="ModelShield Team")
    args = parser.parse_args()
    if len(args.team) > 35:
        parser.error("Team name must be at most 35 characters for the report footer.")
    register_fonts()
    data = read_evidence()
    generated = [detailed(data, args.team), jury_brief(data, args.team)]
    checks = [verify(report) for report in generated]
    inputs = [REPORTS / name for name in EVIDENCE_FILES]
    inputs += [ROOT / name for name in [
        "README.md", "modelshield/model.py", "modelshield/engine.py", "modelshield/chat_engine.py",
        "modelshield/bulk.py", "modelshield/api.py", "modelshield/config.py",
        "modelshield/chat.py", "modelshield/chat_runtime.py", "modelshield/requirements.py", "scripts/setup_chat.py",
        "scripts/jury_report.py", "reports/jury-overview.png",
    ]]
    # Include only existing implementation paths; required evidence files were read above.
    inputs = [p for p in inputs if p.exists()]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "edition": DATE, "team": args.team,
        "scope": "Editorial snapshot of implementation and saved evidence; no new accuracy benchmark was run.",
        "checks": checks,
        "inputs": [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": digest(p)} for p in inputs],
        "outputs": [{"path": str(r.path.relative_to(ROOT)).replace("\\", "/"), "sha256": digest(r.path), "bytes": r.path.stat().st_size} for r in generated],
        "external_sources": [{"title": title, "url": url, "accessed": "2026-09-10"} for title, url in SOURCES],
    }
    (REPORTS / "jury-report-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"outputs": manifest["outputs"], "checks": checks}, indent=2))


if __name__ == "__main__":
    main()
