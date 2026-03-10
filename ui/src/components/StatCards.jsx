const StatCards = ({ stats, loading }) => {
  const items = [
    { label: "Tickets analyzed", value: stats?.tickets_analyzed ?? 0 },
    { label: "Violations detected", value: stats?.violations_detected ?? 0 },
    { label: "High-risk violations", value: stats?.high_risk_violations ?? 0 },
    { label: "SoD conflicts", value: stats?.sod_conflicts ?? 0 },
    { label: "Unauthorized software", value: stats?.unauthorized_software_installs ?? 0 }
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      {items.map((item) => (
        <div key={item.label} className="panel overflow-hidden p-5">
          <div className="label">{item.label}</div>
          {loading ? <div className="skeleton mt-4 h-10 w-24" /> : <div className="mt-4 text-4xl font-bold text-ink">{item.value}</div>}
        </div>
      ))}
    </div>
  );
};

export default StatCards;

