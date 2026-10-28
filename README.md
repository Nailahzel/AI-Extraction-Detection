<<<<<<< HEAD
# Apocalypse

**A local prototype that detects suspicious attempts to collect an AI model's answers.**  
GITEX Cyber Defense hackathon

An attacker does not need a model's source code to imitate it. They can query its API repeatedly and train a copy on the answers. Apocalypse watches the request pattern, shows the operator why it looks suspicious, and limits further answers.

The project has two demonstrations:

- **Classifier lab:** a small open-source text classifier, normal and extraction traffic, a four-signal detector, and measured detection results. This implements the original brief.
- **Chatbot and monitor:** a real local chatbot with a separate dashboard, progressive speed bumps, and operator-approved bulk passes. This uses its own detector and has separate measurements.

The positive/negative classifier is the model being protected. Positive or negative wording is **not** what makes a user suspicious. An alert indicates suspicious querying behaviour; it does not prove that a model has been stolen.

## 1. Problem and business fit — 20%

The intended deployer is a company serving a proprietary classifier or chatbot through an API, such as a document-processing provider or AI software vendor. Its security or platform team needs to distinguish ordinary use from systematic answer collection without blocking every busy customer.

Apocalypse adds behavioural checks and an operator audit trail to basic request limits. It reduces reliance on manual log inspection and a single request cap for everyone. It is a prototype of a protective layer in front of inference, not a replacement for authentication or an existing API gateway.

| Required deliverable | Implementation | Where the jury can check it |
|---|---|---|
| Small open-source model behind an inference API | Local TF-IDF + logistic-regression classifier; `POST /predict` | Classifier lab → Attack lab → Prediction playground |
| Normal and extraction traffic | Seeded normal, burst, boundary-probing, slow and distributed profiles | Run live demo, or the traffic commands below |
| At least 2–3 detection signals | Rate, diversity, low-confidence share and consecutive-query changes | Select a client in the classifier lab |
| Real-time alerts and response | Live alerts, signal explanations, HTTP 429 and temporary restrictions | Classifier live traffic; chatbot monitor |
| Measured detection and false-positive rates | Reproducible session evaluations, with counts and limitations | Results in section 5 and the linked JSON reports |

## 2. Run the prototype — 25%

### First-time setup

Use **Windows x64 and Python 3.13** for the complete demo. The project was checked with Python 3.13.13. Extract the project ZIP, open PowerShell **inside the extracted project folder**, and run:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m scripts.setup_chat
.\.venv\Scripts\python.exe enthi.py
```

Leave that terminal running. No environment activation is needed because the commands name its Python executable directly.

The chat installer downloads approximately 510 MB of model weights and a CPU runtime from the official Qwen and llama.cpp repositories. Downloads are pinned and SHA-256 checked. Installation needs internet; inference then runs locally without a GPU, cloud account or API credits. The weights and runtime are excluded from the submission ZIP, so run the installer on each new computer.

**For the minimum classifier demo only, skip `scripts.setup_chat`.** Its model trains from the included corpus at startup and needs no separate model download. The bundled chat installer supports Windows x64; the complete workflow has not been validated on other operating systems.

| Open in your browser | Purpose |
|---|---|
| [Classifier lab](http://127.0.0.1:8765/classifier-lab) | Original brief: inference, generated traffic, detection and validation |
| [Chatbot](http://127.0.0.1:8765/chat) | Enter conversations or up to 30 batch questions |
| [Monitoring dashboard](http://127.0.0.1:8765/dashboard) | Watch chatbot traffic, restrictions, waiting and bulk passes |

These are public demo identities on a loopback-only service. Opening the dashboard grants local operator access. If an old tab asks for operator access after a restart, refresh `/dashboard`. Chat does not need an operator credential.

For later runs, use only `.\.venv\Scripts\python.exe enthi.py`. Stop with `Ctrl+C`. If port 8765 is occupied, add `--port 8766` and use 8766 in browser links and API commands.

### Jury walkthrough: the required scenario

1. Open **Classifier lab → Attack lab → Reset demo**, and confirm. This clears classifier demo history. Keep **Defense policy → Enforcing** enabled.
2. In **Overview**, click **Run live demo**. During the first five seconds, normal clients receive predictions without restrictions.
3. Extraction traffic then starts while normal traffic continues. Select `attacker-01` to inspect its risk, reasons and signal contributions. Suspicious requests should produce alerts and withheld responses within seconds.
4. Open **Live traffic**. Show HTTP **200** for released predictions and **429** for withheld ones; normal clients should still receive answers.
5. After the run finishes, reset and repeat. For another pattern, run **Coordinated campaign** from Attack lab, then inspect **Campaigns** for linked activity across three keys.

For a direct API check, run this in a **second PowerShell terminal** in the project folder:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/predict `
  -Method Post -ContentType 'application/json' `
  -Headers @{ 'X-API-Key' = 'normal-01' } `
  -Body '{"text":"The product was surprisingly good."}'
```

It returns a label and confidence estimate. The API explorer at `/docs` needs internet for its interface assets; `/openapi.json` provides the schema locally.

The standalone generator sends real HTTP requests too. Reset the classifier demo before this comparison, keep its dashboard open, and run:

```powershell
.\.venv\Scripts\python.exe -m scripts.simulate normal --duration 10 --seed 42
.\.venv\Scripts\python.exe -m scripts.simulate boundary --duration 10 --seed 42
```

The first command should leave normal traffic unflagged; the second should trigger detection. Each prints response counts. For another port, append `--url http://127.0.0.1:8766`. **Run live demo** is the combined scenario with both profiles alongside each other.

### Jury walkthrough: chatbot protection and bulk access

Open the chatbot and monitoring dashboard side by side. Use a fresh client for each case; otherwise stop sending requests for at least 60 seconds before repeating.

| Step | Do this yourself | Inspect in the dashboard |
|---|---|---|
| Ordinary conversation | Select **Normal user**. Ask “Why does a metal spoon feel colder than a wooden one?” Wait for the reply. | A recorded question and answer without restriction |
| Speed bump | Select **Test client** → **Batch questions** → **Fill a probing example**. Keep the first **eight** lines and send. | **Speed bumps & bulk passes**: delayed requests and measured waiting |
| Stronger restriction | Select **Probing demo**, fill the probing example and send all **30** lines. | Red flags and withheld answers; select an alert to inspect its evidence |
| Client isolation | Select **Another normal user** and ask one ordinary question. | This different key can still receive a reply |
| Approved bulk work | In **Speed bumps & bulk passes**, approve **batch-01**, 30 requests, 10 minutes. In chat, select **Bulk customer** → **Batch questions** → **Fill varied questions** → **Send batch**. Under **Batch options**, keep **Use approved allowance** checked. | Usage advances toward **30 / 30**; the fixed varied batch should complete without a behavioural restriction |
| Quota and revocation | After the approved batch, try one more batch question. Then click **Revoke** on its pass in the dashboard. | The exhausted allowance rejects the extra request; revocation updates its status |

Before repeating bulk work, revoke any existing pass, wait for earlier traffic to age out, then approve a new one. Approval does not clear a restriction. **New conversation** clears chat context, not protection history. Classifier reset affects only classifier records.

The monitor's **Chatbot demo** tab contains saved examples. Use **Live monitoring** and **Speed bumps & bulk passes** for the requests you send now. The first answer may take longer while the local model loads; replies are limited to 160 generated tokens.

## 3. Design and relevance — 15%

API-based copying is an existing problem. Conversational services add longer, more expensive generation and queues, making it useful to control incoming requests and outgoing answers. OWASP's **LLM10:2025 Unbounded Consumption** includes model replication and recommends monitoring, quotas and throttling. Our design applies those controls to a small, inspectable local prototype. [OWASP reference](https://genai.owasp.org/llmrisk/llm102025-unbounded-consumption/)

**Stack:** FastAPI for HTTP, scikit-learn for classification and feature vectors, SQLite for audit records, and plain HTML/CSS/JavaScript for the interfaces. Chat uses [Qwen2.5-0.5B-Instruct GGUF](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) through a pinned [llama.cpp CPU runtime](https://github.com/ggml-org/llama.cpp/releases/tag/b10894).

### What the detectors measure

Both use bounded, 60-second histories **per API key**. Risk is a weighted heuristic score, not a probability of theft. Neither detector reads the generator's normal/attack labels or decides risk from a client's name.

| Classifier signal | Logic | Maximum contribution |
|---|---|---:|
| Query rate | Short burst compared with a bounded adaptive rate baseline | 25 points |
| Input diversity | Mean cosine distance between recent hashed text vectors | 15 points |
| Low-confidence share | Fraction of predictions below 0.65 confidence, indicating possible boundary probes | 35 points |
| Consecutive-query changes | Repeated small changes between adjacent, distinct inputs | 25 points |

Evidence grows gradually with the number of observations. Rate alone cannot reach the classifier's 55-point throttle threshold. At 55 points it can throttle for two seconds; at 80 it can block for 30 seconds. Shared input fingerprints and uncertain predictions can also link a campaign across at least three keys.

The **chat detector is separate**: rate contributes up to 45 points, character-gram diversity 20, and repetition or close variations 35. It does not assign an invented confidence score to generated replies.

| Chat risk | Response |
|---|---|
| Below 35 | Normal access |
| 35–39.9 | Watch |
| 40–49.9 | Space generation starts by 1 second |
| 50–59.9 | Space generation starts by 3 seconds |
| 60–79.9 | Throttle for 5 seconds |
| 80 or more | Block for 30 seconds |

For classification, an existing penalty is checked first; an allowed inference supplies the confidence needed for scoring, after which the answer may be withheld. Chat requests are scored before generation and checked again while queued and before answer release. Denial returns HTTP 429 with `Retry-After`, rather than the model's answer.

## 4. Innovation — 15%

**Progressive speed bumps:** suspicious chatbot requests first wait between generation starts. Stronger evidence leads to throttling or temporary blocking. The dashboard shows actual waiting separately from model generation time, so the intervention is visible beyond a red label.

**Operator-approved bulk passes:** a known customer can receive 1–30 requests for 1–60 minutes, with at most two simultaneous generations. Approved requests receive rate credit, while diversity and repetition checks remain active. Repeated probing can remove that credit. The operator can inspect usage and revoke the pass.

Pass reservations are persisted before inference; used slots, expiry and revocation survive restart. A reserved slot still counts if its request later fails or is withheld. Approval is a bounded customer workflow, not a switch that disables monitoring. It does not prove intent: a malicious approved customer can still collect answers within its allowance.

## 5. Correctness and measured results — 25%

**Detection rate** = detected attack sessions ÷ all attack sessions.  
**False-positive rate** = flagged benign sessions ÷ all benign sessions.

Here, detection means reaching the restriction threshold, not merely entering “watch” or receiving a speed bump. These results come from generated traffic, not customer deployments.

| Evaluation | Attack detection | Benign false positives | Scope |
|---|---:|---:|---|
| [Classifier regression](reports/evaluation.json) | **120/120 · 100%** | **0/90 · 0%** | Established synthetic regression suite |
| [Classifier challenge: full defence](reports/defense-comparison.json) | **12/30 · 40%** | **0/18 · 0%** | Additional locally generated attack families |
| [Chat standard access, without passes](reports/chat-evaluation.json) | **24/36 · 66.7%** | **12/24 · 50%** | Synthetic bursts, ordinary conversations and unapproved bulk work |

Classifier regression median detection time was **3.864 seconds of simulated arrival time**, not wall-clock inference latency. Its 95% Wilson intervals were 96.9–100% for detection and 0–4.09% for false positives: observing zero false positives does not establish a zero real-world rate.

In the classifier challenge, the calibrated rate-only baseline also detected 12/30 attacks with 0/18 false positives. Full defence detected flagged attacks sooner (median 5.1 versus 32 simulated seconds), but did **not** improve detection rate. In the chat evaluation, all 12 ordinary conversations stayed clear, all 12 legitimate bulk sessions were flagged, and all 12 slow attacks were missed. That evaluation excludes bulk passes and actual LLM generation.

### Does the defence make copying harder?

In the [HTTP copying experiment](reports/copy-experiment.json), protection reduced released classifier answers from **120 to 30** in a fixed 120-attempt comparison: a **75% reduction**. However, the copy's agreement with the protected model increased from **75.6% to 80.0%** on the small evaluation. We demonstrate restricted answer collection, **not a proven reduction in copying quality**. Agreement is neither the percentage of a model stolen nor accuracy on a real task.

### Measurement discipline

- The classifier trains on **2,432 original synthetic examples**. Its probabilities are uncalibrated estimates, not guarantees of correctness.
- The throttle threshold is selected on **84 calibration sessions**. The 210-session regression uses different seeds and subject words; labels never enter the detector. That suite was inspected during earlier development, so it is not a new independent holdout.
- Challenge protocols are frozen after calibration. The bundled challenge still comes from this project, not an independent team. Copy training uses collected API labels; copy scoring uses a separate evaluation set.
- Synthetic detector timing uses a virtual clock. Browser integration separately checks real responses, generation, waiting and dashboard behaviour; those fixed scenarios are not accuracy estimates.
- SHA-256 supports artifact integrity and input fingerprints, not encryption or anonymity. Chat audits store questions and answers locally. No new cryptographic scheme is claimed.

### Reproduce checks

**Checked on 11 September 2026:** all **88 automated tests passed**. Two consecutive HTTP demo runs each left normal traffic clear and produced alerts and HTTP 429 responses for boundary probes. Startup, all three pages, invalid credentials and malformed inputs were also checked. Re-running the classifier evaluation reproduced the reported 120/120 detection and 0/90 false positives.

Run these from a second terminal. They do not require the demo server. Classifier evaluation writes a separate folder and leaves the deployed policy unchanged; chat evaluation regenerates its saved JSON report.

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate --no-write-policy --output reports/jury-check
.\.venv\Scripts\python.exe -m scripts.evaluate_chat
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

To rerun the optional baseline comparison and copying experiment in a separate output folder:

```powershell
.\.venv\Scripts\python.exe -m scripts.compare_defenses --output reports/jury-check
.\.venv\Scripts\python.exe -m scripts.copy_experiment --output reports/jury-check
```

For real-model browser checks, install Microsoft Edge and complete chat setup, then run:

```powershell
.\.venv\Scripts\python.exe -m scripts.chat_check
.\.venv\Scripts\python.exe -m scripts.protection_check
```

These start isolated temporary servers and databases; they update their reports without resetting the live demo. Saved results cover [chat and access control](reports/chat-check.json) and [speed bumps, usage and revocation](reports/protection-check.json). A successful fixed 30-question approved batch demonstrates the workflow, not a general false-positive rate.

### Repeat runs and unexpected input

| Case | Expected behaviour |
|---|---|
| Second classifier demonstration | Reset in Attack lab, then run again |
| Second chatbot demonstration | Wait at least 60 seconds after the last request; resolve any exhausted, expired or revoked pass before retrying |
| Empty, malformed or overlong prediction input | HTTP 422; no successful inference response |
| Missing or incorrect client key | HTTP 401 |
| More than 30 chat batch lines | Browser validation stops submission |
| Missing chat runtime/model | Chat reports unavailability; run `scripts.setup_chat` and retry |
| Restart | Audit records and pass usage persist; in-memory risk windows and penalties restart |

The main limits are slow extraction, unknown real-world false-positive rates, and legitimate unapproved bulk traffic resembling an attack. This is a single-process prototype: risk state is not shared across workers, and chat restrictions follow a key rather than an account with several keys. Deployment would also need customer validation, shared state, TLS and private credentials. Non-demo configuration uses `MODELSHIELD_DEMO=0`, a JSON `MODELSHIELD_API_KEYS` map and `MODELSHIELD_ADMIN_TOKEN` of at least 32 characters; see [settings](modelshield/config.py).

## Project map

| Location | Responsibility |
|---|---|
| [enthi.py](enthi.py) | Start the API and serve all three interfaces |
| [modelshield/model.py](modelshield/model.py), [engine.py](modelshield/engine.py) | Protected classifier and extraction detector |
| [modelshield/chat_engine.py](modelshield/chat_engine.py), [chat_runtime.py](modelshield/chat_runtime.py) | Chat risk, response policy and local model runtime |
| [modelshield/api.py](modelshield/api.py) | HTTP routes, authentication and orchestration |
| [web/](web/) | Chatbot, monitoring dashboard and classifier lab |
| [scripts/](scripts/) and [tests/](tests/) | Traffic generation, evaluation, copying experiments and checks |
| [reports/](reports/) | Measured results and the classifier lab's downloadable submission PDF |

### Files included on GitHub

The repository contains the application, tests, setup and evaluation scripts, documentation, and saved results used by the dashboards. `.gitignore` excludes local environments, model downloads, live databases, screenshots, slide exports and temporary files. Each new computer installs its own dependencies and chat model using the setup commands above. `ModelShield-submission.pdf` is retained because the classifier lab serves it as a download.

Apocalypse was previously named ModelShield. Package names, environment variables and older report filenames retain that name for compatibility. Project code and the original classifier corpus use the [MIT licence](LICENSE); the model, runtime and dependencies retain their upstream licences.
=======
# AI-Extraction-Detection
>>>>>>> origin/main
