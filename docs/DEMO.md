# Demo notes

Use these as talking points. Run the demo yourself and explain what is on screen in your own words.

## Present the conversational demo

Start at **http://127.0.0.1:8765/dashboard**. Show requests, released answers, withheld answers and restricted clients. Open a client or red flag to inspect its signals. **Chatbot demo** contains saved request examples; measured quality is recorded in `reports/`.

Open **Speed bumps & bulk passes** to approve a workload and watch waiting time or pass usage. Send questions from the chatbot's **Batch questions** tab: keep eight lines of the probing example for a speed bump, send 30 varied questions with a pass, or send all 30 probing questions to trigger a restriction. **Revoke** invalidates a pass for queued and future answers. Use separate clients or wait 60 seconds after their last request.

1. Run `.\.venv\Scripts\python.exe enthi.py`. If the model is not installed, run `.\.venv\Scripts\python.exe -m scripts.setup_chat` once first.
2. Put `http://127.0.0.1:8765/chat` and `http://127.0.0.1:8765/dashboard` side by side. Chat does not need an operator token. Refresh the dashboard after a server restart to renew local demo access.
3. With **Normal user**, introduce yourself and ask a follow-up. Show a real conversational reply and the corresponding question/result in monitoring. The small model may make mistakes.
4. Choose **Test client → Batch questions → Fill a probing example → Send batch**. Or paste your own 10–30 questions, one per line.
5. Show the red flag and HTTP 429 pauses. Click the alert: explain the rate and repetition contributions. The request is checked before generation, while queued, and before an answer is released. A new conversation does not reset the restriction.
6. Switch to **Another normal user** and ask a question. It should still receive an answer. Export the monitoring evidence if the judges want the recorded requests and decisions.
7. Explain the limits: this flags suspicious collection patterns; it does not prove theft or guarantee stopping a clone. Paced ordinary conversations passed the development scenarios, but legitimate bursts also triggered, and slow probing was missed. Show `reports/chat-evaluation.json` and `reports/chat-check.json` separately.

A useful opening: “The chat is the service a customer uses. This other page is what its operator sees. When one key starts collecting answers unusually quickly and systematically, the API pauses it and records why.”

For another clean run, leave the test key idle for at least 60 seconds. The classifier lab's reset does not clear chat restrictions. The two systems have separate audits and policies.

## Optional classifier experiments

The remaining notes describe the original classifier lab at **http://127.0.0.1:8765/classifier-lab**. Its four signals, campaigns, and copying measurements apply to the sentiment model, not the chatbot. Use it to discuss reproducible model-copying experiments without claiming those numbers validate LLM protection.

## Before presenting

1. Plug in the laptop and start `.\.venv\Scripts\python.exe enthi.py`.
2. Open `http://127.0.0.1:8765/classifier-lab`. Check that it says **System online**.
3. In Attack lab, reset the session. In Defense policy, check that **Enforcing** is on.
4. Keep `reports/ModelShield-submission.pdf` and `reports/evaluation.json` available.
5. Run through the demo once, then reset. The installed app works without Wi-Fi.

## A short walkthrough

**Start with the problem.**

“Someone with a valid API key can collect a model's answers and use them to train a copy. We're looking for patterns in those requests. The sentiment model here is a small example of the API we want to protect.”

Click **Run live demo**. The first five seconds contain ordinary traffic; extraction probes follow.

**Show the change in behavior.**

Point to `attacker-01`, its rising score, and the Detection feed. Wait until answers are withheld before describing enforcement. A 429 response means the API withheld the prediction. It does not mean the server crashed.

**Open the explanation.**

Click the suspicious key. Explain two visible signals, such as the burst rate and uncertain-answer share. The four signals are rate, input diversity, uncertain answers, and systematic changes between inputs. A burst alone gives at most 25 points; throttling starts at 55.

Check a normal key in Live traffic. It should still be receiving answers. The penalty belongs to the suspicious key.

**Show several keys working together.**

Stop the simulation, reset, and run **Coordinated campaign** from Attack lab. Open Campaigns when the group appears. The detector links repeated inputs across at least three keys and requires uncertainty and enough observations as supporting evidence. Key names do not determine the result.

**Finish with the measured results.**

Open Validation. Start with the copying experiment and defense comparison. Show actual released-answer counts, copy agreement, and legitimate-request success. The initial experiment withheld many answers but did not lower copy agreement; the new challenge comparison found no overall detection advantage over the calibrated rate limiter. Explain those limits directly.

The original regression report below those experiments detected 120 of 120 simulated attack sessions and flagged none of the 90 benign sessions. Median detection was 3.86 seconds. Slow probing took 13.4 seconds median, so that profile missed the ten-second target. This narrower result does not override failures in the newer challenge set.

Explain that v2 reuses the original test set as a regression check. It is not a fresh unseen evaluation or evidence of real-world accuracy. Allow about two minutes for the full walkthrough, or show one scenario if time is short.

## Let someone try it

For a batch test, open **Attack lab → Prediction playground → Multiple inputs**. Paste 10–30 inputs, one per line, choose `probe-01`, and click **Send batch**. The results show actual responses, risk readings, new alerts, and reasons on the same page. Expand a row's **Response details** to inspect its JSON.

For an easy comparison, reset and send **15 ordinary inputs**, then reset and send **30 probing inputs**, keeping the same key and Rapid timing. The example buttons only fill the box; the person presenting still clicks **Send batch**. Explain what the results actually show. If a key was already penalized, the summary says so. Observe mode can raise alerts without withholding answers.

Open **Attack lab → Prediction playground**. Choose `probe-01`, enter one sentence, and click **Analyze text**. Replace the sentence and click again to send another request. Keep Overview in a second tab so both the response and the risk are easy to see.

For a probing example, change “somewhat” to “barely,” “almost,” and “possibly” in “The movie was somewhat good yet terrible.” Try several related variations within a minute. A single negative review is ordinary traffic, and repeating an ordinary sentence is not guaranteed to trigger enforcement.

## Questions to be ready for

| Question | What to explain |
|---|---|
| Why use sentiment? | It gives us a small local model with a label and confidence. The security part watches requests to it. It could protect another classifier after recalibration. |
| Why not just rate-limit? | Busy legitimate clients exist. Our batch scenario checks that high volume alone does not trigger a penalty. Other signals must contribute. |
| Is similarity semantic? | No. It compares hashed words and word pairs. Paraphrases and other languages need separate work. |
| Are the tests independent? | Calibration uses different seeds and subjects from evaluation. The current evaluation set was already inspected for v1 and is reused for v2 regression. Both use related synthetic generators. |
| Can it miss an attacker? | Yes. Slow queries, natural-looking inputs, and campaigns with no shared probes can escape these rules. Shared legitimate automation can also look suspicious. |
| How much of the model was copied? | We train a second classifier on released labels and measure agreement on separate inputs. Agreement is not a percentage stolen. In the first experiment, protection reduced released answers but did not lower agreement. |
| What survives a restart? | SQLite audit records survive. Current windows, penalties, and counters reset. Multiple server workers would need shared state. |
| Who might use it? | An organization serving a proprietary classifier through an API. It would need validation against its own model and normal customer traffic before deployment. |

## If something goes wrong

- **Disconnected:** check the server terminal. If it stopped, start `enthi.py` again and refresh the browser.
- **Port already in use:** use `enthi.py --port 8766` and open that address.
- **An old penalty affects a test:** stop the simulation and reset in Attack lab. This clears local demo history.
- **The API documentation does not load offline:** use the playground or `/openapi.json`. The optional Swagger page uses CDN scripts.
- **A scenario behaves differently:** inspect the alert and policy instead of promising a particular score. Use the saved report to discuss the measured run separately.

Each team member should be able to explain the path from an API request to a prediction, risk decision, and response. Divide the presentation by what each person has actually practiced.

For an incident demonstration, click the alert itself. Show its recorded score, threshold, signal contributions, and timestamp, then export the record. A key's live score can change later; the stored explanation stays tied to that decision while its audit row is retained.

For team preparation: one member runs integration and manual requests, one owns the copying experiment, one validates the calibrated comparisons, and one rehearses incident investigation and customer impact. After settings are frozen, a teammate should author the separate challenge file described in README. The bundled challenges were authored within this project and must not be called an independent evaluation.
