"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const rows = new Map(),
    revoking = new Set();
  let initialized = false;
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const message = (text) => {
    $("protection-feedback").textContent = text;
  };
  async function post(path, body = {}) {
    const response = await window.ModelShieldMonitor.api(path, {
      method: "POST",
      body: JSON.stringify(body),
    });
    return response.json();
  }
  function render(data) {
    if (!initialized) {
      data.clients.forEach((client) => {
        const option = node("option", `${client.id} · ${client.name}`);
        option.value = client.id;
        $("bulk-client").append(option);
      });
      if (data.clients.some((c) => c.id === "batch-01"))
        $("bulk-client").value = "batch-01";
      const bumps = data.policy.speed_bumps;
      [
        ["Normal", `Risk below ${bumps[0].threshold}`],
        ...bumps.map((b, i) => [
          `${b.seconds} s speed bump`,
          `Risk ${b.threshold}–${(bumps[i + 1]?.threshold ?? data.policy.throttle_threshold) - 1}`,
        ]),
        [
          "Throttle",
          `Risk ${data.policy.throttle_threshold}+ · pause ${data.policy.throttle_seconds} s`,
        ],
        [
          "Temporary block",
          `Risk ${data.policy.block_threshold}+ · pause ${data.policy.block_seconds} s`,
        ],
      ].forEach(([title, text]) => {
        const card = node("div", undefined, "protection-stage");
        card.append(node("strong", title), node("span", text));
        $("protection-stages").append(card);
      });
      initialized = true;
    }
    $("speed-waiting").textContent = data.totals.waiting;
    $("speed-delayed").textContent = data.totals.delayed;
    $("speed-time").textContent =
      `${(data.totals.delay_ms / 1000).toFixed(1)} s`;
    $("bulk-active").textContent = data.bulk_passes.filter(
      (p) => p.status === "active",
    ).length;
    for (const [id, row] of rows)
      if (!data.bulk_passes.some((p) => p.id === id)) {
        row.remove();
        rows.delete(id);
      }
    $("bulk-pass-list").querySelector(".empty-row")?.remove();
    data.bulk_passes.forEach((pass) => {
      let row = rows.get(pass.id);
      if (!row) {
        row = node("tr");
        row.dataset.passId = pass.id;
        const identity = node("td"),
          usage = node("td"),
          expiry = node("td"),
          controls = node("td");
        identity.append(
          node("strong", pass.client_id),
          node("small", pass.purpose),
          node("small", pass.id),
        );
        const status = node("span"),
          revoke = node("button", "Revoke");
        revoke.type = "button";
        revoke.addEventListener("click", async () => {
          revoking.add(pass.id);
          revoke.disabled = true;
          try {
            await post(
              `/api/chat/passes/${encodeURIComponent(pass.id)}/revoke`,
            );
            message(`Pass revoked for ${pass.client_id}.`);
          } catch (error) {
            message(error.message);
          } finally {
            revoking.delete(pass.id);
            window.ModelShieldMonitor.refresh();
          }
        });
        controls.append(status, revoke);
        row.append(identity, usage, expiry, controls);
        rows.set(pass.id, row);
        $("bulk-pass-list").prepend(row);
      }
      row.children[1].textContent = `${pass.used} / ${pass.limit} used · ${pass.remaining} remaining · max ${pass.concurrency} at once`;
      row.children[2].textContent = new Date(
        pass.expires_at * 1000,
      ).toLocaleTimeString();
      row.children[3].firstChild.textContent = pass.status;
      row.children[3].lastChild.disabled =
        revoking.has(pass.id) || ["revoked", "expired"].includes(pass.status);
    });
    if (!rows.size) {
      const tr = node("tr", undefined, "empty-row"),
        td = node("td", "No active passes.", "empty");
      td.colSpan = 4;
      tr.append(td);
      $("bulk-pass-list").append(tr);
    }
    $("protection-queue").replaceChildren();
    if (!data.queue.length)
      $("protection-queue").append(node("p", "No requests waiting.", "empty"));
    data.queue.forEach((request) => {
      const row = node("div", undefined, "queue-item");
      const detail = node("span", request.question);
      detail.append(
        node(
          "small",
          `${request.bulk_pass_id ? "Approved pass attached" : "Standard access"} · speed-bump wait ${(request.speed_bump.wait_ms / 1000).toFixed(1)} s`,
        ),
      );
      row.append(
        node("strong", request.client_id),
        detail,
        node(
          "span",
          request.stage.replaceAll("_", " "),
          `status ${request.stage}`,
        ),
      );
      $("protection-queue").append(row);
    });
  }
  $("bulk-pass-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("issue-bulk-pass").disabled = true;
    message("Saving approval…");
    try {
      const grant = await post("/api/chat/passes", {
        client_id: $("bulk-client").value,
        limit: Number($("bulk-limit").value),
        minutes: Number($("bulk-minutes").value),
        concurrency: Number($("bulk-concurrency").value),
        purpose: $("bulk-purpose").value.trim(),
      });
      message(`Approved ${grant.limit} requests for ${grant.client_id}.`);
    } catch (error) {
      message(error.message);
    } finally {
      $("issue-bulk-pass").disabled = false;
      window.ModelShieldMonitor.refresh();
    }
  });
  document.addEventListener("modelshield:snapshot", (event) =>
    render(event.detail),
  );
})();
