import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { api } from "../api/client";
import RealtimeStatus from "../components/RealtimeStatus";

const AcceptRiskModal = ({ alert, onConfirm, onCancel }) => {
  const [note, setNote] = useState("");
  const textareaRef = useRef(null);

  useEffect(() => {
    if (alert) {
      setNote("");
      setTimeout(() => textareaRef.current?.focus(), 50);
    }
  }, [alert]);

  if (!alert) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <h3 className="text-lg font-semibold text-slate-900">Accept Risk</h3>
        <p className="mt-1 text-sm text-slate-500">
          <span className="font-medium text-slate-700">{alert.ticket_id}</span> — {alert.rule_id}
        </p>
        <p className="mt-3 text-sm text-slate-600">
          Provide a business justification for accepting this violation as-is. This will be stored as a formal risk acceptance record.
        </p>
        <textarea
          ref={textareaRef}
          className="input mt-3 h-28 w-full resize-none"
          placeholder="e.g. Approved by CISO on 2024-03-15 — compensating control in place via monthly access review..."
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <div className="mt-4 flex justify-end gap-3">
          <button className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50" onClick={onCancel}>Cancel</button>
          <button
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
            disabled={!note.trim()}
            onClick={() => onConfirm(note.trim())}
          >
            Accept Risk
          </button>
        </div>
      </div>
    </div>
  );
};

const severityColors = {
  HIGH: "#ef4444",
  MEDIUM: "#f59e0b",
  LOW: "#3b82f6"
};

const ackStatusStyles = {
  open: "bg-rose-100 text-rose-700",
  acknowledged: "bg-amber-100 text-amber-700",
  resolved: "bg-emerald-100 text-emerald-700",
};

const MetricCard = ({ label, value, hint, tone = "default", onClick }) => {
  const tones = {
    default: "border-slate-200 bg-white",
    high: "border-rose-200 bg-rose-50/60",
    medium: "border-amber-200 bg-amber-50/60",
    green: "border-emerald-200 bg-emerald-50/60",
  };

  return (
    <button
      className={`w-full rounded-2xl border p-5 text-left transition ${tones[tone]} ${onClick ? "hover:shadow-sm" : ""}`}
      onClick={onClick}
      type="button"
    >
      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</div>
      <div className="mt-4 text-4xl font-semibold text-slate-950">{value}</div>
      <div className="mt-3 text-sm text-slate-500">{hint}</div>
    </button>
  );
};

const Dashboard = ({ summary, loading, refreshing, runId, runProgress, runEvents, onRefresh, onOpenTickets, onRefreshSummary }) => {
  const stats = summary?.stats || {};
  const totalChecks = stats.total_checks || 0;
  const complianceScore = totalChecks ? Math.round((stats.passed_checks / totalChecks) * 100) : "-";
  const coverage = summary ? `${stats.tickets_analyzed || 0} tickets analysed` : "Run analysis to compute";
  const auditReadiness = stats.audit_readiness ?? (totalChecks ? 100 : 100);
  const alerts = summary?.recent_alerts || [];
  const severityData = (summary?.severity_breakdown || []).filter((item) => item.value > 0);
  const controlData = summary?.control_breakdown || [];

  const [violations, setViolations] = useState([]);
  const [loadingViolations, setLoadingViolations] = useState(true);
  const [actionLoading, setActionLoading] = useState({});
  const [ackModal, setAckModal] = useState(null);
  const [reanalyzingIds, setReanalyzingIds] = useState(new Set());
  const [resolveResults, setResolveResults] = useState({});

  const loadViolations = async () => {
    try {
      setLoadingViolations(true);
      const data = await api.violations();
      setViolations(data);
    } catch {
      // silent
    } finally {
      setLoadingViolations(false);
    }
  };

  useEffect(() => {
    loadViolations();
  }, [summary]);

  const handleAckConfirm = async (note) => {
    const alert = ackModal;
    setAckModal(null);
    setActionLoading((prev) => ({ ...prev, [`ack-${alert.id}`]: true }));
    try {
      await api.acknowledgeViolation(alert.id, note);
      setViolations((prev) =>
        prev.map((v) =>
          v.id === alert.id
            ? { ...v, ack_status: "acknowledged", acknowledged_at: new Date().toISOString(), risk_note: note }
            : v
        )
      );
      toast.success("Risk accepted — violation acknowledged");
      onRefreshSummary?.();
    } catch {
      toast.error("Failed to acknowledge violation");
    } finally {
      setActionLoading((prev) => ({ ...prev, [`ack-${alert.id}`]: false }));
    }
  };

  const waitForRun = (runId) =>
    new Promise((resolve) => {
      const source = new EventSource(api.runEventsUrl(runId));
      let done = false;
      const finish = () => { if (!done) { done = true; source.close(); resolve(); } };
      source.onmessage = (e) => {
        const payload = JSON.parse(e.data);
        if (payload.status === "completed" || payload.status === "failed") finish();
      };
      source.onerror = finish;
      setTimeout(finish, 90_000);
    });

  const handleResolve = async (alert) => {
    setResolveResults((prev) => { const n = { ...prev }; delete n[alert.id]; return n; });
    setReanalyzingIds((prev) => new Set([...prev, alert.id]));
    try {
      const runResult = await api.rerunTicket(alert.ticket_db_id);
      await waitForRun(runResult.run_id);

      const detail = await api.violation(alert.id);
      const failedRules = (detail.rule_results || [])
        .filter((r) => r.status === "FAIL" || r.status === "NEEDS_REVIEW")
        .map((r) => r.rule_id);

      if (failedRules.length === 0) {
        await api.resolveViolation(alert.id);
        setViolations((prev) =>
          prev.map((v) =>
            v.id === alert.id
              ? { ...v, ack_status: "resolved", resolved_at: new Date().toISOString(), acknowledged_at: v.acknowledged_at || new Date().toISOString() }
              : v
          )
        );
        setResolveResults((prev) => ({ ...prev, [alert.id]: { allPassed: true, failedRules: [] } }));
        toast.success(`${alert.ticket_id} — all controls passed, violation resolved`);
        onRefreshSummary?.();
      } else {
        setResolveResults((prev) => ({ ...prev, [alert.id]: { allPassed: false, failedRules } }));
        toast.error(`${alert.ticket_id} — ${failedRules.length} rule(s) still failing`);
      }
    } catch (err) {
      toast.error(`Re-analysis failed: ${err?.message || "unknown error"}`);
    } finally {
      setReanalyzingIds((prev) => { const n = new Set(prev); n.delete(alert.id); return n; });
    }
  };

  const statusText =
    runProgress?.status === "running"
      ? "Active Compliance Analysis in progress"
      : runProgress?.status === "completed"
        ? "Last compliance analysis completed"
        : runProgress?.status === "failed"
          ? "Last compliance analysis failed"
          : "No analysis run yet";

  const readinessColor = auditReadiness >= 75 ? "green" : auditReadiness >= 40 ? "medium" : "high";

  return (
    <div className="space-y-6">
      <AcceptRiskModal
        alert={ackModal}
        onConfirm={handleAckConfirm}
        onCancel={() => setAckModal(null)}
      />
      <div className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="text-sm text-slate-500">{statusText}</div>
          <div className="flex flex-wrap gap-3">
            <button className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-700" onClick={onRefresh}>
              {refreshing ? "Refreshing..." : "Refresh Data"}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-4">
        <MetricCard
          label="Tickets Analysed"
          value={loading && !summary ? "..." : stats.tickets_analyzed || 0}
          hint="ServiceNow"
          onClick={() => onOpenTickets?.({})}
        />
        <MetricCard
          label="Violations Detected"
          value={loading && !summary ? "..." : stats.violations_detected || 0}
          hint={`${stats.failed_checks || 0} failed control checks`}
          onClick={() => onOpenTickets?.({ min_failed: 1 })}
        />
        <MetricCard
          label="High Risk"
          value={loading && !summary ? "..." : stats.high_risk_violations || 0}
          hint="Immediate action required"
          tone="high"
          onClick={() => onOpenTickets?.({ min_failed: 1, priority: "HIGH" })}
        />
        <MetricCard
          label="Medium Risk"
          value={loading && !summary ? "..." : stats.medium_risk_violations || 0}
          hint="Review within 5 days"
          tone="medium"
          onClick={() => onOpenTickets?.({ min_failed: 1, priority: "MEDIUM" })}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_1.2fr_1fr]">
        <MetricCard
          label="Compliance Score"
          value={loading && !summary ? "..." : complianceScore}
          hint={totalChecks ? `${stats.failed_checks || 0} failed of ${totalChecks} applicable checks` : "Run analysis to compute"}
        />
        <MetricCard
          label="Control Coverage"
          value={loading && !summary ? "..." : `${stats.total_checks || 0}`}
          hint={coverage}
        />
        <MetricCard
          label="Audit Readiness"
          value={loading && !summary ? "..." : `${auditReadiness}%`}
          hint={
            stats.violations_detected
              ? `${stats.resolved_violations || 0} resolved · ${stats.acknowledged_violations || 0} acknowledged · ${stats.open_violations || 0} open`
              : "No violations to resolve"
          }
          tone={readinessColor}
        />
      </div>

      <RealtimeStatus runId={runId} runProgress={runProgress} events={runEvents} />

      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.6fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <h3 className="text-xl font-semibold text-slate-900">Violations by Severity</h3>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={severityData} dataKey="value" nameKey="name" innerRadius={60} outerRadius={90} paddingAngle={4}>
                  {severityData.map((entry) => (
                    <Cell key={entry.name} fill={severityColors[entry.name] || "#94a3b8"} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 flex flex-wrap justify-center gap-4 text-sm text-slate-500">
            {(summary?.severity_breakdown || []).map((item) => (
              <div key={item.name} className="flex items-center gap-2">
                <span className="h-3 w-10 rounded-full" style={{ backgroundColor: severityColors[item.name] || "#94a3b8" }} />
                <span>{item.name}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <h3 className="text-xl font-semibold text-slate-900">Violations by Control Type</h3>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={controlData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="rule_id" tick={{ fill: "#64748b", fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fill: "#64748b", fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#4f6fd8" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ── All Violation Tickets ── */}
      <div className="rounded-2xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h3 className="text-xl font-semibold text-slate-900">All Violation Tickets</h3>
            <p className="mt-1 text-sm text-slate-500">
              {violations.length} violation(s) · Acknowledge and resolve to improve audit readiness
            </p>
          </div>
          <button className="text-sm font-medium text-slate-600 transition hover:text-slate-900" onClick={loadViolations}>
            Refresh
          </button>
        </div>
        <div className="overflow-hidden">
          <div className="grid grid-cols-[1.1fr_0.9fr_0.7fr_0.75fr_1fr_1.1fr] gap-4 bg-slate-50 px-5 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            <span>Ticket</span>
            <span>Control</span>
            <span>Severity</span>
            <span>Status</span>
            <span>Detected</span>
            <span>Actions</span>
          </div>
          {loadingViolations ? (
            <div className="px-5 py-10 text-center text-sm text-slate-500">Loading violations...</div>
          ) : violations.length ? (
            <div className="max-h-[420px] overflow-y-auto">
              {violations.map((v) => {
                const isReanalyzing = reanalyzingIds.has(v.id);
                const resolveResult = resolveResults[v.id];
                return (
                  <div key={v.id} className="border-t border-slate-100">
                    <div className="grid grid-cols-[1.1fr_0.9fr_0.7fr_0.75fr_1fr_1.1fr] gap-4 px-5 py-3 text-sm">
                      <div>
                        <div className="font-semibold text-slate-900">{v.ticket_id}</div>
                        <div className="mt-0.5 truncate text-xs text-slate-500">{v.title}</div>
                      </div>
                      <div className="text-slate-700">{v.rule_id}</div>
                      <div>
                        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${v.severity === "HIGH" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700"}`}>
                          {v.severity}
                        </span>
                      </div>
                      <div>
                        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${ackStatusStyles[v.ack_status] || "bg-slate-100 text-slate-600"}`}>
                          {v.ack_status}
                        </span>
                        {v.risk_note && (
                          <div className="mt-1 line-clamp-2 text-xs text-slate-500" title={v.risk_note}>{v.risk_note}</div>
                        )}
                      </div>
                      <div className="text-slate-500">{v.created_at?.slice(0, 16).replace("T", " ")}</div>
                      <div className="flex flex-wrap items-start gap-1.5">
                        {v.ack_status !== "acknowledged" && v.ack_status !== "resolved" && (
                          <button
                            className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 transition hover:bg-amber-100 disabled:opacity-50"
                            onClick={() => setAckModal(v)}
                            disabled={!!actionLoading[`ack-${v.id}`]}
                          >
                            {actionLoading[`ack-${v.id}`] ? "..." : "Accept Risk"}
                          </button>
                        )}
                        {v.ack_status !== "resolved" && (
                          <button
                            className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-50"
                            onClick={() => handleResolve(v)}
                            disabled={isReanalyzing}
                          >
                            {isReanalyzing ? "Checking..." : "Resolve"}
                          </button>
                        )}
                        {v.ack_status === "resolved" && (
                          <span className="text-xs font-medium text-emerald-600">✓ Done</span>
                        )}
                      </div>
                    </div>
                    {resolveResult && !resolveResult.allPassed && (
                      <div className="mx-4 mb-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs">
                        <span className="font-semibold text-rose-700">Still failing after re-analysis: </span>
                        <span className="text-rose-600">{resolveResult.failedRules.join(", ")}</span>
                        <span className="ml-2 text-slate-500">— fix the underlying issue and try Resolve again.</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="px-5 py-10 text-center text-sm text-slate-500">No violations recorded yet. Run an analysis to populate.</div>
          )}
        </div>
      </div>

      {/* ── Live Alert Feed ── */}
      <div className="rounded-2xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h3 className="text-xl font-semibold text-slate-900">Live Compliance Alert Feed</h3>
          <button className="text-sm font-medium text-slate-600 transition hover:text-slate-900" onClick={onRefresh}>Refresh</button>
        </div>
        <div className="p-5">
          {alerts.length ? (
            <div className="space-y-3">
              {alerts.map((alert) => (
                <div key={alert.id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-900">{alert.ticket_id}</div>
                      <div className="mt-1 text-sm text-slate-500">{alert.title}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700">{alert.rule_id}</div>
                      {alert.resolved_at ? (
                        <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">Resolved</span>
                      ) : alert.acknowledged_at ? (
                        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700">Ack'd</span>
                      ) : null}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-10 text-center text-sm text-slate-500">No violations recorded yet. Run an analysis to populate the feed.</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
