import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { api } from "../api/client";
import TicketDrawer from "../components/TicketDrawer";

const Violations = ({ refreshKey, presetFilters = {} }) => {
  const [filters, setFilters] = useState({ severity: "", status: "", search: "" });
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState(null);

  const load = async () => {
    if (!alerts.length) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    try {
      const params = Object.fromEntries(
        Object.entries({
          severity: filters.severity || undefined,
        }).filter(([, value]) => value)
      );
      const data = await api.violations(params);
      setAlerts(data);
    } catch (error) {
      toast.error("Failed to load violations");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    load();
  }, [refreshKey]);

  useEffect(() => {
    if (!presetFilters || !presetFilters.__ts) return;
    setFilters((current) => ({
      ...current,
      severity: presetFilters.severity || "",
      status: presetFilters.status || "",
      search: presetFilters.search || "",
    }));
  }, [presetFilters]);

  const openDetail = async (alert) => {
    const detail = await api.violation(alert.id);
    setSelectedDetail(detail);
  };

  const filtered = alerts.filter((alert) => {
    const statusMatch = !filters.status || alert.status === filters.status;
    const search = filters.search.trim().toLowerCase();
    const searchMatch =
      !search ||
      `${alert.ticket_id} ${alert.rule_id} ${alert.title} ${alert.detail} ${alert.source}`
        .toLowerCase()
        .includes(search);
    return statusMatch && searchMatch;
  });

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-6 py-4">
          <h2 className="text-3xl font-semibold text-slate-900">Compliance Violations</h2>
          <p className="mt-1 text-sm text-slate-500">All detected ITGC control violations</p>
        </div>

        <div className="px-6 py-5">
          <div className="grid gap-3 md:grid-cols-[0.65fr_0.7fr_1.2fr_auto]">
            <select className="input" value={filters.severity} onChange={(event) => setFilters((current) => ({ ...current, severity: event.target.value }))}>
              <option value="">All severities</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
            </select>
            <select className="input" value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}>
              <option value="">All Statuses</option>
              <option value="FAIL">FAIL</option>
              <option value="NEEDS_REVIEW">NEEDS_REVIEW</option>
              <option value="PASS">PASS</option>
            </select>
            <input
              className="input"
              placeholder="Search violations..."
              value={filters.search}
              onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
            />
            <div className="flex items-center gap-4">
              <div className="text-sm text-slate-500">
                {filtered.length} violation(s){refreshing ? " | refreshing..." : ""}
              </div>
              <button className="button-secondary" onClick={load}>
                {refreshing ? "Refreshing..." : "Refresh"}
              </button>
            </div>
          </div>
        </div>

        <div className="px-6 pb-6">
          <div className="overflow-hidden rounded-2xl border border-slate-200">
            <div className="grid grid-cols-[1.1fr_1.1fr_1.1fr_0.8fr_0.8fr_0.9fr_1fr_0.8fr] gap-4 bg-slate-100 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-600">
              <div>Run ID</div>
              <div>Ticket</div>
              <div>Control</div>
              <div>Type</div>
              <div>Severity</div>
              <div>Status</div>
              <div>Detected</div>
              <div>Actions</div>
            </div>
            {loading ? (
              <div className="px-4 py-10 text-center text-sm text-slate-500">Loading violations...</div>
            ) : filtered.length ? (
              <div className="max-h-[460px] overflow-y-auto bg-white">
                {filtered.map((alert) => (
                  <div key={alert.id} className="grid grid-cols-[1.1fr_1.1fr_1.1fr_0.8fr_0.8fr_0.9fr_1fr_0.8fr] gap-4 border-t border-slate-100 px-4 py-3 text-sm">
                    <div className="truncate text-slate-700">{alert.run_id}</div>
                    <div className="font-semibold text-slate-900">{alert.ticket_id}</div>
                    <div className="text-slate-700">{alert.rule_id}</div>
                    <div className="uppercase text-slate-600">{alert.source}</div>
                    <div>
                      <span className={`rounded-full px-2 py-1 text-xs font-semibold ${alert.severity === "HIGH" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700"}`}>
                        {alert.severity}
                      </span>
                    </div>
                    <div className="text-slate-600">{alert.status}</div>
                    <div className="text-slate-500">{alert.created_at?.slice(0, 16).replace("T", " ")}</div>
                    <div>
                      <button className="button-secondary px-3 py-1.5 text-xs" onClick={() => openDetail(alert)}>
                        View
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-4 py-10 text-center text-sm text-slate-500">
                No violations found. Run an analysis from the Dashboard.
              </div>
            )}
          </div>
        </div>
      </div>

      <TicketDrawer detail={selectedDetail} onClose={() => setSelectedDetail(null)} />
    </div>
  );
};

export default Violations;
