import soxLogo from "../assets/sox-logo.svg";

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
    <aside className="scanline relative flex w-full flex-col bg-[#060D1F] text-white lg:sticky lg:top-0 lg:h-screen lg:w-[260px] lg:flex-shrink-0 lg:overflow-y-auto">
      {/* top cyan accent line */}
      <div className="h-[2px] w-full bg-gradient-to-r from-transparent via-cyan-400 to-transparent opacity-70" />

      <div className="border-b border-cyan-900/40 px-6 py-6">
        <div className="flex items-center gap-3">
          <div className="relative">
            <img src={soxLogo} alt="SOX Agent" className="h-11 w-11 shrink-0 drop-shadow-[0_0_8px_rgba(34,211,238,0.5)]" />
            <span className="absolute -bottom-1 -right-1 h-2.5 w-2.5 rounded-full bg-cyan-400 shadow-[0_0_6px_2px_rgba(34,211,238,0.6)]" />
          </div>
          <div>
            <div className="text-lg font-bold tracking-tight text-white">SOX Agent</div>
            <p className="mt-0.5 text-xs leading-4 text-cyan-400/80">ITGC Compliance AI</p>
          </div>
        </div>
      </div>

      <div className="flex-1 space-y-8 px-3 py-5">
        {groups.map((group) => (
          <div key={group.label}>
            <div className="px-3 text-[10px] uppercase tracking-[0.28em] text-cyan-500/50">{group.label}</div>
            <div className="mt-3 space-y-1">
              {group.items.map((item) => {
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => onChange(item.id)}
                    className={`sidebar-item-enter flex w-full items-center gap-3.5 rounded-lg px-4 py-3.5 text-left text-base font-medium transition-all duration-200 hover:translate-x-1 ${
                      isActive
                        ? "sidebar-active-glow bg-cyan-500/10 text-cyan-200"
                        : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                    }`}
                  >
                    <span className={`transition-colors ${isActive ? "text-cyan-400" : "text-slate-500 group-hover:text-slate-300"}`}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                        <path d={icons[item.id]} strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </span>
                    <span>{item.label}</span>
                    {isActive && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_2px_rgba(34,211,238,0.5)]" />}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-cyan-900/30 px-6 py-4 text-[10px] tracking-widest text-slate-600">v1.0.0 · ITGC SOX</div>
    </aside>
  );
};

export default SidebarNav;
