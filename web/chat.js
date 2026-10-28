"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  let conversation = crypto.randomUUID(),
    history = [],
    busy = false;
  let bulkPass = null;
  const key = () => $("client-key").value.trim();
  function feedback(message) {
    $("chat-feedback").textContent = message;
  }
  function reset() {
    if (busy) return;
    conversation = crypto.randomUUID();
    history = [];
    $("messages")
      .querySelectorAll(".exchange")
      .forEach((node) => node.remove());
    $("welcome").hidden = false;
    feedback("New conversation.");
  }
  function setBusy(value) {
    busy = value;
    [
      "send",
      "send-batch",
      "new-chat",
      "client-key",
      "demo-key",
      "example-batch",
      "varied-batch",
      "use-bulk-pass",
    ].forEach((id) => ($(id).disabled = value));
  }
  function exchange(question) {
    $("welcome").hidden = true;
    const wrapper = document.createElement("div");
    wrapper.className = "exchange";
    const user = document.createElement("div");
    user.className = "bubble user";
    user.textContent = question;
    const assistant = document.createElement("div");
    assistant.className = "bubble assistant pending";
    assistant.textContent = "Thinking…";
    wrapper.append(user, assistant);
    $("messages").append(wrapper);
    wrapper.scrollIntoView({ behavior: "instant", block: "end" });
    return assistant;
  }
  async function ask(question, context, target, passId = null) {
    try {
      const response = await fetch("/chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": key() },
        body: JSON.stringify({
          message: question,
          history: context,
          conversation_id: conversation,
          bulk_pass_id: passId,
        }),
        signal: AbortSignal.timeout(190000),
      });
      const result = await response.json();
      target.classList.remove("pending");
      if (response.ok) {
        target.textContent = result.reply;
        if (
          result.processing?.speed_bump_wait_ms > 0 ||
          result.processing?.bulk_pass_used
        ) {
          const note = document.createElement("small");
          note.textContent = [
            result.processing.speed_bump_wait_ms > 0
              ? `Request pacing added ${(result.processing.speed_bump_wait_ms / 1000).toFixed(1)} seconds.`
              : "",
            result.processing.bulk_pass_used
              ? "Approved bulk allowance used."
              : "",
          ]
            .filter(Boolean)
            .join(" ");
          target.append(note);
        }
        if (result.truncated) {
          const note = document.createElement("small");
          note.textContent = "Reply reached the short-answer limit.";
          target.append(note);
        }
        return { status: response.status, reply: result.reply };
      }
      target.classList.add("request-error");
      target.textContent =
        response.status === 429 && result.action !== "bulk_limit"
          ? `Request paused. Please wait ${result.retry_after} seconds before trying again.`
          : typeof result.detail === "string"
            ? result.detail
            : `The request could not be accepted (HTTP ${response.status}).`;
      return { status: response.status };
    } catch (error) {
      target.classList.remove("pending");
      target.classList.add("request-error");
      target.textContent =
        "Could not receive a reply. Check the server; a timed-out request may still be processing.";
      return { status: 0 };
    }
  }
  $("chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    const question = $("message").value.trim();
    if (!question || !key()) {
      feedback("Enter your message and a client API key.");
      return;
    }
    setBusy(true);
    feedback("");
    $("message").value = "";
    const context = history.slice(-4).map((item) => ({
      role: item.role,
      content: item.content.slice(0, 800),
    }));
    // Bound the UTF-8 body even for multibyte scripts or emoji.
    while (
      context.length &&
      new TextEncoder().encode(
        JSON.stringify({
          message: question,
          history: context,
          conversation_id: conversation,
        }),
      ).length > 15000
    )
      context.shift();
    const result = await ask(question, context, exchange(question));
    if (result.reply)
      history.push(
        { role: "user", content: question },
        { role: "assistant", content: result.reply },
      );
    history = history.slice(-4);
    setBusy(false);
    $("message").focus();
    refreshStatus();
  });
  $("message").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("chat-form").requestSubmit();
    }
  });
  const lines = () =>
    $("batch-questions")
      .value.split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  function count() {
    $("batch-count").textContent = `${lines().length} / 30 questions`;
  }
  $("batch-questions").addEventListener("input", count);
  $("example-batch").addEventListener("click", () => {
    $("batch-questions").value = Array.from(
      { length: 30 },
      (_, i) =>
        `Explain how a neural network learns from examples. Keep answer ${i + 1} to one sentence.`,
    ).join("\n");
    count();
  });
  $("varied-batch").addEventListener("click", async () => {
    try {
      const response = await fetch("/chat/examples");
      if (!response.ok) throw new Error("Examples unavailable");
      $("batch-questions").value = (await response.json()).questions.join("\n");
      count();
    } catch {
      feedback(
        "Could not load examples. You can still paste your own questions.",
      );
    }
  });
  $("batch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    const questions = lines();
    if (
      !key() ||
      !questions.length ||
      questions.length > 30 ||
      questions.some((q) => [...q].length > 2000)
    ) {
      feedback(
        "Use an API key and 1–30 questions, each no longer than 2,000 characters.",
      );
      return;
    }
    setBusy(true);
    if (!(await refreshAccess()) && $("use-bulk-pass").checked) {
      feedback(
        "Could not verify the bulk allowance. No questions were sent. Retry, or turn off the bulk-pass option to use standard limits.",
      );
      setBusy(false);
      return;
    }
    const passId = $("use-bulk-pass").checked ? (bulkPass?.id ?? null) : null;
    let completed = 0,
      answered = 0,
      paused = 0,
      errors = 0;
    feedback(`Sending ${questions.length} questions…`);
    await Promise.all(
      questions.map(async (question) => {
        const result = await ask(question, [], exchange(question), passId);
        completed++;
        if (result.status === 200) answered++;
        else if (result.status === 429) paused++;
        else errors++;
        feedback(
          `${completed} / ${questions.length} complete · ${answered} answered · ${paused} paused · ${errors} errors`,
        );
      }),
    );
    setBusy(false);
    refreshStatus();
    refreshAccess();
  });
  function mode(batch) {
    $("chat-form").hidden = batch;
    $("batch-form").hidden = !batch;
    $("single-tab").setAttribute("aria-pressed", String(!batch));
    $("batch-tab").setAttribute("aria-pressed", String(batch));
  }
  $("single-tab").addEventListener("click", () => mode(false));
  $("batch-tab").addEventListener("click", () => mode(true));
  $("new-chat").addEventListener("click", reset);
  $("client-key").addEventListener("change", () => {
    reset();
    refreshAccess();
  });
  $("demo-key").addEventListener("change", () => {
    $("client-key").value = $("demo-key").value;
    reset();
    refreshAccess();
  });
  document.querySelectorAll("[data-prompt]").forEach((button) =>
    button.addEventListener("click", () => {
      mode(false);
      $("message").value = button.dataset.prompt;
      $("message").focus();
    }),
  );
  async function refreshStatus(initial = false) {
    try {
      const response = await fetch("/chat/status", { cache: "no-store" });
      if (!response.ok) throw new Error("Status unavailable");
      const data = await response.json();
      $("model-status").textContent = data.model.ready
        ? "Ready"
        : data.model.installed
          ? "Ready when you are"
          : "Setup needed";
      $("model-status").dataset.state = data.model.installed
        ? "ready"
        : "unavailable";
      $("setup-message").hidden = data.model.installed;
      $("setup-message").textContent =
        `Install the local model in the project terminal: ${data.model.setup}`;
      if (initial && data.demo) {
        $("demo-clients").hidden = false;
        $("client-key").value = "normal-01";
      }
      if (initial && !data.demo) $("connection-settings").open = true;
      if (initial) refreshAccess();
    } catch {
      $("model-status").textContent = "Server unavailable";
      $("model-status").dataset.state = "unavailable";
    }
  }
  async function refreshAccess() {
    const requestedKey = key();
    if (!requestedKey) {
      bulkPass = null;
      $("bulk-access-status").textContent =
        "Enter a client key to check bulk access.";
      return false;
    }
    try {
      const response = await fetch("/chat/access", {
        headers: { "X-API-Key": requestedKey },
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      });
      if (!response.ok) throw new Error("Access unavailable");
      const data = await response.json();
      if (requestedKey !== key()) return false;
      bulkPass = data.bulk_pass;
      $("bulk-access-status").textContent = bulkPass
        ? `Bulk pass ${bulkPass.status}: ${bulkPass.used} / ${bulkPass.limit} used, ${bulkPass.remaining} remaining. Expires ${new Date(bulkPass.expires_at * 1000).toLocaleTimeString()}.`
        : "No current bulk pass. Standard request limits apply.";
      return true;
    } catch {
      if (requestedKey !== key()) return false;
      bulkPass = null;
      $("bulk-access-status").textContent =
        "Could not check bulk access. Standard limits apply if you send without a pass.";
      return false;
    }
  }
  refreshStatus(true);
  setInterval(() => {
    if (!busy) refreshAccess();
  }, 5000);
})();
