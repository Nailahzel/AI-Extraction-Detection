"use strict";

// Use the same public prediction route as the single-input form. Administrator
// snapshots supply the private risk readings; they are not model responses.
(() => {
  let run = null;
  let wake = null;
  const inputs = () =>
    $("#batch-text")
      .value.split(/\r\n|\n|\r/)
      .map((text) => text.trim())
      .filter(Boolean);
  const showError = (message = "") => {
    $("#batch-error").textContent = message;
    $("#batch-error").hidden = !message;
  };
  const updateCount = () => {
    $("#batch-count").textContent = `${inputs().length} / 30 inputs`;
    showError();
  };

  $$("[data-input-mode]").forEach((button) =>
    button.addEventListener("click", () => {
      const batch = button.dataset.inputMode === "batch";
      $("#single-playground").hidden = batch;
      $("#batch-form").hidden = !batch;
      $$("[data-input-mode]").forEach((el) =>
        el.setAttribute("aria-pressed", String(el === button)),
      );
    }),
  );
  $("#batch-text").addEventListener("input", updateCount);
  $$("[data-batch-example]").forEach((button) =>
    button.addEventListener("click", () => {
      const subjects = ["movie", "hotel", "camera", "delivery", "meal"];
      const modifiers = [
        "somewhat",
        "barely",
        "almost",
        "possibly",
        "occasionally",
        "moderately",
      ];
      const adjectives = ["excellent", "terrible", "wonderful"];
      const probing = button.dataset.batchExample === "probing";
      $("#batch-text").value = Array.from(
        { length: probing ? 30 : 15 },
        (_, i) =>
          probing
            ? `The ${subjects[Math.floor(i / 6)]} was ${modifiers[i % 6]} good yet terrible.`
            : `The ${subjects[i % 5]} was ${adjectives[Math.floor(i / 5)]}.`,
      ).join("\n");
      updateCount();
    }),
  );

  function readSnapshot(snapshot) {
    if (snapshot.started_at !== run.session)
      throw new Error(
        "The server session changed. Reset and run a fresh comparison.",
      );
    if (snapshot.enforcing !== run.enforcing)
      throw new Error(
        "Defense mode changed in another tab. Run a fresh comparison.",
      );
    const client = snapshot.clients.find((c) => c.id === run.key);
    if (!client)
      throw new Error("This key is no longer available in the dashboard.");
    run.latest = client;
    if (client.risk >= run.peak) {
      run.peak = client.risk;
      run.reasons = client.reasons;
    }
    for (const alert of snapshot.alerts) {
      if (alert.client_id !== run.key || alert.at < run.started) continue;
      run.alerts.set(`${alert.id}:${alert.at}`, alert);
      if (alert.risk >= run.peak) {
        run.peak = alert.risk;
        run.reasons = alert.reasons;
      }
    }
    render(snapshot);
    return client;
  }

  function renderBatch() {
    const answered = run.rows.filter((r) => r.status === 200).length;
    const denied = run.rows.filter((r) => r.status === 429).length;
    const errors = run.rows.filter(
      (r) => ![200, 429].includes(r.status),
    ).length;
    const flagged =
      run.peak >= run.threshold ||
      denied > 0 ||
      run.alerts.size > 0 ||
      run.preFlagged;
    const active = state.batchRunning;
    const title = flagged
      ? "Flagged activity observed"
      : run.error
        ? "Result incomplete"
        : active
          ? "Watching for a flag…"
          : "No flag observed";
    const progress = active
      ? run.stop
        ? "Stopping after the current request"
        : "Sending batch"
      : run.error
        ? "Batch interrupted"
        : run.stop
          ? "Batch stopped"
          : "Batch complete";
    $("#batch-results").hidden = false;
    $("#batch-progress").textContent =
      `${progress} · ${run.rows.length} / ${run.total} attempted · ${run.key} · ${run.enforcing ? "Enforcing" : "Observing"}`;
    $("#batch-inspect").dataset.client = run.key;
    $("#batch-summary").className = flagged
      ? "batch-summary flagged"
      : "batch-summary";
    $("#batch-summary").innerHTML = `<h3>${title}</h3>
      <div class="batch-totals"><span><strong>${answered}</strong> HTTP 200</span><span><strong>${denied}</strong> HTTP 429</span><span><strong>${run.alerts.size}</strong> new alerts</span><span><strong>${run.peak.toFixed(1)} / 100</strong> highest observed risk</span>${errors ? `<span><strong>${errors}</strong> errors / unknown</span>` : ""}</div>
      <p>Starting risk: ${run.initial.risk.toFixed(1)}. Latest reading: ${run.latest.risk.toFixed(1)}. Alert threshold: ${run.threshold}.</p>
      <p>${run.preFlagged ? "This key was already flagged or under a penalty before this batch. " : ""}Results include other recent activity on this key. Reset the demo session for a fresh comparison.</p>
      ${!run.enforcing ? "<p>Observe mode is on: alerts can be raised while predictions still return HTTP 200.</p>" : ""}
      ${flagged && !run.alerts.size ? "<p>No new alert was captured. Existing penalties and the 10-second alert cooldown can prevent a new alert on each request.</p>" : ""}
      ${run.alerts.size ? `<p>New alert evidence: ${[...run.alerts.values()].map((alert) => `${escapeHTML(alert.id)} at ${escapeHTML(time(alert.at))} (risk ${alert.risk.toFixed(1)}, ${escapeHTML(alert.action)})`).join("; ")}.</p>` : ""}
      ${run.reasons.length ? `<ul>${run.reasons.map((reason) => `<li>${escapeHTML(reason)}</li>`).join("")}</ul>` : ""}
      ${run.error ? `<p class="batch-error">${escapeHTML(run.error)}</p>` : ""}
      ${!active && !flagged && !run.error ? `<p>${run.stop ? "This is a partial run. " : ""}The observed requests did not trigger a flag. Quantity alone does not prove model extraction.</p>` : ""}`;
    $("#batch-rows").innerHTML = run.rows
      .map(
        (row, i) =>
          `<tr><td>${i + 1}</td><td class="batch-input">${escapeHTML(row.text)}</td><td><strong>${row.status ? `HTTP ${row.status}` : "Response unknown"}</strong><div>${escapeHTML(row.status === 200 ? "Prediction received" : row.status === 429 ? `${row.data.action || "Withheld"} · retry after ${row.data.retry_after ?? "?"}s` : "Request error")}</div><details><summary>Response details</summary><pre>${escapeHTML(JSON.stringify(row.data, null, 2))}</pre></details></td><td>${row.risk == null ? "Unavailable" : `${row.risk.toFixed(1)} / 100`}</td></tr>`,
      )
      .join("");
  }

  $("#batch-stop").addEventListener("click", () => {
    if (!run || !state.batchRunning) return;
    run.stop = true;
    $("#batch-stop").disabled = true;
    if (wake) wake();
    renderBatch();
  });

  $("#batch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.batchRunning || state.manualRunning) return;
    const texts = inputs();
    if (!texts.length || texts.length > 30) {
      showError("Enter 1–30 inputs, one per line. Blank lines are ignored.");
      return;
    }
    const tooLong = texts.findIndex((text) => [...text].length > 2000);
    if (tooLong !== -1) {
      showError(
        `Input ${tooLong + 1} exceeds 2,000 characters. Shorten it before sending.`,
      );
      return;
    }
    showError();
    const key = $("#batch-key").value;
    const delay = Number($("#batch-delay").value);
    run = null;
    state.batchRunning = true;
    updateInputControls();
    $("#batch-stop").hidden = false;
    $("#batch-stop").disabled = true;
    $("#batch-send").textContent = "Connecting…";
    try {
      const snapshot = await (await api("/api/snapshot")).json();
      if (!snapshot.demo_mode)
        throw new Error(
          "Batch testing with public demo keys is available in local demo mode only.",
        );
      if (snapshot.demo.running)
        throw new Error(
          "Stop the running simulation before starting your batch.",
        );
      const client = snapshot.clients.find((c) => c.id === key);
      if (!client) throw new Error("Choose an available demo API key.");
      run = {
        key,
        total: texts.length,
        rows: [],
        alerts: new Map(),
        stop: false,
        error: "",
        session: snapshot.started_at,
        started: snapshot.now,
        enforcing: snapshot.enforcing,
        threshold: snapshot.policy.throttle_threshold,
        initial: client,
        latest: client,
        peak: client.risk,
        reasons: client.reasons,
        preFlagged:
          client.risk >= snapshot.policy.throttle_threshold ||
          client.retry_after > 0,
      };
      $("#batch-stop").disabled = false;
      $("#batch-send").textContent = "Sending…";
      renderBatch();
      $("#batch-results").scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      for (const text of texts) {
        if (run.stop) break;
        const row = { text, status: null, data: {}, risk: null };
        run.rows.push(row);
        try {
          const response = await fetch("/predict", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-API-Key": key },
            body: JSON.stringify({ text }),
            signal: AbortSignal.timeout(12000),
          });
          row.status = response.status;
          row.data = await response.json();
        } catch (error) {
          row.data = { detail: error.message };
          throw new Error(
            "A response could not be read. The server may have counted that request. Nothing was retried; check Live traffic before sending again.",
          );
        }
        const current = readSnapshot(await (await api("/api/snapshot")).json());
        row.risk = current.risk;
        if (![200, 429].includes(row.status))
          throw new Error(
            `HTTP ${row.status}: batch stopped. Open Response details for the server message.`,
          );
        renderBatch();
        if (run.rows.length < texts.length && !run.stop) {
          await new Promise((resolve) => {
            const timer = setTimeout(() => {
              wake = null;
              resolve();
            }, delay);
            wake = () => {
              clearTimeout(timer);
              wake = null;
              resolve();
            };
          });
        }
      }
    } catch (error) {
      if (run) run.error = error.message;
      else showError(error.message);
    } finally {
      state.batchRunning = false;
      wake = null;
      $("#batch-stop").hidden = true;
      $("#batch-send").textContent = "Send batch";
      updateInputControls();
      if (run) renderBatch();
      await refresh();
    }
  });
  updateInputControls();
})();
