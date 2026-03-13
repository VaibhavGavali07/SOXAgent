const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const request = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });
  if (!response.ok) {
    let detail = "";
    try {
      const errorBody = await response.json();
      detail = errorBody?.detail || "";
    } catch {
      detail = "";
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
};

export const api = {
  apiBase: API_BASE,
  runEventsUrl: (runId) => `${API_BASE}/api/runs/${runId}/events`,
  health: () => request("/api/health"),
  getConfigs: () => request("/api/configs"),
  saveConfig: (payload) => request("/api/configs", { method: "POST", body: JSON.stringify(payload) }),
  testLLM: (payload) => request("/api/llm/test", { method: "POST", body: JSON.stringify(payload) }),
  testServiceNow: (payload) => request("/api/servicenow/test", { method: "POST", body: JSON.stringify(payload) }),
  testNotifications: (payload) => request("/api/notifications/test", { method: "POST", body: JSON.stringify(payload) }),
  clearComplianceData: (payload = { include_configs: false }) =>
    request("/api/data/clear", { method: "POST", body: JSON.stringify(payload) }),
  fetchServiceNow: (filters = {}) => request("/api/fetch/servicenow", { method: "POST", body: JSON.stringify({ filters }) }),
  rerunTicket: (ticketDbId) => request(`/api/analyze/ticket/${ticketDbId}`, { method: "POST" }),
  dashboardSummary: () => request("/api/dashboard/summary"),
  violations: (params = {}) => request(`/api/violations?${new URLSearchParams(params).toString()}`),
  violation: (alertId) => request(`/api/violations/${alertId}`),
  acknowledgeViolation: (alertId) => request(`/api/violations/${alertId}/acknowledge`, { method: "PATCH" }),
  resolveViolation: (alertId) => request(`/api/violations/${alertId}/resolve`, { method: "PATCH" }),
  tickets: (params = {}) => request(`/api/tickets?${new URLSearchParams(params).toString()}`),
  ticket: (ticketDbId) => request(`/api/tickets/${ticketDbId}`),
  rules: () => request("/api/rules"),
  createRule: (payload) => request("/api/rules", { method: "POST", body: JSON.stringify(payload) }),
  updateRule: (ruleId, payload) => request(`/api/rules/${encodeURIComponent(ruleId)}`, { method: "PUT", body: JSON.stringify(payload) })
};
