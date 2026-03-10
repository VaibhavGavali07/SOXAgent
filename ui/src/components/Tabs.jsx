const Tabs = ({ tabs, active, onChange }) => (
  <div className="inline-flex rounded-full border border-slate-300/80 bg-white/70 p-1 shadow-panel">
    {tabs.map((tab) => (
      <button
        key={tab.id}
        onClick={() => onChange(tab.id)}
        className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
          active === tab.id ? "bg-ink text-white" : "text-slate-600 hover:text-slate-900"
        }`}
      >
        {tab.label}
      </button>
    ))}
  </div>
);

export default Tabs;

