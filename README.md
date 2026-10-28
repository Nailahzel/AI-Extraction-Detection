# ModelShield – AI Model Extraction Attack Detection

### AI-Powered API Security and Behavioral Threat Detection System

ModelShield is a cybersecurity prototype designed to detect and mitigate **AI model extraction attacks**, where attackers repeatedly query an AI model's API to collect responses and attempt to replicate its functionality.

The project combines behavioral analysis, API traffic monitoring, risk scoring, and automated response mechanisms to identify suspicious activity while allowing legitimate users to continue accessing AI services.

## Project Overview

As AI-powered applications become increasingly accessible through APIs, protecting proprietary machine learning models has become an important cybersecurity challenge.

Attackers can systematically send queries to a model, collect its predictions, and use those responses to train a substitute model without accessing the original model's source code or parameters.

Traditional rate limiting may not be sufficient to detect these attacks, particularly when malicious requests are distributed across multiple API keys or sent at a relatively low frequency.

ModelShield explores a behavioral security approach that monitors API requests, identifies suspicious query patterns, and applies appropriate restrictions.

## Objectives

- Detect suspicious AI model extraction attempts.
- Monitor API traffic and identify abnormal querying behavior.
- Differentiate legitimate API usage from potentially malicious activity.
- Identify coordinated suspicious requests across multiple API keys.
- Generate real-time security alerts.
- Implement automated throttling and temporary blocking.
- Provide an interactive monitoring dashboard.
- Evaluate detection performance and false positives.

## Technologies Used

| Technology | Purpose |
|---|---|
| Python | Core application and detection logic |
| FastAPI | REST API development |
| Scikit-learn | Machine learning classification and text feature extraction |
| TF-IDF and Logistic Regression | Protected demonstration classifier |
| SQLite | Security event and audit storage |
| HTML, CSS, JavaScript | Interactive monitoring dashboard |
| Qwen2.5 | Local chatbot demonstration |
| llama.cpp | Local LLM inference runtime |
| Pytest | Automated testing |
| HTTPX | API request simulation and testing |

## Key Features

### 1. AI Model Extraction Detection

Analyzes API query behavior to identify patterns potentially associated with model extraction.

Detection signals include:

- High-frequency API requests.
- Unusual input diversity.
- Repeated low-confidence predictions.
- Small variations between consecutive queries.
- Coordinated activity across multiple API keys.

### 2. Behavioral Risk Scoring

Assigns a heuristic risk score to API clients based on observed request patterns.

Multiple behavioral signals are combined to determine whether additional monitoring or restrictions are necessary.

The score represents suspicious behavior under the configured detection rules rather than a verified probability of model theft.

### 3. Automated Threat Response

Implements progressive security responses based on detected risk, including:

- Continued monitoring of suspicious requests.
- Delayed processing of certain requests.
- API throttling.
- Temporary client blocking.
- HTTP 429 responses when access is restricted.

### 4. Real-Time Monitoring Dashboard

Provides a web-based interface for viewing API activity and investigating potentially suspicious behavior.

The dashboard supports monitoring of request activity, alerts, risk indicators, and security enforcement actions.

### 5. Coordinated Attack Detection

Explores the identification of related suspicious requests distributed across multiple API keys.

This helps address situations where attackers attempt to avoid simple per-client rate limits by spreading requests across different identities.

### 6. Local AI Chatbot Protection

Includes a locally running chatbot to demonstrate behavioral security monitoring for generative AI services.

The chatbot protection system supports request monitoring, progressive restrictions, and controlled bulk-access workflows.

## System Architecture

The system follows a behavioral detection and response workflow:

**Client Request → FastAPI → Behavioral Analysis → Risk Scoring → Security Decision → Model Response or Restriction**

The monitoring layer processes request activity and maintains evidence of suspicious behavior.

Security events and audit records are stored locally for monitoring and investigation.

## Development Challenges and Solutions

### 1. Distinguishing Legitimate and Malicious API Traffic

**Challenge:** Legitimate users may send many API requests, making it difficult to distinguish normal activity from extraction attempts.

**Solution:** Combined multiple behavioral signals rather than relying solely on request frequency. This allows the detector to consider query diversity, prediction confidence, and repeated input modifications.

### 2. Detecting Distributed Extraction Attempts

**Challenge:** Attackers may use several API keys to distribute requests and avoid conventional rate limits.

**Solution:** Implemented correlation mechanisms to identify related activity across multiple clients based on shared request patterns and fingerprints.

### 3. Reducing False Positives

**Challenge:** Aggressive detection thresholds may incorrectly restrict legitimate users.

**Solution:** Introduced configurable thresholds, progressive enforcement, and controlled bulk-access mechanisms. Evaluation also identified remaining limitations involving legitimate high-volume requests.

### 4. Real-Time Monitoring and Response

**Challenge:** Detecting suspicious activity is insufficient if the system cannot respond during an ongoing attack.

**Solution:** Integrated behavioral detection with API enforcement, enabling request throttling, temporary blocking, and security alerts.

### 5. Measuring Detection Effectiveness

**Challenge:** Determining whether the defense identifies attacks without disrupting legitimate users.

**Solution:** Developed simulated attack and benign traffic profiles, automated evaluation scripts, and repeatable tests to measure detection rates and false positives.

## Testing and Evaluation

The project was evaluated using generated legitimate and suspicious API traffic.

| Evaluation Scenario | Detection Rate | False-Positive Rate |
|---|---:|---:|
| Classifier regression tests | 100% (120/120) | 0% (0/90) |
| Additional classifier attack scenarios | 40% (12/30) | 0% (0/18) |
| Chatbot behavioral detection | 66.7% (24/36) | 50% (12/24) |

These results come from controlled synthetic evaluations and should not be interpreted as production-level detection accuracy.

In a separate controlled experiment involving 120 attempted classifier queries, the defense reduced released predictions from 120 to 30, representing a 75% reduction in exposed responses.

However, the experiment did not establish that the resulting substitute model was less accurate.

The project also recorded **88 passing automated tests** during its September 2026 validation.

## Installation and Setup

### Prerequisites

- Windows 64-bit
- Python 3.13
- Git
- pip
- Internet access for initial dependency and optional chatbot model installation

### 1. Clone the Repository

```bash
git clone https://github.com/Nailahzel/AI-Extraction-Detection.git
cd AI-Extraction-Detection
```

### 2. Create a Virtual Environment

```powershell
python -m venv .venv
```

### 3. Install Dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 4. Run the Classifier and Security Dashboard

```powershell
.\.venv\Scripts\python.exe enthi.py
```

### 5. Access the Application

Once the server starts, open:

| Interface | URL |
|---|---|
| Classifier Lab | http://127.0.0.1:8765/classifier-lab |
| Security Dashboard | http://127.0.0.1:8765/dashboard |
| Chatbot | http://127.0.0.1:8765/chat |
| API Documentation | http://127.0.0.1:8765/docs |

### 6. Optional: Enable Local Chatbot Inference

To set up the chatbot model, run:

```powershell
.\.venv\Scripts\python.exe -m scripts.setup_chat
```

The setup process downloads the required local AI model and runtime.

Restart the application afterward if necessary.

## Project Structure

```text
AI-Extraction-Detection/
│
├── modelshield/
│   ├── api.py
│   ├── engine.py
│   ├── model.py
│   ├── chat_engine.py
│   ├── chat_runtime.py
│   ├── storage.py
│   ├── traffic.py
│   └── config.py
│
├── web/
│   ├── index.html
│   ├── chat.html
│   ├── monitor.html
│   ├── app.js
│   └── styles.css
│
├── scripts/
│   ├── simulate.py
│   ├── evaluate.py
│   ├── evaluate_chat.py
│   └── setup_chat.py
│
├── tests/
│
├── reports/
│
├── docs/
│
├── enthi.py
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── .gitignore
├── LICENSE
└── README.md
```

## Current Limitations

- The detection system relies on configurable behavioral heuristics.
- Slow and adaptive extraction attempts can remain difficult to identify.
- Legitimate bulk usage may resemble malicious extraction patterns.
- Synthetic testing does not guarantee equivalent real-world performance.
- Detection scores indicate suspicious patterns rather than confirmed intellectual property theft.
- Production deployment would require additional security controls, scalability improvements, and validation using representative traffic.

## Future Improvements

- Integrate additional machine learning-based anomaly detection.
- Improve detection of slow and adaptive extraction attempts.
- Reduce false positives involving legitimate bulk API usage.
- Introduce centralized security monitoring and SIEM integration.
- Expand behavioral correlation across multiple clients.
- Add more advanced risk analytics and investigation capabilities.
- Evaluate the system against independent real-world traffic datasets.
- Improve scalability for production AI API environments.

## Potential Applications

ModelShield can be explored for:

- AI API security monitoring.
- Machine learning intellectual property protection.
- Detection of automated model extraction attempts.
- Cybersecurity research involving API misuse.
- Behavioral anomaly detection.
- Generative AI application security.

## Project Status

**Working local cybersecurity prototype**

The project includes an inference API, behavioral detection engine, automated response mechanisms, monitoring dashboard, simulated traffic generation, and evaluation scripts.

It is intended for research, experimentation, and demonstration rather than direct production deployment.

## Author

**GitHub:** [Nailahzel](https://github.com/Nailahzel)

**Repository:** [AI-Extraction-Detection](https://github.com/Nailahzel/AI-Extraction-Detection)

## License

This project is distributed under the terms described in the [LICENSE](LICENSE) file.
