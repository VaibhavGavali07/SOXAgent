const Icon = ({ path }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
    <path d={path} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const icons = {
  dashboard: "M3 13h8V3H3zm10 8h8v-6h-8zM3 21h8v-6H3zm10-10h8V3h-8z",
  tickets: "M5 7h14M7 4h10a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z",
  violations: "m12 9 .01 0M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0ZM12 13v3",
  connections: "M15 7h4a2 2 0 0 1 2 2v4m-9 4H8a2 2 0 0 1-2-2V9m4 4h4M7 12H3m18 0h-4M12 3v4m0 14v-4",
  rules: "M9 3h6m-7 4h8M7 21h10a2 2 0 0 0 2-2V7l-4-4H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2Zm3-7h4",
};

const SidebarNav = ({ activeTab, onChange }) => {
  const groups = [
    {
      label: "Monitoring",
      items: [
        { id: "dashboard", label: "Dashboard" },
        { id: "tickets", label: "Tickets" },
        { id: "violations", label: "Violations" },
        { id: "rules", label: "Rules" },
      ],
    },
    {
      label: "System",
      items: [{ id: "connections", label: "Connections" }],
    },
  ];

  return (
    <aside className="flex w-full flex-col bg-[#081633] text-white lg:sticky lg:top-0 lg:h-screen lg:w-[240px] lg:flex-shrink-0 lg:overflow-y-auto">
      <div className="border-b border-white/10 px-6 py-7">
        <div className="flex items-start gap-3">
          <div className="mt-1 rounded-full border border-white/15 bg-white/5 p-2 text-cyan-200">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
              <path d="M12 3 5 6v5c0 5 3.4 8.8 7 10 3.6-1.2 7-5 7-10V6l-7-3Zm0 5 1.1 2.3 2.5.4-1.8 1.8.4 2.5-2.2-1.2-2.2 1.2.4-2.5-1.8-1.8 2.5-.4L12 8Z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div>
            <div className="text-lg font-semibold">SOX Compliance</div>
            <p className="mt-1 text-sm leading-5 text-slate-300">SOX compliance audit readiness</p>
          </div>
        </div>
      </div>

      <div className="flex-1 space-y-8 px-3 py-5">
        {groups.map((group) => (
          <div key={group.label}>
            <div className="px-3 text-xs uppercase tracking-[0.22em] text-slate-400">{group.label}</div>
            <div className="mt-3 space-y-1">
              {group.items.map((item) => {
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => onChange(item.id)}
                    className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-medium transition ${
                      isActive ? "bg-[#2b53d0] text-white" : "text-slate-200 hover:bg-white/5"
                    }`}
                  >
                    <span className={`${isActive ? "text-white" : "text-slate-300"}`}>
                      <Icon path={icons[item.id]} />
                    </span>
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-white/10 px-6 py-4 text-xs text-slate-400">v1.0.0 | ITGC SOX Agent</div>
    </aside>
  );
};

export default SidebarNav;
