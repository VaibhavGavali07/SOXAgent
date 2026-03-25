import TicketInfoPanel from "./TicketInfoPanel";

const statusStyles = {
  PASS: "bg-emerald-100 text-emerald-700",
  FAIL: "bg-rose-100 text-rose-700",
  NEEDS_REVIEW: "bg-amber-100 text-amber-700"
};

const RULE_SORT = { FAIL: 0, NEEDS_REVIEW: 1, PASS: 2 };
const sortRules = (rules) =>
  [...(rules || [])].sort((a, b) => (RULE_SORT[a.status] ?? 3) - (RULE_SORT[b.status] ?? 3));

const ScreenshotApprovals = ({ approvals }) => {
  if (!approvals?.length) return null;
  return (
    <div className="mt-6 rounded-3xl border border-violet-200 bg-violet-50 p-5 shadow-panel">
      <div className="flex items-center gap-2">
        <span className="text-lg">📷</span>
        <span className="text-sm font-semibold text-violet-800">
          Screenshot Approval Evidence ({approvals.length} image{approvals.length !== 1 ? "s" : ""} analysed)
        </span>
      </div>
      <div className="mt-3 space-y-3">
        {approvals.map((apv, i) => {
          const statusColor =
            apv.approval_status === "approved"
              ? "bg-emerald-100 text-emerald-700"
              : apv.approval_status === "rejected"
              ? "bg-rose-100 text-rose-700"
              : "bg-slate-100 text-slate-600";
          return (
            <div key={i} className="rounded-2xl bg-white p-3 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-medium text-slate-700">📎 {apv.filename}</span>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${statusColor}`}>
                  {apv.approval_status}
                </span>
              </div>
              {apv.approver && (
                <div className="mt-1.5 text-xs text-slate-600">
                  <span className="font-medium">Approver:</span> {apv.approver}
                  {apv.timestamp && <span className="ml-2 text-slate-400">@ {apv.timestamp}</span>}
                </div>
              )}
              {apv.approval_text && (
                <div className="mt-1 text-xs italic text-slate-500">"{apv.approval_text}"</div>
              )}
              {apv.summary && (
                <div className="mt-1 text-xs text-slate-500">{apv.summary}</div>
              )}
              <div className="mt-1.5 text-xs text-slate-400">
                Confidence: {Math.round((apv.confidence || 0) * 100)}%
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};


const TicketDrawer = ({ detail, onClose }) => {
  const screenshotApprovals = detail?.ticket?.screenshot_approvals || [];

  return (
    <div className={`fixed inset-0 z-50 transition ${detail ? "pointer-events-auto" : "pointer-events-none"}`}>
      <div className={`absolute inset-0 bg-slate-950/40 transition ${detail ? "opacity-100" : "opacity-0"}`} onClick={onClose} />
      <aside className={`absolute right-0 top-0 h-full w-full max-w-2xl transform bg-[#fffaf4] shadow-2xl transition ${detail ? "translate-x-0" : "translate-x-full"}`}>
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-5">
          <div>
            <div className="label">Violation details</div>
            <h3 className="mt-2 font-display text-2xl text-ink">{detail?.ticket_id || "Select an alert"}</h3>
          </div>
          <button className="button-secondary" onClick={onClose}>Close</button>
        </div>
        {detail ? (
          <div className="h-[calc(100vh-104px)] overflow-y-auto px-6 py-5">
            {/* Violation summary */}
            <div className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="mb-1 text-xs font-bold uppercase tracking-widest text-slate-400">Violation Summary</div>
              <div className="text-sm text-slate-600">{detail.detail}</div>
              {detail.evidence?.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {detail.evidence.map((item, index) => (
                    <div key={`${item.ref_id}-${index}`} className="rounded-xl bg-slate-100 px-3 py-1.5 text-xs text-slate-700">
                      <span className="font-medium">{item.ref_id}:</span> {item.snippet}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Ticket details — human readable */}
            <div className="mt-6">
              <TicketInfoPanel ticket={detail.ticket} />
            </div>

            <ScreenshotApprovals approvals={screenshotApprovals} />

            {/* Rule results */}
            <div className="mt-6 grid gap-3">
              {sortRules(detail.rule_results).map((rule) => (
                <div key={rule.rule_id} className="rounded-2xl border border-slate-200 bg-white p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-900">{rule.rule_id} — {rule.rule_name}</div>
                      <div className="mt-2 text-sm text-slate-600">{rule.why}</div>
                    </div>
                    <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${statusStyles[rule.status]}`}>{rule.status}</span>
                  </div>
                  <div className="mt-2 text-xs text-slate-500">Confidence: {Math.round(rule.confidence * 100)}%</div>
                  <div className="mt-3 text-sm font-medium text-slate-800">Recommended action</div>
                  <div className="mt-1 text-sm text-slate-600">{rule.recommended_action}</div>
                  {rule.evidence?.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {rule.evidence.map((item, index) => (
                        <div key={`${rule.rule_id}-${item.ref_id}-${index}`} className="rounded-xl bg-slate-100 px-3 py-1.5 text-xs text-slate-700">
                          <span className="font-medium capitalize">{item.type}</span> · {item.ref_id} · {item.snippet}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>

          </div>
        ) : null}
      </aside>
    </div>
  );
};

export default TicketDrawer;
