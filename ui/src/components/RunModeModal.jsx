const RunModeModal = ({ onSelect, onCancel }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
    <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
      <h3 className="text-lg font-semibold text-slate-900">Run Analysis</h3>
      <p className="mt-1 text-sm text-slate-500">How would you like to proceed?</p>
      <div className="mt-5 space-y-3">
        <button
          className="w-full rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-left transition hover:bg-rose-100"
          onClick={() => onSelect("clean")}
        >
          <div className="font-semibold text-rose-800">Clean &amp; Run</div>
          <div className="mt-0.5 text-xs text-rose-600">Delete all existing tickets and results, then fetch fresh data from ServiceNow and analyse.</div>
        </button>
        <button
          className="w-full rounded-xl border border-teal-200 bg-teal-50 px-4 py-3 text-left transition hover:bg-teal-100"
          onClick={() => onSelect("append")}
        >
          <div className="font-semibold text-teal-800">Fetch New Tickets</div>
          <div className="mt-0.5 text-xs text-teal-600">Fetch tickets from ServiceNow and analyse — existing data is kept.</div>
        </button>
      </div>
      <button
        className="mt-4 w-full rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-600 transition hover:bg-slate-50"
        onClick={onCancel}
      >
        Cancel
      </button>
    </div>
  </div>
);

export default RunModeModal;
