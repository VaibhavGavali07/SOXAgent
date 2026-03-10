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
import RealtimeStatus from "../components/RealtimeStatus";

const severityColors = {
  HIGH: "#ef4444",
  MEDIUM: "#f59e0b",
  LOW: "#3b82f6"
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

const Dashboard = ({ summary, loading, refreshing, runId, runProgress, runEvents, onRefresh, onOpenTickets }) => {
  const stats = summary?.stats || {};
  const totalChecks = stats.total_checks || 0;
  const complianceScore = totalChecks ? Math.round((stats.passed_checks / totalChecks) * 100) : "-";
  const coverage = summary ? `${stats.tickets_analyzed || 0} tickets analysed` : "Run analysis to compute";
  const readiness = totalChecks ? Math.round(((stats.passed_checks + stats.needs_review_checks * 0.5) / totalChecks) * 100) : 100;
  const alerts = summary?.recent_alerts || [];
  const severityData = (summary?.severity_breakdown || []).filter((item) => item.value > 0);
  const controlData = summary?.control_breakdown || [];

  const statusText =
    runProgress?.status === "running"
      ? "Active Compliance Analysis in progress"
      : runProgress?.status === "completed"
        ? "Last compliance analysis completed"
        : runProgress?.status === "failed"
          ? "Last compliance analysis failed"
          : "No analysis run yet";

  return (
    <div className="space-y-6">
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
          value={loading && !summary ? "..." : `${readiness}%`}
          hint="Derived from current control outcomes and open exception load"
          tone="green"
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
                    <div className="rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700">{alert.rule_id}</div>
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
