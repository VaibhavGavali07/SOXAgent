import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { api } from "../api/client";

const DEFAULT_SOFTWARE = [
  "Microsoft Office 365", "Zoom", "Slack", "Google Chrome", "Visual Studio Code",
  "Python 3.11", "Python 3.12", "Node.js LTS", "Docker Desktop", "Git", "Postman",
  "Confluence", "Jira Software", "ServiceNow Agent", "McAfee Endpoint Security",
  "CrowdStrike Falcon", "Okta Verify", "LastPass Enterprise", "Microsoft Teams",
  "Windows Defender", "7-Zip", "Adobe Acrobat Reader", "Notepad++",
];

const Rules = () => {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [softwareText, setSoftwareText] = useState("");
  const [savingSoftware, setSavingSoftware] = useState(false);
  const [swOpen, setSwOpen] = useState(false);
  const [form, setForm] = useState({
    rule_id: "",
    rule_name: "",
    severity: "MEDIUM",
    description: "",
    recommended_action: "",
    control_mapping: "",
    active: true,
  });

  const loadRules = async () => {
    setLoading(true);
    try {
      const data = await api.rules();
      setRules(data);
    } catch {
      toast.error("Failed to load rules");
    } finally {
      setLoading(false);
    }
  };

  const loadSoftwareList = async () => {
    try {
      const configs = await api.getConfigs();
      const compliance = configs.find((c) => c.config_type === "compliance");
      const saved = compliance?.data?.approved_software;
      if (Array.isArray(saved) && saved.length) {
        setSoftwareText(saved.join("\n"));
      } else {
        setSoftwareText(DEFAULT_SOFTWARE.join("\n"));
      }
    } catch {
      setSoftwareText(DEFAULT_SOFTWARE.join("\n"));
    }
  };

  const saveSoftwareList = async () => {
    setSavingSoftware(true);
    try {
      const approved_software = softwareText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      await api.saveConfig({
        config_type: "compliance",
        name: "compliance-default",
        data: { approved_software },
      });
      toast.success("Approved software list saved");
    } catch {
      toast.error("Failed to save approved software list");
    } finally {
      setSavingSoftware(false);
    }
  };

  useEffect(() => {
    loadRules();
    loadSoftwareList();
  }, []);

  const createRule = async () => {
    setSubmitting(true);
    try {
      await api.createRule({
        ...form,
        rule_id: form.rule_id.trim().toUpperCase(),
        rule_name: form.rule_name.trim(),
        control_mapping: form.control_mapping
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      toast.success("Rule created");
      setForm({
        rule_id: "",
        rule_name: "",
        severity: "MEDIUM",
        description: "",
        recommended_action: "",
        control_mapping: "",
        active: true,
      });
      await loadRules();
    } catch (error) {
      toast.error("Failed to create rule");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-6 py-4">
          <h2 className="text-3xl font-semibold text-slate-900">Compliance Rules</h2>
          <p className="mt-1 text-sm text-slate-500">Review default controls and create custom controls for monitoring</p>
        </div>
        <div className="px-6 py-5">
          <div className="overflow-hidden rounded-2xl border border-slate-200">
            <div className="grid grid-cols-[0.8fr_1.6fr_0.8fr_0.8fr_1.6fr_60px] gap-4 bg-slate-100 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-600">
              <div>Rule ID</div>
              <div>Rule Name</div>
              <div>Severity</div>
              <div>Status</div>
              <div>Control Mapping</div>
              <div></div>
            </div>
            {loading ? (
              <div className="px-4 py-10 text-center text-sm text-slate-500">Loading rules...</div>
            ) : (
              <div className="max-h-[460px] overflow-y-auto bg-white">
                {rules.map((rule) => (
                  <div key={rule.rule_id}>
                    <div className="grid grid-cols-[0.8fr_1.6fr_0.8fr_0.8fr_1.6fr_auto] gap-4 border-t border-slate-100 px-4 py-3 text-sm">
                      <div className="font-semibold text-slate-900">{rule.rule_id}</div>
                      <div className="text-slate-700">{rule.rule_name}</div>
                      <div>
                        <span className={`rounded-full px-2 py-1 text-xs font-semibold ${rule.severity === "HIGH" ? "bg-rose-100 text-rose-700" : rule.severity === "MEDIUM" ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"}`}>
                          {rule.severity}
                        </span>
                      </div>
                      <div className="text-slate-600">{rule.active ? "Active" : "Inactive"}</div>
                      <div className="text-slate-600">{(rule.control_mapping || []).join(", ") || "-"}</div>
                      <div>
                        {rule.rule_id === "ITGC-SW-01" && (
                          <button
                            className="text-xs text-blue-600 hover:underline"
                            onClick={() => setSwOpen((v) => !v)}
                          >
                            {swOpen ? "Hide" : "Edit list"}
                          </button>
                        )}
                      </div>
                    </div>
                    {rule.rule_id === "ITGC-SW-01" && swOpen && (
                      <div className="border-t border-slate-100 bg-slate-50 px-4 py-3">
                        <p className="mb-2 text-xs text-slate-500">One software name per line — used by the LLM for ITGC-SW-01 checks.</p>
                        <textarea
                          className="input w-full font-mono text-xs"
                          rows={5}
                          value={softwareText}
                          onChange={(e) => setSoftwareText(e.target.value)}
                        />
                        <div className="mt-2 flex items-center gap-3">
                          <button
                            className="button-primary text-xs disabled:opacity-60"
                            disabled={savingSoftware}
                            onClick={saveSoftwareList}
                          >
                            {savingSoftware ? "Saving..." : "Save"}
                          </button>
                          <span className="text-xs text-slate-400">
                            {softwareText.split("\n").filter((s) => s.trim()).length} entries
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                {!rules.length ? <div className="px-4 py-10 text-center text-sm text-slate-500">No rules available.</div> : null}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <h3 className="text-2xl font-semibold text-slate-900">Create New Rule</h3>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <input
            className="input"
            placeholder="Rule ID (e.g., R101)"
            value={form.rule_id}
            onChange={(event) => setForm((current) => ({ ...current, rule_id: event.target.value }))}
          />
          <input
            className="input"
            placeholder="Rule Name"
            value={form.rule_name}
            onChange={(event) => setForm((current) => ({ ...current, rule_name: event.target.value }))}
          />
          <select className="input" value={form.severity} onChange={(event) => setForm((current) => ({ ...current, severity: event.target.value }))}>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="LOW">LOW</option>
          </select>
          <input
            className="input"
            placeholder="Control mappings (comma separated)"
            value={form.control_mapping}
            onChange={(event) => setForm((current) => ({ ...current, control_mapping: event.target.value }))}
          />
          <textarea
            className="input md:col-span-2"
            rows={3}
            placeholder="Description"
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
          />
          <textarea
            className="input md:col-span-2"
            rows={3}
            placeholder="Recommended action"
            value={form.recommended_action}
            onChange={(event) => setForm((current) => ({ ...current, recommended_action: event.target.value }))}
          />
        </div>
        <div className="mt-4">
          <button className="button-primary disabled:opacity-60" disabled={submitting} onClick={createRule}>
            {submitting ? "Creating..." : "Create Rule"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Rules;

