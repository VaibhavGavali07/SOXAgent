import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";
import { api } from "../api/client";
import TicketDrawer from "../components/TicketDrawer";

const ackStatusStyles = {
  open: "bg-rose-100 text-rose-700",
  acknowledged: "bg-amber-100 text-amber-700",
  resolved: "bg-emerald-100 text-emerald-700",
};

// ---------------------------------------------------------------------------
// Accept Risk modal
// ---------------------------------------------------------------------------
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
          <button className="button-secondary" onClick={onCancel}>Cancel</button>
          <button
            className="button-primary disabled:opacity-50"
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

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
const Violations = ({ refreshKey, presetFilters = {} }) => {
  const [filters, setFilters] = useState({ severity: "", status: "", ackStatus: "", search: "" });
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [actionLoading, setActionLoading] = useState({});

  // Accept Risk modal
  const [ackModal, setAckModal] = useState(null);

  // Resolve re-analysis tracking
  const [reanalyzingIds, setReanalyzingIds] = useState(new Set());
  // alertId -> { allPassed: bool, failedRules: string[] }
  const [resolveResults, setResolveResults] = useState({});

  const load = async () => {
    if (!alerts.length) setLoading(true);
    else setRefreshing(true);
    try {
      const params = Object.fromEntries(
        Object.entries({ severity: filters.severity || undefined }).filter(([, v]) => v)
      );
      const data = await api.violations(params);
      setAlerts(data);
    } catch {
      toast.error("Failed to load violations");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, [refreshKey]);

  useEffect(() => {
    if (!presetFilters?.__ts) return;
    setFilters((cur) => ({
      ...cur,
      severity: presetFilters.severity || "",
      status: presetFilters.status || "",
      search: presetFilters.search || "",
    }));
  }, [presetFilters]);

  const openDetail = async (alert) => {
    const detail = await api.violation(alert.id);
    setSelectedDetail(detail);
  };

  // ------------------------------------------------------------------
  // Accept Risk (Acknowledge with justification)
  // ------------------------------------------------------------------
  const handleAckConfirm = async (note) => {
    const alert = ackModal;
    setAckModal(null);
    setActionLoading((prev) => ({ ...prev, [`ack-${alert.id}`]: true }));
    try {
      await api.acknowledgeViolation(alert.id, note);
      setAlerts((prev) =>
        prev.map((v) =>
          v.id === alert.id
            ? { ...v, ack_status: "acknowledged", acknowledged_at: new Date().toISOString(), risk_note: note }
            : v
        )
      );
      toast.success("Risk accepted — violation acknowledged");
    } catch {
      toast.error("Failed to acknowledge violation");
    } finally {
      setActionLoading((prev) => ({ ...prev, [`ack-${alert.id}`]: false }));
    }
  };

  // ------------------------------------------------------------------
  // Smart Resolve — re-analyse ticket, only resolve when all rules pass
  // ------------------------------------------------------------------
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
        setAlerts((prev) =>
          prev.map((v) =>
            v.id === alert.id
              ? { ...v, ack_status: "resolved", resolved_at: new Date().toISOString(), acknowledged_at: v.acknowledged_at || new Date().toISOString() }
              : v
          )
        );
        setResolveResults((prev) => ({ ...prev, [alert.id]: { allPassed: true, failedRules: [] } }));
        toast.success(`${alert.ticket_id} — all controls passed, violation resolved`);
      } else {
        setResolveResults((prev) => ({ ...prev, [alert.id]: { allPassed: false, failedRules } }));
        toast.error(`${alert.ticket_id} — ${failedRules.length} rule(s) still failing`);
      }
    } catch (err) {
      toast.error(`Re-analysis failed: ${err.message || "unknown error"}`);
    } finally {
      setReanalyzingIds((prev) => { const n = new Set(prev); n.delete(alert.id); return n; });
    }
  };

  // ------------------------------------------------------------------
  // Filtering
  // ------------------------------------------------------------------
  const filtered = alerts.filter((alert) => {
    const statusMatch = !filters.status || alert.status === filters.status;
    const ackMatch = !filters.ackStatus || alert.ack_status === filters.ackStatus;
    const search = filters.search.trim().toLowerCase();
    const searchMatch =
      !search ||
      `${alert.ticket_id} ${alert.rule_id} ${alert.title} ${alert.detail} ${alert.source}`
        .toLowerCase()
        .includes(search);
    return statusMatch && ackMatch && searchMatch;
  });

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="space-y-5">
      <AcceptRiskModal
        alert={ackModal}
        onConfirm={handleAckConfirm}
        onCancel={() => setAckModal(null)}
      />

      <div className="rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-6 py-4">
          <h2 className="text-3xl font-semibold text-slate-900">Compliance Violations</h2>
          <p className="mt-1 text-sm text-slate-500">
            All detected ITGC control violations — accept risk or resolve to update audit readiness
          </p>
        </div>

        <div className="px-6 py-5">
          <div className="grid gap-3 md:grid-cols-[0.55fr_0.6fr_0.6fr_1.2fr_auto]">
            <select className="input" value={filters.severity} onChange={(e) => setFilters((c) => ({ ...c, severity: e.target.value }))}>
              <option value="">All severities</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
            </select>
            <select className="input" value={filters.status} onChange={(e) => setFilters((c) => ({ ...c, status: e.target.value }))}>
              <option value="">All Statuses</option>
              <option value="FAIL">FAIL</option>
              <option value="NEEDS_REVIEW">NEEDS_REVIEW</option>
              <option value="PASS">PASS</option>
            </select>
            <select className="input" value={filters.ackStatus} onChange={(e) => setFilters((c) => ({ ...c, ackStatus: e.target.value }))}>
              <option value="">All Actions</option>
              <option value="open">Open</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
            </select>
            <input
              className="input"
              placeholder="Search violations..."
              value={filters.search}
              onChange={(e) => setFilters((c) => ({ ...c, search: e.target.value }))}
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
            <div className="grid grid-cols-[1fr_1fr_1fr_0.7fr_0.7fr_0.7fr_0.9fr_0.9fr_1.1fr] gap-4 bg-slate-100 px-6 py-4 text-xs font-semibold uppercase tracking-[0.16em] text-slate-600">
              <div>Run ID</div>
              <div>Ticket</div>
              <div>Control</div>
              <div>Type</div>
              <div>Severity</div>
              <div>Status</div>
              <div>Detected</div>
              <div>Action Status</div>
              <div>Actions</div>
            </div>

            {loading ? (
              <div className="px-6 py-12 text-center text-sm text-slate-500">Loading violations...</div>
            ) : filtered.length ? (
              <div className="max-h-[620px] overflow-y-auto bg-white">
                {filtered.map((alert) => {
                  const isReanalyzing = reanalyzingIds.has(alert.id);
                  const resolveResult = resolveResults[alert.id];

                  return (
                    <div key={alert.id} className="border-t border-slate-100">
                      <div className="grid grid-cols-[1fr_1fr_1fr_0.7fr_0.7fr_0.7fr_0.9fr_0.9fr_1.1fr] gap-4 px-6 py-5 text-sm">
                        <div className="truncate text-slate-500 text-xs leading-5">{alert.run_id}</div>
                        <div className="font-semibold text-base text-slate-900">{alert.ticket_id}</div>
                        <div className="font-medium text-slate-700">{alert.rule_id}</div>
                        <div className="uppercase text-slate-600">{alert.source}</div>
                        <div>
                          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${alert.severity === "HIGH" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700"}`}>
                            {alert.severity}
                          </span>
                        </div>
                        <div className="text-slate-600">{alert.status}</div>
                        <div className="text-slate-500">{alert.created_at?.slice(0, 16).replace("T", " ")}</div>

                        {/* Action status + risk note */}
                        <div className="space-y-1">
                          <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${ackStatusStyles[alert.ack_status] || "bg-slate-100 text-slate-600"}`}>
                            {alert.ack_status}
                          </span>
                          {alert.risk_note && (
                            <div className="line-clamp-2 text-xs text-slate-500" title={alert.risk_note}>
                              {alert.risk_note}
                            </div>
                          )}
                        </div>

                        {/* Action buttons */}
                        <div className="flex flex-wrap items-start gap-1.5">
                          {alert.ack_status !== "acknowledged" && alert.ack_status !== "resolved" && (
                            <button
                              className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 transition hover:bg-amber-100 disabled:opacity-50"
                              onClick={() => setAckModal(alert)}
                              disabled={!!actionLoading[`ack-${alert.id}`]}
                            >
                              {actionLoading[`ack-${alert.id}`] ? "..." : "Accept Risk"}
                            </button>
                          )}

                          {alert.ack_status !== "resolved" && (
                            <button
                              className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-50"
                              onClick={() => handleResolve(alert)}
                              disabled={isReanalyzing}
                            >
                              {isReanalyzing ? "Checking..." : "Resolve"}
                            </button>
                          )}

                          {alert.ack_status === "resolved" && (
                            <span className="text-xs font-medium text-emerald-600">✓ Done</span>
                          )}

                          <button
                            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                            onClick={() => openDetail(alert)}
                          >
                            View
                          </button>
                        </div>
                      </div>

                      {/* Inline result banner — shown only when re-analysis found still-failing rules */}
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
