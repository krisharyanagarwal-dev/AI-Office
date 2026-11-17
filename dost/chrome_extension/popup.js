const BASE_URL = "http://localhost:8083";
const METRICS_URL = `${BASE_URL}/metrics`;
const TASK_URL = `${BASE_URL}/api/task`;

const fleetStatusEl = document.getElementById("fleet-status");
const completionRateEl = document.getElementById("completion-rate");
const errorRateEl = document.getElementById("error-rate");
const lastUpdatedEl = document.getElementById("last-updated");
const metricsErrorEl = document.getElementById("metrics-error");
const dispatchForm = document.getElementById("dispatch-form");
const promptInput = document.getElementById("prompt");
const dispatchBtn = document.getElementById("dispatch-btn");
const dispatchStatusEl = document.getElementById("dispatch-status");
const dispatchErrorEl = document.getElementById("dispatch-error");
const taskListEl = document.getElementById("task-list");

let lastUpdated = null;

/* ---------- Fleet metrics ---------- */

async function fetchMetrics() {
  metricsErrorEl.textContent = "";
  try {
    const res = await fetch(METRICS_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderMetrics(data);
    lastUpdated = new Date();
    lastUpdatedEl.textContent = `Updated ${lastUpdated.toLocaleTimeString()}`;
  } catch (err) {
    metricsErrorEl.textContent = `Could not reach fleet metrics at ${METRICS_URL}: ${err.message}`;
    fleetStatusEl.textContent = "--";
    completionRateEl.textContent = "--";
    errorRateEl.textContent = "--";
  }
}

function renderMetrics(data) {
  const status = data.fleet_status ?? data.status ?? data.fleet ?? "--";
  const completion = data.completion_rate ?? data.completion ?? "--";
  const errors = data.error_rate ?? data.errors ?? "--";

  fleetStatusEl.textContent = formatStatus(status);
  completionRateEl.textContent = formatPercent(completion);
  errorRateEl.textContent = formatPercent(errors);

  if (Array.isArray(data.recent_tasks)) {
    renderTasks(data.recent_tasks);
  }
}

function formatStatus(value) {
  const map = {
    ok: "Operational",
    healthy: "Operational",
    running: "Operational",
    degraded: "Degraded",
    warning: "Degraded",
    error: "Error",
    critical: "Error",
    down: "Down",
    offline: "Down",
  };
  const key = String(value).toLowerCase();
  return map[key] ?? String(value);
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "--") return "--";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${num.toFixed(1)}%`;
}

/* ---------- Task dispatch ---------- */

dispatchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  dispatchStatusEl.textContent = "";
  dispatchErrorEl.textContent = "";
  dispatchBtn.disabled = true;
  dispatchBtn.textContent = "Dispatching...";

  const prompt = promptInput.value.trim();
  if (!prompt) {
    dispatchBtn.disabled = false;
    dispatchBtn.textContent = "Dispatch";
    return;
  }

  try {
    const res = await fetch(TASK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}${text ? ": " + text : ""}`);
    }

    const data = await res.json().catch(() => ({}));
    dispatchStatusEl.textContent = data.message ?? "Task dispatched.";
    promptInput.value = "";

    if (Array.isArray(data.task)) {
      renderTasks(data.task);
    } else if (data.task) {
      renderTasks([data.task]);
    }

    await fetchMetrics();
  } catch (err) {
    dispatchErrorEl.textContent = `Failed to dispatch task: ${err.message}`;
  } finally {
    dispatchBtn.disabled = false;
    dispatchBtn.textContent = "Dispatch";
  }
});

/* ---------- Recent tasks ---------- */

function renderTasks(tasks) {
  taskListEl.innerHTML = "";
  if (!tasks || tasks.length === 0) {
    taskListEl.innerHTML = '<li class="empty">No recent tasks.</li>';
    return;
  }
  for (const task of tasks.slice(0, 10)) {
    const li = document.createElement("li");
    li.className = "task-item";
    const statusClass = `status-${String(task.status ?? "pending").toLowerCase()}`;
    const ts = task.created_at ?? task.timestamp ?? task.createdAt ?? "";
    li.innerHTML = `
      <div class="task-main">
        <div class="task-prompt">${escapeHtml(String(task.prompt ?? task.task ?? task.description ?? ""))}</div>
        <div class="task-meta"><span class="task-status ${statusClass}">${escapeHtml(String(task.status ?? "pending"))}</span>${ts ? ` · ${escapeHtml(ts)}` : ""}</div>
      </div>
    `;
    taskListEl.appendChild(li);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/* ---------- Init ---------- */

fetchMetrics();
setInterval(fetchMetrics, 30000);
