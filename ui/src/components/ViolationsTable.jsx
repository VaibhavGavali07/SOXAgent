const severityStyles = {
  HIGH: "bg-rose-100 text-rose-700",
  MEDIUM: "bg-amber-100 text-amber-700",
  LOW: "bg-emerald-100 text-emerald-700"
};

const ViolationsTable = ({ alerts, loading, onSelect }) => {
  if (loading) {
    return (
      <div className="panel p-5">
        <div className="skeleton h-10 w-full" />
        <div className="skeleton mt-4 h-10 w-full" />
        <div className="skeleton mt-4 h-10 w-full" />
      </div>
    );
  }

  return (
    <div className="panel overflow-hidden">
      <div className="grid grid-cols-[1.2fr_0.7fr_0.7fr_0.9fr_1fr] gap-4 border-b border-slate-200 px-5 py-4 text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">
        <span>Ticket</span>
        <span>Rule</span>
        <span>Severity</span>
        <span>Source</span>
        <span>Created</span>
      </div>
      <div>
        {alerts.map((alert) => (
          <button
            key={alert.id}
            onClick={() => onSelect(alert)}
            className="grid w-full grid-cols-[1.2fr_0.7fr_0.7fr_0.9fr_1fr] gap-4 border-b border-slate-100 px-5 py-4 text-left transition hover:bg-slate-50"
          >
            <div>
              <div className="font-semibold text-slate-900">{alert.ticket_id}</div>
              <div className="mt-1 text-sm text-slate-500">{alert.title}</div>
            </div>
            <div className="text-sm font-medium text-slate-700">{alert.rule_id}</div>
            <div>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${severityStyles[alert.severity] || "bg-slate-200 text-slate-700"}`}>{alert.severity}</span>
            </div>
            <div className="text-sm text-slate-600">{alert.source}</div>
            <div className="text-sm text-slate-500">{alert.created_at?.slice(0, 10)}</div>
          </button>
        ))}
        {!alerts.length ? <div className="px-5 py-10 text-center text-sm text-slate-500">No violations match the current filters.</div> : null}
      </div>
    </div>
  );
};

export default ViolationsTable;

