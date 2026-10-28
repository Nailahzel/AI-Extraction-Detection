"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const rows = new Map();
  let busy = false,
    checkedAt = 0,
    runId = null;
  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  };
  async function refresh() {
    if (busy || Date.now() - checkedAt < 2000) return;
    busy = true;
    try {
      const response = await window.ModelShieldMonitor.api(
        "/api/requirements/reports/chat-feature-demo",
      );
      const report = await response.json();
      if (!Array.isArray(report.features))
        throw new Error("Incomplete demo report");
      if (runId !== report.id) {
        rows.clear();
        $("feature-demo-list").replaceChildren();
        runId = report.id;
      }
      const completed = report.features.filter(
        (row) => row.status === "passed",
      ).length;
      $("feature-demo-status").textContent =
        `${completed} / ${report.features.length} checks passed · ${report.status} · updated ${new Date(report.updated_at * 1000).toLocaleTimeString()}`;
      report.features.forEach((feature, index) => {
        let row = rows.get(feature.id);
        if (!row) {
          row = node("details", undefined, "feature-demo-card");
          row.dataset.feature = feature.id;
          const summary = node("summary"),
            title = node(
              "strong",
              `${String(index + 1).padStart(2, "0")} · ${feature.title}`,
            );
          summary.append(title, node("span", "Waiting", "feature-state"));
          row.append(
            summary,
            node("p", feature.explanation),
            node("div", undefined, "feature-proof"),
          );
          rows.set(feature.id, row);
          $("feature-demo-list").append(row);
        }
        row.querySelector(".feature-state").textContent = feature.status;
        row.dataset.status = feature.status;
        const signature = JSON.stringify([
          feature.status,
          feature.result,
          feature.samples,
          feature.observations,
        ]);
        if (row.dataset.signature === signature) return;
        row.dataset.signature = signature;
        const proof = row.querySelector(".feature-proof");
        proof.replaceChildren();
        if (feature.result) proof.append(node("p", feature.result));
        (feature.observations || []).forEach((text) =>
          proof.append(node("p", text, "muted")),
        );
        [...(feature.samples || [])]
          .sort(
            (a, b) =>
              Number(b.action === "block") - Number(a.action === "block"),
          )
          .forEach((sample) => {
            const button = node(
              "button",
              `${sample.client_id} · ${sample.status} · ${sample.question}`,
            );
            button.type = "button";
            button.addEventListener("click", () =>
              window.ModelShieldMonitor.show(
                "Saved demonstration request",
                sample,
                "event",
              ),
            );
            proof.append(button);
          });
      });
    } catch (error) {
      $("feature-demo-status").textContent = "Saved results could not refresh.";
    } finally {
      busy = false;
      checkedAt = Date.now();
    }
  }
  document.addEventListener("modelshield:snapshot", refresh);
})();
