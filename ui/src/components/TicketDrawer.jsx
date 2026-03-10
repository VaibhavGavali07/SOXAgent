const statusStyles = {
  PASS: "bg-emerald-100 text-emerald-700",
  FAIL: "bg-rose-100 text-rose-700",
  NEEDS_REVIEW: "bg-amber-100 text-amber-700"
};

const TicketDrawer = ({ detail, onClose }) => {
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
            <div className="rounded-3xl bg-white p-5 shadow-panel">
              <div className="text-sm text-slate-500">{detail.detail}</div>
              <div className="mt-4 flex flex-wrap gap-2">
                {detail.evidence?.map((item, index) => (
                  <div key={`${item.ref_id}-${index}`} className="rounded-2xl bg-slate-100 px-3 py-2 text-xs text-slate-700">
                    {item.ref_id}: {item.snippet}
                  </div>
                ))}
              </div>
            </div>
            <div className="mt-6 grid gap-3">
              {detail.rule_results?.map((rule) => (
                <div key={rule.rule_id} className="rounded-3xl bg-white p-5 shadow-panel">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-900">{rule.rule_id} {rule.rule_name}</div>
                      <div className="mt-2 text-sm text-slate-600">{rule.why}</div>
                    </div>
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusStyles[rule.status]}`}>{rule.status}</span>
                  </div>
                  <div className="mt-3 text-sm text-slate-600">Confidence: {Math.round(rule.confidence * 100)}%</div>
                  <div className="mt-3 text-sm font-medium text-slate-800">Recommended action</div>
                  <div className="mt-1 text-sm text-slate-600">{rule.recommended_action}</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {rule.evidence?.map((item, index) => (
                      <div key={`${rule.rule_id}-${item.ref_id}-${index}`} className="rounded-2xl bg-slate-100 px-3 py-2 text-xs text-slate-700">
                        {item.type} | {item.ref_id} | {item.snippet}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            {detail.llm_response ? (
              <div className="mt-6 rounded-3xl bg-[#101826] p-5 text-slate-100 shadow-panel">
                <div className="label text-slate-400">LLM response</div>
                <div className="mt-3 text-xs text-slate-300">
                  {detail.llm_response.provider} / {detail.llm_response.deployment_name} / {detail.llm_response.run_id}
                </div>
                <div className="mt-1 text-xs text-slate-400">Prompt hash: {detail.llm_response.prompt_hash}</div>
                <pre className="mt-3 overflow-auto text-xs">{JSON.stringify(detail.llm_response.response_json, null, 2)}</pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </aside>
    </div>
  );
};

export default TicketDrawer;
