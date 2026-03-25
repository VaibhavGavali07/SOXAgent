import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";
import { api } from "../api/client";
import RunModeModal from "../components/RunModeModal";
import TicketInfoPanel from "../components/TicketInfoPanel";

const priorityClass = {
  HIGH: "bg-rose-100 text-rose-700",
  MEDIUM: "bg-amber-100 text-amber-700",
  LOW: "bg-blue-100 text-blue-700",
};

const RULE_SORT = { FAIL: 0, NEEDS_REVIEW: 1, PASS: 2 };
const sortRules = (rules) =>
  [...(rules || [])].sort((a, b) => (RULE_SORT[a.status] ?? 3) - (RULE_SORT[b.status] ?? 3));

const TicketInfo = ({ refreshKey, onRunStarted, presetFilters = {} }) => {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning] = useState(false);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [minFailedFilter, setMinFailedFilter] = useState(0);
  const [selected, setSelected] = useState(null);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [showRunModal, setShowRunModal] = useState(false);

  const waitForRunCompletion = (runId) =>
    new Promise((resolve) => {
      if (!runId) {
        resolve();
        return;
      }
      const source = new EventSource(api.runEventsUrl(runId));
      let finished = false;
      const done = () => {
        if (finished) return;
        finished = true;
        source.close();
        resolve();
      };
      source.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.status === "completed" || payload.status === "failed") {
          done();
        }
      };
      source.onerror = () => done();
      setTimeout(done, 60000);
    });

  const loadTickets = async (overrides = {}) => {
    const qValue = overrides.q ?? query;
    const sourceValue = overrides.source ?? sourceFilter;
    const statusValue = overrides.status ?? statusFilter;
    const typeValue = overrides.ticket_type ?? typeFilter;
    const priorityValue = overrides.priority ?? priorityFilter;
    const minFailedValue = overrides.min_failed ?? minFailedFilter;
    if (!tickets.length) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    try {
      const params = Object.fromEntries(
        Object.entries({
          q: qValue || undefined,
          source: sourceValue || undefined,
          status: statusValue || undefined,
          ticket_type: typeValue || undefined,
        }).filter(([, value]) => value)
      );
      const rows = await api.tickets(params);
      let filteredRows = rows;
      if (priorityValue) {
        filteredRows = filteredRows.filter((item) => item.priority === priorityValue);
      }
      if (minFailedValue > 0) {
        filteredRows = filteredRows.filter((item) => (item.failed || 0) >= minFailedValue);
      }
      setTickets(filteredRows);
      if (selected) {
        const stillThere = filteredRows.find((item) => item.id === selected.id);
        setSelected(stillThere || null);
      }
    } catch {
      toast.error("Failed to load tickets");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadTickets();
  }, [refreshKey]);

  useEffect(() => {
    if (!presetFilters || !presetFilters.__ts) return;
    if (typeof presetFilters.q === "string") setQuery(presetFilters.q);
    if (typeof presetFilters.source === "string") setSourceFilter(presetFilters.source);
    if (typeof presetFilters.status === "string") setStatusFilter(presetFilters.status);
    if (typeof presetFilters.ticket_type === "string") setTypeFilter(presetFilters.ticket_type);
    const priorityValue = typeof presetFilters.priority === "string" ? presetFilters.priority : "";
    const minFailedValue = typeof presetFilters.min_failed === "number" ? presetFilters.min_failed : 0;
    setPriorityFilter(priorityValue);
    setMinFailedFilter(minFailedValue);
    setSelected(null);
    setSelectedDetail(null);
    loadTickets({
      q: typeof presetFilters.q === "string" ? presetFilters.q : query,
      source: typeof presetFilters.source === "string" ? presetFilters.source : sourceFilter,
      status: typeof presetFilters.status === "string" ? presetFilters.status : statusFilter,
      ticket_type: typeof presetFilters.ticket_type === "string" ? presetFilters.ticket_type : typeFilter,
      priority: priorityValue,
      min_failed: minFailedValue,
    });
  }, [presetFilters]);

  const handleRefreshAnalyze = async (mode = "append") => {
    setRunning(true);
    try {
      if (mode === "clean") {
        await api.clearComplianceData({ include_configs: false });
      }
      const snRun = await api.fetchServiceNow({});
      onRunStarted(snRun.run_id);
      toast.success("Refresh and analysis started for ServiceNow");
      await waitForRunCompletion(snRun.run_id);
      await loadTickets();
    } catch {
      toast.error("Failed to start refresh and analysis");
    } finally {
      setRunning(false);
    }
  };

  const handleRowClick = async (row) => {
    setSelected(row);
    try {
      const detail = await api.ticket(row.id);
      setSelectedDetail(detail);
    } catch {
      toast.error("Failed to load ticket detail");
      setSelectedDetail(null);
    }
  };

  const distinctStatuses = useMemo(() => {
    return Array.from(new Set(tickets.map((ticket) => ticket.status))).sort();
  }, [tickets]);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-6 py-4">
          <h2 className="text-3xl font-semibold text-slate-900">Monitored Tickets</h2>
          <p className="mt-1 text-sm text-slate-500">All ingested tickets from ServiceNow</p>
        </div>

        <div className="px-6 py-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="grid flex-1 gap-3 md:grid-cols-[1.2fr_0.7fr_0.7fr_0.8fr_0.8fr_auto]">
              <input
                className="input"
                placeholder="Search tickets..."
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <select className="input" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
                <option value="">All Sources</option>
                <option value="servicenow">ServiceNow</option>
              </select>
              <select className="input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="">All Statuses</option>
                {distinctStatuses.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
              <select className="input" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                <option value="">All Tickets</option>
                <option value="incident">Incidents</option>
                <option value="request">Requests</option>
                <option value="change">Changes</option>
              </select>
              <select className="input" value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
                <option value="">All Priorities</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>
              <button className="button-secondary" onClick={loadTickets}>Apply</button>
            </div>
            <div className="flex items-center gap-5">
              <div className="text-sm text-slate-500">
                {tickets.length} ticket(s) loaded{refreshing ? " | refreshing..." : ""}
              </div>
              <button className="button-primary disabled:opacity-60" disabled={running} onClick={() => setShowRunModal(true)}>
                {running ? "Running..." : "Refresh & Analyze"}
              </button>
            </div>
          </div>
        </div>

        <div className="px-6 pb-6">
          <div className="overflow-hidden rounded-2xl border border-slate-200">
            <div className="grid grid-cols-[0.9fr_1.6fr_0.8fr_0.8fr_0.8fr_0.6fr_0.6fr_0.8fr_1fr] gap-4 bg-slate-100 px-6 py-4 text-xs font-semibold uppercase tracking-[0.16em] text-slate-600">
              <div>Key</div>
              <div>Title</div>
              <div>Source</div>
              <div>Status</div>
              <div>Priority</div>
              <div>Passed</div>
              <div>Failed</div>
              <div>Violations</div>
              <div>Analysed</div>
            </div>
            {loading ? (
              <div className="px-6 py-12 text-center text-sm text-slate-500">Loading tickets...</div>
            ) : tickets.length ? (
              <div className="max-h-[620px] overflow-y-auto bg-white">
                {tickets.map((ticket) => (
                  <button
                    key={ticket.id}
                    onClick={() => handleRowClick(ticket)}
                    className={`grid w-full grid-cols-[0.9fr_1.6fr_0.8fr_0.8fr_0.8fr_0.6fr_0.6fr_0.8fr_1fr] gap-4 border-t border-slate-100 px-6 py-5 text-left text-sm transition ${
                      selected?.id === ticket.id ? "bg-blue-50" : "hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-semibold text-base text-slate-900">
                      {ticket.servicenow_url ? (
                        <a
                          href={ticket.servicenow_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {ticket.ticket_id}
                        </a>
                      ) : (
                        ticket.ticket_id
                      )}
                    </div>
                    <div className="truncate font-medium text-slate-700">{ticket.summary}</div>
                    <div className="uppercase text-slate-600">{ticket.source}</div>
                    <div className="text-slate-600">{ticket.status}</div>
                    <div>
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${priorityClass[ticket.priority] || "bg-slate-100 text-slate-700"}`}>
                        {ticket.priority}
                      </span>
                    </div>
                    <div className="text-base font-semibold text-emerald-700">{ticket.passed}</div>
                    <div className="text-base font-semibold text-rose-700">{ticket.failed}</div>
                    <div className="text-base font-semibold text-slate-800">{ticket.violations}</div>
                    <div className="text-slate-500">{ticket.analyzed_at ? ticket.analyzed_at.slice(0, 16).replace("T", " ") : "-"}</div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="px-4 py-10 text-center text-sm text-slate-500">
                No tickets found. Run an analysis from the Dashboard to ingest data.
              </div>
            )}
          </div>
        </div>
      </div>

      {showRunModal && (
        <RunModeModal
          onSelect={(mode) => { setShowRunModal(false); handleRefreshAnalyze(mode); }}
          onCancel={() => setShowRunModal(false)}
        />
      )}

      {selectedDetail ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-xl font-semibold text-slate-900">
              Ticket Detail:{" "}
              {selectedDetail.ticket.canonical_json?.custom_fields?.servicenow_url ? (
                <a
                  href={selectedDetail.ticket.canonical_json.custom_fields.servicenow_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  {selectedDetail.ticket.ticket_id}
                </a>
              ) : (
                selectedDetail.ticket.ticket_id
              )}
            </h3>
            <button
              className="button-secondary"
              onClick={async () => {
                const result = await api.rerunTicket(selectedDetail.ticket.id);
                onRunStarted(result.run_id);
                toast.success("Re-analysis started for selected ticket");
              }}
            >
              Re-run LLM Evaluation
            </button>
          </div>
          <div className="mt-4 space-y-4">
            <TicketInfoPanel ticket={selectedDetail.ticket.canonical_json} />
            {selectedDetail.rule_results?.length > 0 && (
              <div className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Rule Results</div>
                <div className="space-y-2">
                  {sortRules(selectedDetail.rule_results).map((rule) => (
                    <div key={rule.rule_id} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                      <div className="flex items-center justify-between">
                        <div className="font-semibold text-slate-900">{rule.rule_id} — {rule.rule_name}</div>
                        <div className={`rounded-full px-2 py-1 text-xs font-semibold ${rule.status === "FAIL" ? "bg-rose-100 text-rose-700" : rule.status === "PASS" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                          {rule.status}
                        </div>
                      </div>
                      <div className="mt-2 text-sm text-slate-600">{rule.why}</div>
                      {rule.recommended_action && (
                        <div className="mt-2 text-xs text-slate-500"><span className="font-medium">Action:</span> {rule.recommended_action}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default TicketInfo;
