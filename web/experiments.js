"use strict";

// Historical evidence has its own view; live polling never rewrites it.
(() => {
  let selected = null;
  async function showIncident(id) {
    selected = id;
    $("#incident-content").textContent = "Loading recorded evidence…";
    if (!$("#incident-dialog").open) $("#incident-dialog").showModal();
    try {
      const record = await (
        await api(`/api/incidents/${encodeURIComponent(id)}`)
      ).json();
      if (selected !== id) return;
      const p = record.policy,
        s = record.signals;
      const values = {
        rate: `${s.burst_rpm || 0}/min burst; baseline ${s.baseline_rpm || 36}/min`,
        diversity: Number(s.diversity || 0).toFixed(3),
        boundary: percent(s.boundary, 1),
        sequence: percent(s.sequence, 1),
      };
      $("#incident-content").innerHTML =
        `<h2>${escapeHTML(record.client_id)} · ${escapeHTML(record.action)}</h2><p class="incident-id">${escapeHTML(record.incident_id)}</p><p>${escapeHTML(new Date(record.at * 1000).toLocaleString())} · ${record.enforcing ? "Enforcing" : "Observing"}</p><div class="detail-risk"><strong>${record.risk.toFixed(1)}</strong><span>/ 100 recorded risk</span></div><p>Policy ${escapeHTML(p.version)} · alert threshold ${p.throttle_threshold} · block threshold ${p.block_threshold}</p><p>${s.evidence || 0} observations in the ${p.window_seconds}-second window.</p><h3>Why this decision?</h3><ul class="reasons-list">${record.reasons.map((r) => `<li>${escapeHTML(r)}</li>`).join("")}</ul><h3>Signals at the time</h3>${Object.entries(
          signals,
        )
          .map(
            ([key, [label]]) =>
              `<div class="weight-row"><div><span>${label}</span><strong>${Number(s.contributions?.[key] || 0).toFixed(1)} points</strong></div><p>${values[key]} · weight ${percent(p.weights[key])}</p></div>`,
          )
          .join(
            "",
          )}${record.campaign_evidence ? `<h3>Campaign evidence</h3><p>${escapeHTML(record.campaign_evidence.id)} · group risk ${record.campaign_evidence.risk}</p><ul class="reasons-list">${(record.campaign_evidence.links || []).map((link) => `<li>${link.keys.map(escapeHTML).join(" ↔ ")}: ${link.shared_count} shared fingerprints; ${percent(link.overlap_fraction)} overlap.</li>`).join("")}</ul>` : ""}<p class="detail-note">This is the stored decision record. The key's current score may have changed. Export includes the full policy and any shared fingerprint evidence.</p><button class="button secondary" id="download-incident">Export this incident</button>`;
      $("#download-incident").onclick = () => {
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(record, null, 2)], {
            type: "application/json",
          }),
        );
        const a = document.createElement("a");
        a.href = url;
        a.download = `${record.incident_id}.json`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
    } catch (error) {
      $("#incident-content").textContent = error.message;
    }
  }
  document.addEventListener("click", (event) => {
    const incident = event.target.closest("[data-incident]");
    if (incident) showIncident(incident.dataset.incident);
  });

  async function loadExperiments() {
    if (location.hash !== "#validation") return;
    try {
      const reports = await (await api("/api/experiments")).json();
      const copy = reports["copy-experiment"],
        comparison = reports["defense-comparison"];
      $("#experiment-content").innerHTML =
        `<div class="section-heading"><h2>Copying and customer impact</h2><p>Saved experiments, separate from live dashboard traffic.</p></div>${copy ? `<article class="panel"><div class="panel-heading"><div><h2>Can the API answers train a copy?</h2><p>Saved ${escapeHTML(new Date(copy.generated_at).toLocaleString())} · up to ${copy.protocol.attempt_budget} attempts / ${copy.protocol.time_budget_seconds}s per run · ${copy.protocol.test_count} evaluation inputs</p></div><span class="soft-tag">LOCAL HTTP EXPERIMENT</span></div><div class="table-scroll"><table><thead><tr><th>Protection</th><th>Requests / answers</th><th>Copy agreement</th><th>First alert / denial</th><th>Customer answers</th><th>Client P95</th></tr></thead><tbody>${copy.runs.map((r) => `<tr><td>${escapeHTML(r.name)}</td><td>${r.attempted} / ${r.released}<br><small>${r.withheld} withheld</small></td><td>${r.agreement == null ? "Insufficient training data" : percent(r.agreement, 1)}<br><small>${r.training_unique_inputs} unique training inputs</small></td><td>${r.first_alert_seconds == null ? "—" : r.first_alert_seconds.toFixed(2) + "s"} / ${r.first_denial_seconds == null ? "—" : r.first_denial_seconds.toFixed(2) + "s"}</td><td>${r.legitimate.allowed} / ${r.legitimate.attempted}<br><small>${r.legitimate.denied} denied · ${r.legitimate.errors} errors</small></td><td>${r.client_latency.p95_ms?.toFixed(1) ?? "—"} ms</td></tr>`).join("")}</tbody></table></div><div class="validation-description"><strong>Agreement compares the copy's labels with the protected model on separate sentences.</strong> It is not a percentage of the model stolen. The attacker receives no training corpus or administrator access. Client timing includes the HTTP response.<details><summary>Method and limits</summary><p>${copy.limitations.map(escapeHTML).join(" ")}</p><p>Input selection: ${escapeHTML(copy.protocol.selection)}.</p></details></div></article>` : `<p class="notice">No copying report yet. Run the local copying experiment from the README.</p>`}${
          comparison
            ? `<div class="section-heading"><h2>Compare the defenses</h2><p>Calibrated to the same ≤5% false-positive target, then tested with frozen settings.</p></div><article class="panel"><div class="table-scroll"><table><thead><tr><th>Configuration</th><th>Frozen setting</th><th>Detected attacks</th><th>Flagged legitimate sessions</th><th>Customer answers</th></tr></thead><tbody>${comparison.results.map((r) => `<tr><td>${escapeHTML(r.configuration)}</td><td>${r.setting ?? "Off"}${r.configuration === "rate_only" ? " requests / 60s" : r.setting == null ? "" : " risk points"}</td><td>${r.detected} / ${r.attack_sessions}</td><td>${r.false_positives} / ${r.benign_sessions}</td><td>${r.legitimate_allowed} / ${r.legitimate_attempted}</td></tr>`).join("")}</tbody></table></div><div class="validation-description"><p>${escapeHTML(comparison.dataset_origin)}.</p><details><summary>Scenario results and limitations</summary><div class="table-scroll"><table><thead><tr><th>Scenario</th>${comparison.results.map((r) => `<th>${escapeHTML(r.configuration)}</th>`).join("")}</tr></thead><tbody>${[
                ...new Set(
                  comparison.results[0].sessions.map((s) => s.profile),
                ),
              ]
                .map(
                  (profile) =>
                    `<tr><td>${escapeHTML(profile)}</td>${comparison.results
                      .map((r) => {
                        const rows = r.sessions.filter(
                          (s) => s.profile === profile,
                        );
                        return `<td>${rows.filter((s) => s.flagged).length} / ${rows.length} flagged</td>`;
                      })
                      .join("")}</tr>`,
                )
                .join(
                  "",
                )}</tbody></table></div><p>${comparison.limitations.map(escapeHTML).join(" ")}</p><p>${escapeHTML(comparison.protocol.behavioral_response)}</p></details></div></article>`
            : ""
        }<div class="section-heading"><h2>Original synthetic regression suite</h2><p>The report below uses the existing generator families.</p></div>`;
      if (copy) {
        const colors = ["#28746a", "#b45d38", "#5868a0"];
        const width = 740,
          height = 170;
        const seconds = Math.max(
          copy.protocol.time_budget_seconds,
          ...copy.runs.flatMap((r) =>
            r.progress.map((p) => p.response_seconds),
          ),
        );
        const maximum = Math.max(1, ...copy.runs.map((r) => r.released));
        const x = (value) => 45 + (value / seconds) * (width - 65);
        const y = (value) => height - 25 - (value / maximum) * (height - 45);
        const paths = copy.runs
          .map((r, i) => {
            let answers = 0;
            const points = [`${x(0)},${y(0)}`];
            for (const p of r.progress) {
              if (p.status === 200) answers += 1;
              points.push(`${x(p.response_seconds)},${y(answers)}`);
            }
            points.push(`${x(seconds)},${y(answers)}`);
            return `<polyline points="${points.join(" ")}" fill="none" stroke="${colors[i]}" stroke-width="2.5"/>`;
          })
          .join("");
        const chart = document.createElement("div");
        chart.className = "copy-progress-chart";
        chart.innerHTML = `<h3>Answers released over time</h3><p>${copy.runs.map((r, i) => `<span style="color:${colors[i]}">${escapeHTML(r.name)}</span>`).join(" · ")}</p><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Cumulative released API answers for each saved experiment"><path d="M45 20V145H720" fill="none" stroke="#bbc7c1"/>${paths}<text x="7" y="25">${maximum}</text><text x="20" y="148">0</text><text x="45" y="166">0 seconds</text><text x="645" y="166">${seconds.toFixed(1)} seconds</text></svg><p>Measured response counts; copy agreement is evaluated separately after training.</p>`;
        $("#experiment-content .panel .panel-heading").after(chart);
      }
    } catch (error) {
      $("#experiment-content").textContent = error.message;
    }
  }
  window.addEventListener("hashchange", loadExperiments);
  loadExperiments();
})();
