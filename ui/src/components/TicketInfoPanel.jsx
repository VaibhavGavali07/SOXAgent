const statusStyles = {
  PASS: "bg-emerald-100 text-emerald-700",
  FAIL: "bg-rose-100 text-rose-700",
  NEEDS_REVIEW: "bg-amber-100 text-amber-700",
};

const Field = ({ label, value }) =>
  value ? (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 text-sm text-slate-800">{value}</div>
    </div>
  ) : null;

const TicketInfoPanel = ({ ticket }) => {
  if (!ticket) return null;
  const t = ticket;
  const cf = t.custom_fields || {};

  const comments = [...(t.comments || [])].sort(
    (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
  );

  const statusColor = {
    Closed: "bg-slate-100 text-slate-600",
    Resolved: "bg-emerald-100 text-emerald-700",
    Open: "bg-rose-100 text-rose-700",
  }[t.status] || "bg-slate-100 text-slate-600";

  return (
    <div className="space-y-4">
      {/* Overview */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-bold uppercase tracking-widest text-slate-400">Ticket Overview</span>
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusColor}`}>{t.status}</span>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-3">
          <Field label="Ticket ID" value={t.ticket_id} />
          <Field label="Type" value={t.type} />
          <Field label="Summary" value={t.summary} />
          <Field label="Source" value={t.source} />
          <Field label="Created" value={t.created_at} />
          <Field label="Updated" value={t.updated_at} />
          <Field label="Closed" value={t.closed_at} />
          <Field label="Category" value={cf.category} />
          <Field label="Impact" value={cf.impact} />
          <Field label="Urgency" value={cf.urgency} />
          {cf.risk_hint && (
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Risk Hint</div>
              <span className={`mt-0.5 inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${cf.risk_hint === "HIGH" ? "bg-rose-100 text-rose-700" : cf.risk_hint === "MEDIUM" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
                {cf.risk_hint}
              </span>
            </div>
          )}
        </div>
        {t.description && (
          <div className="mt-3 border-t border-slate-100 pt-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Description</div>
            <div className="mt-1 text-sm text-slate-700">{t.description}</div>
          </div>
        )}
      </div>

      {/* People */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">People</div>
        <div className="space-y-2">
          {t.requestor?.name && (
            <div className="flex items-center gap-3 rounded-xl bg-slate-50 px-3 py-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-600">
                {t.requestor.name.charAt(0).toUpperCase()}
              </span>
              <div>
                <div className="text-sm font-medium text-slate-800">{t.requestor.name}</div>
                {t.requestor.email && <div className="text-xs text-slate-400">{t.requestor.email}</div>}
                <div className="text-xs text-slate-400">Requestor</div>
              </div>
            </div>
          )}
          {(t.implementers || []).map((imp, i) => (
            <div key={i} className="flex items-center gap-3 rounded-xl bg-slate-50 px-3 py-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-100 text-xs font-bold text-violet-600">
                {(imp.name || "I").charAt(0).toUpperCase()}
              </span>
              <div>
                <div className="text-sm font-medium text-slate-800">{imp.name || imp.id}</div>
                {imp.email && <div className="text-xs text-slate-400">{imp.email}</div>}
                <div className="text-xs text-slate-400">Implementer</div>
              </div>
            </div>
          ))}
          {!t.requestor?.name && !(t.implementers?.length) && (
            <div className="text-sm text-slate-400">No people information recorded</div>
          )}
        </div>
      </div>

      {/* Approvals */}
      {(t.approvals || []).length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Approvals</div>
          <div className="space-y-2">
            {t.approvals.map((apv, i) => (
              <div key={i} className="flex items-start justify-between rounded-xl bg-slate-50 px-3 py-2">
                <div>
                  <div className="text-sm font-medium text-slate-800">{apv.approver_name || apv.approver_id || "Unknown"}</div>
                  {apv.timestamp && <div className="text-xs text-slate-400">{apv.timestamp}</div>}
                  {apv.comments && <div className="mt-1 text-xs text-slate-600 italic">"{apv.comments}"</div>}
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${apv.state === "approved" ? "bg-emerald-100 text-emerald-700" : apv.state === "rejected" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700"}`}>
                  {apv.state || "pending"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Comment timeline */}
      {comments.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">
            Activity Timeline ({comments.length} comment{comments.length !== 1 ? "s" : ""})
          </div>
          <div className="relative space-y-0 pl-4">
            <div className="absolute left-1.5 top-2 bottom-2 w-px bg-slate-200" />
            {comments.map((c, i) => (
              <div key={c.id || i} className="relative pb-4">
                <span className="absolute -left-[11px] mt-1.5 h-3 w-3 rounded-full border-2 border-white bg-slate-300" />
                <div className="rounded-xl bg-slate-50 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-slate-700">{c.author?.name || "Unknown"}</span>
                    <span className="text-xs text-slate-400">{c.timestamp}</span>
                  </div>
                  <div className="mt-1 text-sm text-slate-700">{c.body}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ServiceNow link */}
      {cf.servicenow_url && (
        <a
          href={cf.servicenow_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-medium text-blue-700 transition hover:bg-blue-100"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Open in ServiceNow
        </a>
      )}
    </div>
  );
};

export default TicketInfoPanel;
