# ModelShield measured validation

Generated 2026-09-10T14:06:23+00:00. Synthetic benchmark only.

- Detection: 120/120 (100.0%).
- False positives: 0/90 (0.0%).
- Median detection: 3.864 seconds; P95: 13.936 seconds (detected attacks only).
- Frozen throttle threshold: 55.

| Profile | Truth | Sessions | Flagged | Median detection (s) |
|---|---|---:|---:|---:|
| normal | Benign | 30 | 0 | - |
| batch | Benign | 30 | 0 | - |
| neutral | Benign | 30 | 0 | - |
| burst | Attack | 30 | 30 | 1.504 |
| boundary | Attack | 30 | 30 | 0.882 |
| slow | Attack | 30 | 30 | 13.402 |
| distributed | Attack | 30 | 30 | 6.241 |

Replay 45-second sessions on a virtual clock using the production detector in observe mode. Detection is any score at or above the frozen throttle threshold. The 25/15/35/25 signal weights are fixed; only the throttle threshold is selected on calibration traffic. Final test seeds and subject words are disjoint from calibration and the development pilot (seeds 1000-1019), which revealed invalid boundary probes. Final test labels never enter the detector. A campaign is one attack session, not three independent sessions. Detection timing is simulated arrival time, not a hardware latency measurement. The v2 sentiment update reuses the previously inspected v1 holdout as a fixed regression suite; these are not new unseen test sessions. Sarcasm regression examples are separate from this extraction-traffic benchmark.

Synthetic traffic is narrower than real-world API behavior; shared generator families can overestimate generalization.

Low-and-slow attacks may take longer than the ten-second demonstration target or evade detection.

The local sentiment model is trained on original synthetic examples; its probabilities are not calibrated on real customer data.

Cross-key correlation requires overlapping normalized inputs and can miss non-overlapping campaigns or flag similar benign automation.

In-memory windows and penalties reset on server restart; SQLite audit records persist. This single-process prototype is not a distributed production gateway.
