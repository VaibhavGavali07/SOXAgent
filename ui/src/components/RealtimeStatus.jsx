const RealtimeStatus = ({ runId, runProgress, events = [] }) => {
  const status = runProgress?.status || "idle";
  const statusTone =
    status === "running"
      ? "bg-emerald-100 text-emerald-700"
      : status === "completed"
        ? "bg-sky-100 text-sky-700"
        : status === "failed"
          ? "bg-rose-100 text-rose-700"
          : "bg-slate-200 text-slate-600";
  const statusLabel =
    status === "running" ? "LIVE" : status === "completed" ? "COMPLETED" : status === "failed" ? "FAILED" : "IDLE";
  const runLabel = runId ? `MR-${runId.slice(0, 8).toUpperCase()}` : "";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Analysis Progress</div>
          <h3 className="mt-2 text-xl font-semibold text-slate-900">{runId ? "Active Compliance Analysis" : "No active analysis"}</h3>
          {runLabel ? <div className="mt-1 text-xs text-slate-500">Monitoring Run: {runLabel}</div> : null}
        </div>
        <div className={`rounded-full px-3 py-1 text-xs font-semibold ${statusTone}`}>
          {statusLabel}
        </div>
      </div>
      {status === "running" && runProgress?.total ? (
        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between text-xs text-slate-600">
            <span>{runProgress.message || "Processing tickets"}</span>
            <span>
              {runProgress.progress}/{runProgress.total}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-teal-600 transition-all duration-300"
              style={{ width: `${Math.min(100, Math.round((runProgress.progress / runProgress.total) * 100))}%` }}
            />
          </div>
        </div>
      ) : null}
      <div className="mt-4 space-y-3">
        {events.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">Start a run to stream status events over SSE.</div>
        ) : (
          events.map((event, index) => (
            <div key={`${event.timestamp}-${index}`} className="rounded-2xl bg-slate-100/80 p-4 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold text-slate-900">{event.message}</span>
                <span className="text-slate-500">{event.timestamp?.replace("T", " ").slice(0, 19)}</span>
              </div>
              {event.total ? <div className="mt-2 text-slate-600">Progress: {event.progress}/{event.total}</div> : null}
              {event.failed_rules?.length ? <div className="mt-2 text-rose-700">Failed: {event.failed_rules.join(", ")}</div> : null}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default RealtimeStatus;
