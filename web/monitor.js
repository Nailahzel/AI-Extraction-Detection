"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  let alertSignature = null;
  let snapshot = null,
    token = "",
    refreshing = false;
  const time = (value) => new Date(value * 1000).toLocaleTimeString();
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (response.status === 401) {
      $("operator-form").hidden = false;
      throw new Error("Operator access required");
    }
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(
        typeof error.detail === "string"
          ? error.detail
          : `Server returned HTTP ${response.status}`,
      );
    }
    return response;
  }
  function signalEvidence(data) {
    const box = node("div", undefined, "signal-list");
    Object.entries(data.signals || {}).forEach(([name, signal]) => {
      const row = node("div", undefined, "signal-row");
      row.append(
        node("strong", name),
        node("span", `${signal.value} ${signal.unit}`),
        node("b", `+${signal.points} points`),
      );
      box.append(row);
    });
    (data.reasons || []).forEach((reason) =>
      box.append(node("p", reason, "reason")),
    );
    return box;
  }
  function show(title, data, type) {
    $("detail-title").textContent = title;
    const body = $("detail-body");
    body.replaceChildren();
    if (type === "client") {
      body.append(
        node("p", `${data.id} · ${data.status} · risk ${data.risk}/100`),
      );
      body.append(signalEvidence(data));
      body.append(
        node(
          "p",
          `Before allowance: ${data.raw_risk ?? data.risk}/100 · rate credit ${data.rate_credit || 0} points · speed bump ${data.speed_bump_seconds || 0} s · ${data.waiting || 0} waiting.`,
        ),
      );
      body.append(
        node(
          "p",
          data.retry_after
            ? `Current restriction expires in about ${data.retry_after} seconds.`
            : "No active restriction.",
          "muted",
        ),
      );
    } else {
      body.append(
        node(
          "p",
          `${time(data.at)} · ${data.client_id} · ${data.action} · risk at arrival ${data.risk}/100`,
          "muted",
        ),
      );
      body.append(
        node("h3", "Question"),
        node("p", data.question, "transcript"),
      );
      if (data.reply)
        body.append(
          node("h3", "Reply released"),
          node("p", data.reply, "transcript"),
        );
      if (data.error) body.append(node("p", data.error, "reason"));
      if (data.speed_bump)
        body.append(
          node(
            "p",
            `Speed bump: ${data.speed_bump.seconds} s spacing · ${(data.speed_bump.wait_ms / 1000).toFixed(2)} s measured waiting (separate from generation).`,
          ),
        );
      if (data.bulk_pass_id)
        body.append(
          node(
            "p",
            `Bulk pass: ${data.bulk_pass_id} · ${data.bulk_pass ? `request ${data.bulk_pass.used} of ${data.bulk_pass.limit} reserved at arrival` : "not accepted"}.`,
          ),
        );
      body.append(node("h3", "Signals at arrival"), signalEvidence(data));
      if (data.enforcement)
        body.append(
          node(
            "h3",
            `Signals when withheld · risk ${data.enforcement.risk}/100`,
          ),
          signalEvidence(data.enforcement),
        );
      body.append(
        node(
          "p",
          `Request ${data.id} · Conversation ${data.conversation_id}`,
          "muted",
        ),
      );
      if (data.latency_ms !== null && data.latency_ms !== undefined)
        body.append(
          node(
            "p",
            `Server handling: ${data.latency_ms} ms (includes queue and generation, excludes final audit commit and response delivery).`,
            "muted",
          ),
        );
    }
    body.append(
      node(
        "p",
        "These are lexical and timing heuristics. Repeated questions can be legitimate, and slower extraction may evade detection.",
        "muted",
      ),
    );
    $("detail-dialog").showModal();
  }
  function renderEvents() {
    if (!snapshot) return;
    const filter = $("event-filter").value;
    const events = snapshot.events.filter(
      (row) => filter === "all" || row.status === filter,
    );
    $("events").replaceChildren();
    if (!events.length)
      $("events").append(
        node(
          "p",
          "No requests match this view. Send a message from the chatbot to begin.",
          "empty",
        ),
      );
    events.forEach((event) => {
      const row = node("button", undefined, "event-row");
      row.type = "button";
      const stamp = node("div", undefined, "event-meta");
      stamp.append(
        node("span", time(event.at)),
        node("strong", event.client_id),
      );
      const text = node("div", undefined, "event-text");
      text.append(node("strong", event.question));
      if (event.speed_bump?.wait_ms || event.bulk_pass_id)
        text.append(
          node(
            "small",
            `${event.speed_bump?.wait_ms ? `Speed bump: ${(event.speed_bump.wait_ms / 1000).toFixed(1)} s waited` : ""}${event.bulk_pass_id ? " · Bulk pass attached" : ""}`,
            "event-protection",
          ),
        );
      text.append(
        node(
          "p",
          event.reply ||
            event.error ||
            (event.status === "pending"
              ? `Request stage: ${(event.stage || "queued").replaceAll("_", " ")}…`
              : "No answer released."),
        ),
      );
      const label = node(
        "span",
        event.status === "pending" ? "processing" : event.status,
        `status ${event.status}`,
      );
      row.append(stamp, text, label);
      row.addEventListener("click", () =>
        show("Request evidence", event, "event"),
      );
      $("events").append(row);
    });
  }
  function render() {
    const data = snapshot;
    ["requests", "answered", "denied"].forEach(
      (name) => ($("total-" + name).textContent = data.totals[name]),
    );
    $("total-flagged").textContent = data.clients.filter((c) =>
      ["block", "throttle"].includes(c.status),
    ).length;
    $("queue-status").textContent =
      `${data.totals.pending} processing · ${data.totals.errors} errors`;
    $("clients").replaceChildren();
    data.clients
      .filter((client) => client.total > 0)
      .sort((a, b) => b.risk - a.risk)
      .forEach((client) => {
        const tr = node("tr");
        const identity = node("td");
        const button = node("button", client.id, "client-button");
        button.addEventListener("click", () =>
          show("Client signals", client, "client"),
        );
        identity.append(button, node("small", client.name));
        const risk = node("td");
        const track = node("div", undefined, "risk-track");
        const fill = node("span");
        fill.style.width = `${client.risk}%`;
        track.append(fill);
        risk.append(node("b", String(client.risk)), track);
        const status = node("td");
        status.append(node("span", client.status, `status ${client.status}`));
        tr.append(identity, node("td", String(client.total)), risk, status);
        $("clients").append(tr);
      });
    if (!$("clients").children.length) {
      const tr = node("tr");
      const td = node(
        "td",
        "No chat traffic yet. Open the chatbot to get started.",
        "empty",
      );
      td.colSpan = 4;
      tr.append(td);
      $("clients").append(tr);
    }
    // Incident records are immutable. Preserve their buttons between polls so
    // live refresh cannot interrupt a click, keyboard focus, or scroll position.
    const nextAlertSignature = JSON.stringify(
      data.alerts.map((alert) => alert.incident_id),
    );
    if (nextAlertSignature !== alertSignature) {
      alertSignature = nextAlertSignature;
      $("alerts").replaceChildren();
      $("alert-count").textContent = data.alerts.length;
      if (!data.alerts.length)
        $("alerts").append(
          node(
            "p",
            "No red flags yet. Normal chat activity appears below.",
            "empty",
          ),
        );
      data.alerts.forEach((alert) => {
        const button = node("button", undefined, "alert-card");
        button.append(
          node(
            "span",
            `${alert.action === "block" ? "TEMPORARILY BLOCKED" : "THROTTLED"} · ${time(alert.at)}`,
            "alert-kind",
          ),
          node("strong", alert.client_id),
          node("p", alert.reasons.join(" · ")),
          node("small", `Risk ${alert.risk}/100 · Inspect evidence ↗`),
        );
        button.addEventListener("click", () =>
          show("Red flag evidence", alert, "alert"),
        );
        $("alerts").append(button);
      });
    }
    $("runtime-name").textContent = data.model.name;
    $("runtime-status").textContent = data.model.ready
      ? "Local model running · enforcement active"
      : data.model.installed
        ? "Model installed · starts on first chat message"
        : `Setup needed: ${data.model.setup}`;
    renderEvents();
  }
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      snapshot = await (await api("/api/chat/snapshot")).json();
      render();
      document.dispatchEvent(
        new CustomEvent("modelshield:snapshot", { detail: snapshot }),
      );
      $("operator-form").hidden = true;
      $("connection").textContent = "● Monitor connected";
      $("last-updated").textContent = `Updated ${time(Date.now() / 1000)}`;
    } catch (error) {
      $("connection").textContent = "Monitor disconnected";
      $("last-updated").textContent = error.message;
    } finally {
      refreshing = false;
    }
  }
  function navigate() {
    const section = ["#protection", "#feature-demo"].includes(location.hash)
      ? location.hash
      : "#live";
    document.querySelectorAll(".view-switch a").forEach((link) => {
      if (link.hash === section) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    if (section === "#live") window.scrollTo(0, 0);
    else $(section.slice(1)).scrollIntoView({ block: "start" });
  }
  window.addEventListener("hashchange", navigate);
  navigate();
  $("operator-form").addEventListener("submit", (event) => {
    event.preventDefault();
    token = $("operator-token").value.trim();
    refresh();
  });
  $("event-filter").addEventListener("change", renderEvents);
  $("close-detail").addEventListener("click", () => $("detail-dialog").close());
  $("export").addEventListener("click", async () => {
    try {
      const blob = await (await api("/api/chat/export")).blob();
      const url = URL.createObjectURL(blob);
      const link = node("a");
      link.href = url;
      link.download = "modelshield-chat-evidence.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      $("notification").textContent = error.message;
    }
  });
  window.ModelShieldMonitor = { api, refresh, show };
  refresh();
  setInterval(refresh, 1500);
})();
