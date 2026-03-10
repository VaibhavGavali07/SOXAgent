import ConnectionForms from "../components/ConnectionForms";

const Connections = ({ configs, onSaved }) => (
  <div className="space-y-5">
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Connections</div>
      <h2 className="mt-2 text-2xl font-semibold text-slate-900">Platform configuration</h2>
      <p className="mt-2 max-w-3xl text-sm text-slate-500">
        Configure LLM providers, ServiceNow, and notifications.
      </p>
    </div>
    <ConnectionForms configs={configs} onSaved={onSaved} />
  </div>
);

export default Connections;
