ModelShield — AI Model Extraction Detection
Behaviour-based protection for AI inference APIs and local chatbots.

ModelShield is a Python cybersecurity prototype that monitors how clients query an AI model and responds to suspicious patterns that may indicate model-extraction attempts. Attackers can repeatedly query an API, collect its answers and use those examples to imitate the original model. ModelShield combines request-behaviour analysis with explainable risk scores, live monitoring, throttling and temporary blocking.

The project also includes a locally running chatbot demonstration with a separate monitoring interface. The underlying Python package is named modelshield; earlier project documentation also used the name Apocalypse.
Features
- Protected classification API: Local text-sentiment classifier exposed through FastAPI (POST /predict). The sample classifier uses TF-IDF and logistic regression from scikit-learn.
- Multi-signal detection: Monitors unusual query rates, input diversity, low-confidence predictions and small changes across consecutive queries.
- Coordinated activity: Correlates suspicious inputs across multiple API keys to help surface distributed probing.
- Adaptive responses: Records alerts, withholds predictions using HTTP 429, and applies temporary throttles or blocks according to a configurable policy.
- Chatbot protection: Separate behaviour analysis for repeated or high-volume chatbot prompts, including progressive waiting periods and restrictions.
- Controlled bulk access: Time-limited, quota-limited bulk passes that an operator can approve and revoke; behavioural monitoring remains active.
- Monitoring dashboard: Browser views for traffic, risk explanations, alerts, restrictions and investigation evidence.
- Auditing and testing: SQLite-backed local audit records, synthetic traffic generators, evaluation scripts and automated tests.
Technology Stack
Area	Technologies
Backend/API	Python, FastAPI, Uvicorn
Classification	scikit-learn, TF-IDF, logistic regression
Chatbot (optional)	Qwen2.5-0.5B-Instruct GGUF, llama.cpp CPU runtime
Monitoring and storage	Custom behaviour-scoring logic, SQLite
Frontend	HTML, CSS, JavaScript
Testing and evaluation	pytest, HTTPX, Playwright, custom traffic simulation


How It Works
1. An API client sends a prediction request or chatbot prompt.
2. ModelShield tracks recent request activity for that API key or client.
3. Detection rules calculate a risk score from patterns such as speed, repetition, diversity and boundary probing.
4. Low-risk requests proceed; suspicious requests may be delayed, throttled or temporarily blocked.
5. The operator dashboard shows the decision, supporting signals and audit history.
The risk score is an engineered heuristic, not a probability that a model has been stolen. Classification sentiment is separate from the question of whether the client is behaving suspiciously.
Local Setup
Validated environment reported in the project: Windows x64, Python 3.13. The full optional chatbot setup has not been validated on other operating systems.

Open PowerShell in the project folder:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe enthi.py
This starts the classifier lab and API without downloading the optional chatbot model. Open:
- Classifier lab: http://127.0.0.1:8765/classifier-lab
- Monitoring dashboard: http://127.0.0.1:8765/dashboard
- API documentation: http://127.0.0.1:8765/docs
To enable the local chatbot, stop the server and run:
.\.venv\Scripts\python.exe -m scripts.setup_chat
.\.venv\Scripts\python.exe enthi.py
Then visit http://127.0.0.1:8765/chat. The chatbot setup downloads approximately 510 MB of model/runtime files; internet access is needed for the initial download. The runtime and model weights are not kept in this Git repository. Inference runs locally after setup.

If port 8765 is busy, use python enthi.py --port 8766 (using the virtual environment's Python) and change the URLs accordingly.
Example API Request
Run in a second PowerShell window while the server is active:
Invoke-RestMethod -Uri http://127.0.0.1:8765/predict `
  -Method Post -ContentType 'application/json' `
  -Headers @{ 'X-API-Key' = 'normal-01' } `
  -Body '{"text":"The product was surprisingly good."}'
Demo API keys are for local testing only. The default demo must not be exposed to the public internet.
Testing and Evaluation
The project includes repeatable synthetic traffic scenarios, including normal use, rapid bursts, boundary probing, slow querying and distributed probing.
Recorded evaluation	Attack sessions detected	Benign sessions incorrectly restricted
Classifier synthetic regression	120 / 120 (100%)	0 / 90 (0%)
Additional classifier challenge	12 / 30 (40%)	0 / 18 (0%)
Chat synthetic evaluation without bulk passes	24 / 36 (66.7%)	12 / 24 (50%)


These are project-generated test results, not production performance guarantees. In particular, the chat evaluation flagged legitimate unapproved bulk activity and missed slow attacks. The classifier challenge also exposed gaps beyond the main regression scenarios.

A fixed HTTP collection experiment reduced released predictions from 120 to 30 requests (75% fewer answers). This does not establish that the resulting copied model is less accurate; the experiment's copy-model agreement did not improve under protection.

The project records 88 automated tests passing as of September 11, 2026. To run the tests locally:
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
To run evaluation scripts:
.\.venv\Scripts\python.exe -m scripts.evaluate --no-write-policy --output reports/local-check
.\.venv\Scripts\python.exe -m scripts.evaluate_chat
Detailed machine-generated results are included in the reports/ directory.
Key Development Challenges
Detecting extraction without blocking normal users
High request volume alone does not prove malicious intent. ModelShield combines several behavioural signals, maintains recent activity windows and applies graded restrictions rather than treating every busy client as an attacker.
Recognizing distributed and low-and-slow activity
An attacker may spread requests across keys or avoid large bursts. The classifier detector correlates shared fingerprints across keys, but the evaluations show that slower strategies remain difficult to detect reliably.
Keeping the system transparent and testable
Risk calculations and response decisions are surfaced in monitoring views. Repeatable traffic profiles, automated tests and saved evaluation reports help distinguish observed behaviour from unverified security claims.
Supporting legitimate batch workloads
Bulk customers can resemble attackers. The chatbot workflow includes operator-approved, limited passes that preserve monitoring and can be revoked instead of globally disabling controls.
Project Structure
.
├── enthi.py                 # Application launcher
├── modelshield/             # APIs, classifiers, detection, policy, audit and chat logic
├── web/                     # Chat, classifier lab and monitoring interfaces
├── scripts/                 # Setup, traffic generation, evaluation and utilities
├── tests/                   # Automated tests
├── reports/                 # Evaluation outputs and evidence
├── docs/                    # Demonstration guidance
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # Test/development dependencies
├── .gitignore
└── LICENSE
Local virtual environments, downloaded model weights, runtime databases and other generated artifacts are excluded by .gitignore.
Limitations and Future Work
ModelShield is a local research prototype, not a production-ready API security gateway. Its main limitations include reliance on synthetic testing, missed slow extraction attempts, false positives for some bulk traffic, and in-memory risk state that is not shared across multiple server workers. For production use, it would need representative customer traffic evaluation, stronger identity and access controls, shared state, TLS, secret management, operational monitoring and more comprehensive adversarial testing.

Potential future improvements include learning per-customer baselines, broader cross-key correlation, more realistic adversarial evaluations and carefully measured false-positive reductions.
