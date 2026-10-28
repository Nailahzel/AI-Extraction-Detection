"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const icon = (name) =>
  `<svg aria-hidden="true"><use href="/static/icons.svg#${name}"/></svg>`;
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const number = (value) => Number(value || 0).toLocaleString();
const percent = (value, digits = 0) =>
  `${(Number(value || 0) * 100).toFixed(digits)}%`;
const time = (value) =>
  new Date(value * 1000).toLocaleTimeString([], { hour12: false });
const state = {
  snapshot: null,
  page: "overview",
  selected: null,
  evaluation: null,
  token: sessionStorage.getItem("modelshield-token") || "",
  toastTimer: null,
  online: false,
  batchRunning: false,
  manualRunning: false,
};
const pages = {
  overview: [
    "Overview",
    "REQUEST MONITOR",
    "API activity",
    "Requests, risk scores, and responses for each API key.",
  ],
  traffic: [
    "Live traffic",
    "REQUEST LOG",
    "Recent requests",
    "See which answers were released, which were withheld, and the risk at that time.",
  ],
  campaigns: [
    "Campaigns",
    "SHARED INPUTS",
    "Related API keys",
    "Groups of keys with overlapping probes and repeated uncertain predictions.",
  ],
  lab: [
    "Attack lab",
    "MANUAL TESTS & SCENARIOS",
    "Attack lab",
    "Send your own inputs or run a repeatable traffic scenario.",
  ],
  validation: [
    "Validation",
    "SAVED BENCHMARK",
    "Test results",
    "Results from the included synthetic traffic, with the test method and limitations.",
  ],
  policy: [
    "Defense policy",
    "DETECTOR SETTINGS",
    "Defense policy",
    "Check the thresholds, signal weights, and enforcement mode.",
  ],
};
const signals = {
  rate: [
    "Query-rate anomaly",
    "10-second request burst against the client baseline.",
  ],
  diversity: ["Input diversity", "Average lexical distance in recent queries."],
  boundary: ["Boundary probing", "Share of answers below 65% confidence."],
  sequence: [
    "Sequential probing",
    "Controlled changes between consecutive inputs.",
  ],
};

async function api(path, options = {}) {
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
    ...options.headers,
  };
  const response = await fetch(path, {
    ...options,
    headers,
    signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) {
    let detail;
    try {
      const data = await response.json();
      detail =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {
      detail = response.statusText;
    }
    if (response.status === 401 && !$("#auth-dialog").open)
      $("#auth-dialog").showModal();
    throw new Error(detail || `Request failed (${response.status}).`);
  }
  return response;
}
const post = async (path, data = {}) =>
  (await api(path, { method: "POST", body: JSON.stringify(data) })).json();
function toast(message) {
  clearTimeout(state.toastTimer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  state.toastTimer = setTimeout(() => ($("#toast").hidden = true), 4500);
}
function statusBadge(status) {
  const names = {
    allow: "Allowed",
    healthy: "Healthy",
    monitor: "Monitor",
    throttled: "Throttled",
    blocked: "Blocked",
    idle: "Standby",
    observed: "Observed",
  };
  return `<span class="status-pill ${escapeHTML(status)}">${names[status] || escapeHTML(status)}</span>`;
}
function riskColor(risk, policy) {
  if (risk >= policy.block_threshold) return "#b56367";
  if (risk >= policy.throttle_threshold) return "#ad804d";
  if (risk >= policy.monitor_threshold) return "#748697";
  return "#568b70";
}

function navigate() {
  const page = location.hash.slice(1) || "overview";
  state.page = pages[page] ? page : "overview";
  const [name, eyebrow, title, subtitle] = pages[state.page];
  $("#breadcrumb-current").textContent = name;
  $("#page-eyebrow").textContent = eyebrow;
  $("#page-title").textContent = title;
  $("#page-subtitle").textContent = subtitle;
  $$(".page").forEach((el) => (el.hidden = el.id !== `page-${state.page}`));
  $$(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.page === state.page);
    if (el.dataset.page === state.page) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  $("#sidebar").classList.remove("open");
  if (state.page === "validation") loadValidation();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function renderChart(data) {
  const width = 680,
    height = 215,
    left = 32,
    right = 9,
    top = 13,
    bottom = 28;
  const max = Math.max(4, ...data.map((p) => Math.max(p.allowed, p.denied)));
  const ceiling = Math.ceil(max / 4) * 4;
  const x = (i) => left + (i * (width - left - right)) / 59;
  const y = (value) =>
    height - bottom - (value / ceiling) * (height - top - bottom);
  const line = (key) =>
    data
      .map(
        (p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`,
      )
      .join(" ");
  const area = (key) => `${line(key)} L${x(59)},${y(0)} L${x(0)},${y(0)} Z`;
  const grid = Array.from({ length: 5 }, (_, i) => {
    const value = (ceiling * i) / 4;
    return `<line x1="${left}" x2="${width - right}" y1="${y(value)}" y2="${y(value)}" class="chart-grid"/><text x="${left - 12}" y="${y(value) + 3}" text-anchor="end" class="chart-label">${value}</text>`;
  }).join("");
  const labels = [0, 12, 24, 36, 48, 59]
    .map(
      (i) =>
        `<text x="${x(i)}" y="${height - 5}" text-anchor="${i === 0 ? "start" : i === 59 ? "end" : "middle"}" class="chart-label">${i === 59 ? "now" : `${59 - i}s ago`}</text>`,
    )
    .join("");
  const count = data.reduce((sum, p) => sum + p.allowed + p.denied, 0);
  $("#traffic-chart").innerHTML =
    `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${count} requests in the last 60 seconds"><defs><linearGradient id="allow-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#83b19b" stop-opacity=".30"/><stop offset="100%" stop-color="#83b19b" stop-opacity=".02"/></linearGradient><linearGradient id="deny-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#c99d6b" stop-opacity=".30"/><stop offset="100%" stop-color="#c99d6b" stop-opacity=".02"/></linearGradient></defs>${grid}<path d="${area("allowed")}" fill="url(#allow-fill)"/><path d="${area("denied")}" fill="url(#deny-fill)"/><path d="${line("allowed")}" fill="none" stroke="#548d73" stroke-width="2" vector-effect="non-scaling-stroke"/><path d="${line("denied")}" fill="none" stroke="#b48852" stroke-width="2" vector-effect="non-scaling-stroke"/>${labels}</svg>${count ? "" : '<div class="chart-empty"><strong>No requests in this window</strong><span>Run the live demo or send a prediction from Attack lab.</span></div>'}`;
  $("#chart-total").textContent = `${number(count)} requests in this window`;
  const spark = data.slice(-20);
  const sparkMax = Math.max(1, ...spark.map((p) => p.allowed + p.denied));
  $(".sparkline path").setAttribute(
    "d",
    spark
      .map(
        (p, i) =>
          `${i ? "L" : "M"}${i * 4.5},${18 - ((p.allowed + p.denied) / sparkMax) * 16}`,
      )
      .join(" "),
  );
}

function renderClients(snapshot) {
  const query = $("#client-search").value.toLowerCase();
  let clients = snapshot.clients.filter((c) =>
    `${c.id} ${c.name}`.toLowerCase().includes(query),
  );
  clients.sort(
    (a, b) =>
      (b.total > 0) - (a.total > 0) ||
      b.risk - a.risk ||
      a.id.localeCompare(b.id),
  );
  if (!query) clients = clients.slice(0, 5);
  $("#active-client-count").textContent =
    `${snapshot.totals.active_keys} active`;
  $("#client-table").innerHTML = clients.length
    ? clients
        .map(
          (c) =>
            `<tr class="client-row" data-client="${escapeHTML(c.id)}" tabindex="0" role="button" aria-label="Inspect ${escapeHTML(c.id)}"><td><div class="client-id"><span class="key-avatar">${icon("key")}</span><div><strong>${escapeHTML(c.id)}</strong><small>${escapeHTML(c.name)}</small></div></div></td><td>${number(c.signals.rate)}</td><td>${Number(c.signals.diversity || 0).toFixed(2)}</td><td>${percent(c.signals.boundary)}</td><td><div class="risk-cell"><div class="risk-track"><span style="width:${c.risk}%;background:${riskColor(c.risk, snapshot.policy)}"></span></div>${Math.round(c.risk)}</div></td><td>${statusBadge(c.total ? c.status : "idle")}</td><td><svg class="row-arrow"><use href="/static/icons.svg#chevron"/></svg></td></tr>`,
        )
        .join("")
    : '<tr class="empty-table"><td colspan="7">No API keys match this search.</td></tr>';
}

function renderAlerts(snapshot) {
  $("#alert-count").textContent = snapshot.alerts.length;
  $("#alert-feed").innerHTML = snapshot.alerts.length
    ? snapshot.alerts
        .slice(0, 3)
        .map(
          (a) =>
            `<button class="alert-item" data-incident="${escapeHTML(a.id)}"><span class="alert-symbol">${icon(a.campaign ? "network" : "alert")}</span><span class="alert-copy"><strong>${a.campaign ? "Coordinated campaign" : "Extraction risk detected"}</strong><p>${escapeHTML(a.client_id)} · ${escapeHTML(a.reasons.find((r) => r.includes("boundary")) || a.reasons[0] || "Multiple signals exceeded the policy.")}</p><span class="alert-meta">${statusBadge(a.action)}<span>${time(a.at)}</span></span></span></button>`,
        )
        .join("")
    : `<div class="empty-state">${icon("shield")}<h3>No alerts yet</h3><p>Alerts appear here when a key reaches the action threshold.</p></div>`;
}

function renderEvents(snapshot) {
  $("#event-table").innerHTML = snapshot.events.length
    ? snapshot.events
        .map(
          (e) =>
            `<tr><td>${e.incident_id ? `<button class="text-button" data-incident="${escapeHTML(e.incident_id)}">${time(e.at)} · evidence</button>` : time(e.at)}</td><td><button class="text-button" data-client="${escapeHTML(e.client_id)}">${escapeHTML(e.client_id)}</button></td><td>${e.label ? escapeHTML(e.label) : "Answer withheld"}</td><td>${e.confidence ? percent(e.confidence, 1) : "—"}</td><td>${e.risk.toFixed(1)}</td><td>${statusBadge(e.action)}</td><td>${e.latency.toFixed(2)} ms</td></tr>`,
        )
        .join("")
    : '<tr class="empty-table"><td colspan="7">No requests yet. Start a simulation or use the prediction playground.</td></tr>';
}

function renderCampaigns(snapshot) {
  $("#campaign-count").textContent = snapshot.campaigns.length;
  $("#campaign-list").innerHTML = snapshot.campaigns.length
    ? snapshot.campaigns
        .map(
          (c) =>
            `<article class="panel campaign-card"><div class="panel-heading"><div><h2>${escapeHTML(c.id)}</h2><p>${c.keys.length} correlated keys · ${c.queries} observations · ${c.shared_patterns} distinct patterns</p></div><span class="status-pill monitor">Correlated</span></div><div class="campaign-members">${c.keys.map((k) => `<button class="campaign-node" data-client="${escapeHTML(k)}">${icon("key")}${escapeHTML(k)}</button>`).join(`<span class="flow-line"></span>`)}</div><p>${escapeHTML(c.reason)} Group risk: <strong>${c.risk}</strong>. Uncertain answer share: <strong>${percent(c.boundary)}</strong>. Policy applies when each key next requests a prediction.</p></article>`,
        )
        .join("")
    : `<div class="panel empty-state">${icon("network")}<h3>No active coordinated campaigns.</h3><p>Run the Coordinated campaign scenario in Attack lab to try this check.</p><button class="button secondary" data-navigate="lab">Open Attack lab${icon("arrow")}</button></div>`;
}

function renderPolicy(snapshot) {
  const p = snapshot.policy;
  $("#monitor-threshold").textContent = `${p.monitor_threshold}+`;
  $("#throttle-threshold").textContent = `${p.throttle_threshold}+`;
  $("#block-threshold").textContent = `${p.block_threshold}+`;
  $("#enforce-toggle").checked = snapshot.enforcing;
  $("#mode-label").textContent = snapshot.enforcing ? "Enforcing" : "Observing";
  const bands = [
    [
      `0–${p.monitor_threshold - 1}`,
      "healthy",
      "Release answers and collect observations.",
    ],
    [
      `${p.monitor_threshold}–${p.throttle_threshold - 1}`,
      "monitor",
      "Keep answering while monitoring the key.",
    ],
    [
      `${p.throttle_threshold}–${p.block_threshold - 1}`,
      "throttled",
      `Withhold answers; retry after ${p.throttle_seconds}s.`,
    ],
    [
      `${p.block_threshold}–100`,
      "blocked",
      `Withhold answers for ${p.cooldown_seconds}s.`,
    ],
  ];
  $("#policy-bands").innerHTML = bands
    .map(
      ([range, status, description]) =>
        `<div class="policy-band"><strong>${range}</strong>${statusBadge(status)}<p>${description}</p></div>`,
    )
    .join("");
  $("#policy-weights").innerHTML = Object.entries(p.weights)
    .map(
      ([key, weight]) =>
        `<div class="weight-row"><div><span>${signals[key][0]}</span><strong>${percent(weight)}</strong></div><div class="weight-bar"><span style="width:${weight * 100}%"></span></div><p>${signals[key][1]}</p></div>`,
    )
    .join("");
}

function renderDetail() {
  const c = state.snapshot?.clients.find((c) => c.id === state.selected);
  if (!c) return;
  const weights = state.snapshot.policy.weights;
  $("#detail-content").innerHTML =
    `<div class="detail-title"><h2>${escapeHTML(c.id)}</h2>${statusBadge(c.total ? c.status : "idle")}</div><div class="detail-subtitle">${escapeHTML(c.name)} · current rolling window</div><div class="detail-risk"><strong>${c.risk.toFixed(0)}</strong><span>/ 100</span><small>Peak ${c.peak_risk.toFixed(0)} · ${c.signals.evidence || 0} observations</small></div><h3>Why this score?</h3><ul class="reasons-list">${(c.reasons.length ? c.reasons : ["Waiting for the first prediction."]).map((r) => `<li>${escapeHTML(r)}</li>`).join("")}</ul><h3>Signal contributions</h3>${Object.entries(
      signals,
    )
      .map(
        ([key, [label]]) =>
          `<div class="weight-row"><div><span>${label}</span><strong>${(c.signals.contributions?.[key] || 0).toFixed(1)} / ${weights[key] * 100}</strong></div><div class="weight-bar"><span style="width:${((c.signals.contributions?.[key] || 0) / (weights[key] * 100)) * 100}%"></span></div></div>`,
      )
      .join(
        "",
      )}${c.campaign ? `<a href="#campaigns" class="detail-campaign" data-close="detail-dialog">${icon("network")} ${escapeHTML(c.campaign)} · campaign risk override</a>` : ""}<div class="detail-counts"><div><strong>${c.answered}</strong><small>Answers released</small></div><div><strong>${c.denied}</strong><small>Answers withheld</small></div><div><strong>${c.retry_after}s</strong><small>Current cooldown</small></div></div><div class="detail-note">${c.signals.baseline_ready ? "Learned" : "Starter"} rate baseline: ${c.signals.baseline_rpm || 36}/minute. ${c.signals.baseline_ready ? "Based on a bounded median of trusted request intervals." : "At least 16 trusted intervals are needed before adaptation."}<br>Risk is behavioral evidence, not proof of theft. Confidence reflects this local demonstration classifier.</div>`;
}

function updateInputControls() {
  const snapshot = state.snapshot;
  const busy = state.batchRunning || state.manualRunning;
  const demoDisabled = !snapshot?.demo_mode || snapshot.demo.running || busy;
  $("#demo-button").disabled = demoDisabled;
  $("#guide-start").disabled = demoDisabled;
  $$("[data-scenario]").forEach((el) => (el.disabled = demoDisabled));
  $("#reset-button").disabled = !snapshot?.demo_mode || busy;
  $("#enforce-toggle").disabled = busy;
  $("#predict-form button[type='submit']").disabled = busy;
  $("#batch-send").disabled = demoDisabled;
  $$(
    "[data-input-mode], [data-batch-example], #batch-key, #batch-text, #batch-delay",
  ).forEach((el) => (el.disabled = busy));
}

function render(snapshot) {
  state.snapshot = snapshot;
  const t = snapshot.totals;
  $("#model-name").textContent = snapshot.model.name;
  $("#metric-requests").textContent = number(t.requests);
  $("#metric-denied").textContent = number(t.denied);
  $("#metric-keys").innerHTML =
    `${t.active_keys}<span class="metric-unit"> / ${snapshot.clients.length}</span>`;
  $("#metric-latency").innerHTML =
    `${t.requests ? t.latency_p95.toFixed(1) : "—"}<span class="metric-unit">ms</span>`;
  $("#denied-detail").textContent = t.denied
    ? `${percent(t.denied / Math.max(1, t.requests), 1)} of session requests`
    : "No answers withheld yet";
  $("#keys-detail").textContent = t.active_keys
    ? `${t.at_risk} high-risk · ${t.active_keys - t.at_risk} below threshold`
    : "Awaiting first request";
  $("#defense-mode").textContent = snapshot.enforcing
    ? "ENFORCING"
    : "OBSERVING";
  $("#defense-title").textContent = !snapshot.enforcing
    ? "Observation only"
    : t.denied
      ? "Answers have been withheld"
      : t.requests
        ? "Monitoring requests"
        : "Waiting for requests";
  $("#defense-description").innerHTML = !snapshot.enforcing
    ? "Risk is still recorded.<br>All predictions are being released."
    : t.denied
      ? "Some requests crossed the action threshold.<br>Inspect their keys in the alert feed."
      : "Send a request or run a scenario.<br>Risk is tracked separately for each key.";
  $("#defense-threats").textContent = t.at_risk;
  $("#demo-banner").hidden = !snapshot.demo.running;
  const elapsed = snapshot.demo.started_at
    ? Math.floor(snapshot.now - snapshot.demo.started_at)
    : 0;
  $("#demo-stage").textContent =
    elapsed < 5
      ? "Establishing normal behavior"
      : t.denied
        ? "Defense responding to suspicious traffic"
        : "Simulation in progress";
  $("#demo-description").textContent =
    `${snapshot.demo.scenario || "guided"} scenario · ${snapshot.demo.sent} requests sent · ${snapshot.demo.errors} errors`;
  $("#demo-elapsed").textContent = `${elapsed}s / 32s`;
  $("#demo-button").disabled = snapshot.demo.running;
  $("#demo-button span").textContent = snapshot.demo.running
    ? "Demo running"
    : "Run live demo";
  $$("[data-scenario]").forEach((el) => (el.disabled = snapshot.demo.running));
  if (!snapshot.demo_mode) {
    $("#demo-button").hidden = true;
    $(".environment-label").textContent = "AUTHENTICATED SERVICE";
    $("#reset-button").disabled = true;
    $$("[data-scenario]").forEach((el) => (el.disabled = true));
  }
  renderChart(snapshot.timeline);
  renderClients(snapshot);
  renderAlerts(snapshot);
  renderEvents(snapshot);
  renderCampaigns(snapshot);
  renderPolicy(snapshot);
  updateInputControls();
  if ($("#detail-dialog").open) renderDetail();
}

async function refresh() {
  try {
    render(await (await api("/api/snapshot")).json());
    state.online = true;
    $("#connection").classList.remove("offline");
    $("#connection").innerHTML = '<span class="live-dot"></span>System online';
    $("#connection-error").hidden = true;
  } catch (error) {
    state.online = false;
    $("#connection").classList.add("offline");
    $("#connection").innerHTML = '<span class="live-dot"></span>Disconnected';
    $("#connection-error").hidden = false;
    $("#connection-error").textContent =
      `Live telemetry unavailable. ${error.message} Retrying automatically.`;
  }
}
async function poll() {
  await refresh();
  setTimeout(poll, 1000);
}

async function startDemo(scenario = "guided") {
  if (state.batchRunning || state.manualRunning) return;
  try {
    await post("/api/demo/start", { scenario, seed: 42 });
    toast(
      `${scenario === "guided" ? "Live demo" : scenario[0].toUpperCase() + scenario.slice(1) + " scenario"} started. Normal traffic begins first.`,
    );
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

async function download(path, filename) {
  try {
    const response = await api(path);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Download ready.");
  } catch (error) {
    toast(error.message);
  }
}

async function loadValidation() {
  try {
    const report = await (await api("/api/evaluation")).json();
    state.evaluation = report;
    if (!report.available) {
      $("#validation-content").innerHTML =
        `<div class="panel empty-state">${icon("chart")}<h3>Measurements have not been generated.</h3><p>${escapeHTML(report.message)}</p></div>`;
      return;
    }
    const t = report.test;
    const suiteLabel =
      report.evaluation_kind === "regression" ? "regression" : "held-out";
    const duration =
      t.median_detection_seconds === null
        ? "—"
        : `${t.median_detection_seconds.toFixed(2)}s`;
    $("#validation-content").innerHTML =
      `<div class="notice">${icon("chart")}<div><strong>These results cover the included synthetic scenarios.</strong><p>${t.attack_sessions + t.benign_sessions} ${suiteLabel} synthetic sessions · test seeds ${report.test_seed_range.join("–")} · ${escapeHTML(report.generated_at)}. Calibration and test use different seeds and subject vocabulary; they share traffic-generator families.</p></div></div><div class="validation-metrics"><article class="panel validation-metric"><h3>Attack detection rate</h3><div class="validation-value">${percent(t.detection_rate, 1)}</div><p>${t.detected_attacks} / ${t.attack_sessions} attack sessions detected</p><span class="goal-tag">Target ≥ 90%</span></article><article class="panel validation-metric"><h3>False-positive rate</h3><div class="validation-value">${percent(t.false_positive_rate, 1)}</div><p>${t.false_positives} / ${t.benign_sessions} benign sessions flagged</p><span class="goal-tag">Target &lt; 5%</span></article><article class="panel validation-metric"><h3>Median time to detect</h3><div class="validation-value">${duration}</div><p>P95 ${t.p95_detection_seconds === null ? "—" : t.p95_detection_seconds.toFixed(2) + "s"} · detected attacks only</p><span class="goal-tag">Target ≤ 10s</span></article></div><article class="panel"><div class="panel-heading"><div><h2>Results by traffic profile</h2><p>Detection means reaching the enforcement threshold at any point in a session.</p></div><span class="soft-tag">${suiteLabel.toUpperCase()}</span></div><div class="table-scroll"><table><thead><tr><th>Profile</th><th>Ground truth</th><th>Sessions</th><th>Flagged</th><th>Detection / FP rate</th><th>Median detection</th></tr></thead><tbody>${t.profiles.map((p) => `<tr><td>${escapeHTML(p.profile)}</td><td>${p.attack ? "Extraction" : "Benign"}</td><td>${p.sessions}</td><td>${p.flagged}</td><td>${percent(p.flagged / p.sessions, 1)}</td><td>${p.median_detection_seconds === null ? "—" : p.median_detection_seconds.toFixed(2) + "s"}</td></tr>`).join("")}</tbody></table></div><div class="validation-footnote">95% Wilson intervals: detection ${percent(t.detection_ci95[0], 1)}–${percent(t.detection_ci95[1], 1)}; false positives ${percent(t.false_positive_ci95[0], 1)}–${percent(t.false_positive_ci95[1], 1)}.</div></article><article class="panel validation-note"><div class="panel-heading"><h2>What these numbers mean</h2></div><div class="validation-description"><strong>Protocol.</strong> ${escapeHTML(report.methodology)}<br><br><strong>Limits.</strong> ${report.limitations.map(escapeHTML).join(" ")}<br><br><strong>Model.</strong> ${escapeHTML(report.model.name)}. ${report.model.training_samples} original synthetic training examples. Fingerprint: <code>${escapeHTML(report.model.fingerprint)}</code>.</div></article><div class="report-actions"><button class="button primary" id="download-submission">${icon("download")}Download five-page submission</button><button class="button secondary" id="download-results">${icon("download")}Download benchmark JSON</button></div>`;
  } catch (error) {
    $("#validation-content").innerHTML =
      `<div class="notice danger">${escapeHTML(error.message)}</div>`;
  }
}

const scenarios = [
  [
    "burst",
    "High-volume extraction",
    "RAPID QUERIES",
    "bolt",
    "A fast, diverse query stream targets uncertain model responses.",
  ],
  [
    "boundary",
    "Decision-boundary probing",
    "CONTROLLED CHANGES",
    "activity",
    "Small, systematic input changes map where the model changes its mind.",
  ],
  [
    "distributed",
    "Coordinated campaign",
    "CROSS-KEY DETECTION",
    "network",
    "Three slower clients submit shared probes. Correlation links the evidence.",
  ],
  [
    "normal",
    "Everyday users",
    "BENIGN TRAFFIC",
    "key",
    "Natural review requests arrive with realistic pauses between queries.",
  ],
  [
    "batch",
    "Legitimate batch job",
    "FALSE-POSITIVE CHECK",
    "server",
    "High-volume, varied reviews test whether a burst alone causes enforcement.",
  ],
  [
    "guided",
    "The guided demo",
    "START HERE",
    "play",
    "Normal traffic first. An extraction attempt follows after five seconds.",
  ],
];
$("#scenario-grid").innerHTML = scenarios
  .map(
    ([id, title, label, shape, description]) =>
      `<article class="scenario-card"><div class="scenario-card-top">${icon(shape)}<span class="scenario-label">${label}</span></div><h3>${title}</h3><p>${description}</p><button class="button secondary" data-scenario="${id}">Run scenario${icon("play")}</button></article>`,
  )
  .join("");

document.addEventListener("click", async (event) => {
  const close = event.target.closest("[data-close]");
  if (close) $(`#${close.dataset.close}`).close();
  const nav = event.target.closest("[data-navigate]");
  if (nav) location.hash = nav.dataset.navigate;
  const client = event.target.closest("[data-client]");
  if (client) {
    state.selected = client.dataset.client;
    renderDetail();
    if (!$("#detail-dialog").open) $("#detail-dialog").showModal();
  }
  const scenario = event.target.closest("[data-scenario]");
  if (scenario) await startDemo(scenario.dataset.scenario);
  if (event.target.closest("#download-submission"))
    await download("/api/submission", "ModelShield-submission.pdf");
  if (event.target.closest("#download-results"))
    await download("/api/evaluation", "modelshield-benchmark.json");
});
document.addEventListener("keydown", (event) => {
  if (
    (event.key === "Enter" || event.key === " ") &&
    event.target.matches("tr[data-client]")
  ) {
    event.preventDefault();
    event.target.click();
  }
});
$("#demo-button").addEventListener("click", () => startDemo());
$("#export-button").addEventListener("click", () =>
  download("/api/export", "modelshield-evidence.json"),
);
$("#guide-button").addEventListener("click", () =>
  $("#guide-dialog").showModal(),
);
$("#guide-start").addEventListener("click", () => {
  $("#guide-dialog").close();
  location.hash = "overview";
  startDemo();
});
$("#menu-button").addEventListener("click", () =>
  $("#sidebar").classList.toggle("open"),
);
$("#client-search").addEventListener("input", () => {
  if (state.snapshot) renderClients(state.snapshot);
});
$("#reset-button").addEventListener("click", () =>
  $("#confirm-dialog").showModal(),
);
$("#confirm-reset").addEventListener("click", async () => {
  if (state.batchRunning || state.manualRunning) return;
  try {
    await post("/api/reset");
    $("#confirm-dialog").close();
    toast("Session cleared. You can start a new test.");
    $("#batch-results").hidden = true;
    $("#predict-result").hidden = true;
    await refresh();
  } catch (error) {
    toast(error.message);
  }
});
$("#stop-demo").addEventListener("click", async () => {
  try {
    await post("/api/demo/stop");
    toast("Simulation stopped. Evidence is preserved.");
    await refresh();
  } catch (error) {
    toast(error.message);
  }
});
$("#enforce-toggle").addEventListener("change", async (event) => {
  try {
    await post("/api/mode", { enforce: event.target.checked });
    toast(
      event.target.checked
        ? "Enforcement enabled."
        : "Observe mode enabled. Model answers will be released.",
    );
    await refresh();
  } catch (error) {
    toast(error.message);
    event.target.checked = !event.target.checked;
  }
});
$("#predict-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.batchRunning || state.manualRunning) return;
  state.manualRunning = true;
  updateInputControls();
  try {
    const response = await fetch("/predict", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": $("#predict-key").value,
      },
      body: JSON.stringify({ text: $("#predict-text").value }),
      signal: AbortSignal.timeout(12000),
    });
    const data = await response.json();
    $("#predict-result").hidden = false;
    $("#predict-result").innerHTML =
      `<strong>HTTP ${response.status} · ${response.ok ? "Prediction received" : response.status === 429 ? "Defense policy applied" : "Request rejected"}</strong><pre>${escapeHTML(JSON.stringify(data, null, 2))}</pre>`;
    await refresh();
  } catch (error) {
    toast(error.message);
  } finally {
    state.manualRunning = false;
    updateInputControls();
  }
});
$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = $("#admin-token").value;
  try {
    await api("/api/snapshot");
    sessionStorage.setItem("modelshield-token", state.token);
    $("#auth-dialog").close();
    $("#admin-token").value = "";
    await refresh();
  } catch (error) {
    state.token = "";
    sessionStorage.removeItem("modelshield-token");
    toast(error.message);
  }
});
window.addEventListener("hashchange", navigate);
navigate();
poll();
