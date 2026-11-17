/**
 * API client for THE CLAUDE COMPANY Dost fleet API.
 *
 * Talks to the dispatcher running on :8083 (see dost/dost.py and
 * dost/sdk/python/client.py for the backend reference).
 *
 * Endpoints used:
 *   GET    /metrics          Fleet status (pools, cooldowns, task counts)
 *   POST   /tasks/dispatch   Submit a prompt to the fleet
 *   POST   /debates          Start a multi-agent debate
 *   GET    /tasks            List recent tasks
 *   GET    /health           Fleet health
 */

import axios from "axios";

const BASE_URL = "http://127.0.0.1:8083";
const REQUEST_TIMEOUT = 10000;

const api = axios.create({
  baseURL: BASE_URL,
  timeout: REQUEST_TIMEOUT,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

/** Fetch live fleet status from :8083/metrics. */
export async function getMetrics() {
  const { data } = await api.get("/metrics");
  return data;
}

/** Submit a prompt to the fleet. POST /tasks/dispatch */
export async function dispatchTask(prompt, options = {}) {
  const body = {
    prompt,
    priority: options.priority || "normal",
    ...(options.agentId && { agent_id: options.agentId }),
    ...(options.parentTaskId && { parent_task_id: options.parentTaskId }),
    ...(options.chain && { chain: options.chain }),
  };
  const { data } = await api.post("/tasks/dispatch", body);
  return data;
}

/** Start a multi-agent debate. POST /debates */
export async function startDebate(prompt, agents) {
  const body = { prompt };
  if (agents) body.agents = agents;
  const { data } = await api.post("/debates", body);
  return data;
}

/** List recent tasks. GET /tasks */
export async function getTasks(workspaceId) {
  const params = workspaceId ? { workspace_id: workspaceId } : {};
  const { data } = await api.get("/tasks", { params });
  return data;
}

/** Fleet health. GET /health */
export async function healthCheck() {
  const { data } = await api.get("/health");
  return data;
}

export { BASE_URL };
