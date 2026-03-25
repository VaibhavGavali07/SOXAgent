import { useEffect, useMemo, useRef, useState } from "react";
import toast from "react-hot-toast";
import { api } from "../api/client";

// ---------------------------------------------------------------------------
// Scheduled Auto-Fetch section
// ---------------------------------------------------------------------------
const INTERVAL_PRESETS = [
  { label: "Every 15 minutes", type: "minutes", value: 15 },
  { label: "Every 30 minutes", type: "minutes", value: 30 },
  { label: "Every 1 hour",     type: "hours",   value: 1  },
  { label: "Every 2 hours",    type: "hours",   value: 2  },
  { label: "Every 4 hours",    type: "hours",   value: 4  },
  { label: "Every 6 hours",    type: "hours",   value: 6  },
  { label: "Every 12 hours",   type: "hours",   value: 12 },
  { label: "Every 24 hours",   type: "hours",   value: 24 },
  { label: "Daily at a specific time", type: "daily", value: 0 },
];

const ScheduleSection = () => {
  const [schedule, setSchedule] = useState({
    enabled: false,
    interval_type: "hours",
    interval_value: 1,
    daily_time: "09:00",
    mode: "append",
  });
  const [nextRunTime, setNextRunTime] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  const selectedPresetIdx = INTERVAL_PRESETS.findIndex(
    (p) => p.type === schedule.interval_type && (p.type === "daily" || p.value === schedule.interval_value)
  );

  useEffect(() => {
    api.getSchedule()
      .then((data) => {
        setSchedule({
          enabled: data.enabled ?? false,
          interval_type: data.interval_type ?? "hours",
          interval_value: data.interval_value ?? 1,
          daily_time: data.daily_time ?? "09:00",
          mode: data.mode ?? "append",
        });
        setNextRunTime(data.next_run_time ?? null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handlePresetChange = (idx) => {
    const preset = INTERVAL_PRESETS[Number(idx)];
    if (!preset) return;
    setSchedule((s) => ({ ...s, interval_type: preset.type, interval_value: preset.value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const data = await api.saveSchedule(schedule);
      setNextRunTime(data.next_run_time ?? null);
      toast.success(schedule.enabled ? "Schedule saved & activated" : "Schedule saved (disabled)");
    } catch {
      toast.error("Failed to save schedule");
    } finally {
      setSaving(false);
    }
  };

  const handleDisable = async () => {
    setSaving(true);
    try {
      await api.disableSchedule();
      setSchedule((s) => ({ ...s, enabled: false }));
      setNextRunTime(null);
      toast.success("Schedule disabled");
    } catch {
      toast.error("Failed to disable schedule");
    } finally {
      setSaving(false);
    }
  };

  const formatNextRun = (iso) => {
    if (!iso) return null;
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  if (loading) return null;

  return (
    <div className="panel p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="label">Automation</div>
          <h3 className="mt-2 font-display text-2xl text-ink">Scheduled Auto-Fetch</h3>
          <p className="mt-1 text-sm text-slate-500">
            Automatically fetch and analyse ServiceNow tickets on a recurring schedule.
          </p>
        </div>
        {schedule.enabled && (
          <span className="mt-1 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700 whitespace-nowrap">
            Active
          </span>
        )}
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {/* Enable toggle */}
        <label className="col-span-full flex cursor-pointer items-center gap-3">
          <div
            className={`relative h-6 w-11 rounded-full transition-colors duration-200 ${schedule.enabled ? "bg-cyan-500" : "bg-slate-300"}`}
            onClick={() => setSchedule((s) => ({ ...s, enabled: !s.enabled }))}
          >
            <span className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-200 ${schedule.enabled ? "translate-x-5" : "translate-x-0"}`} />
          </div>
          <span className="text-sm font-medium text-slate-700">
            {schedule.enabled ? "Enabled — fetch will run automatically" : "Disabled — no automatic fetch"}
          </span>
        </label>

        {/* Interval preset */}
        <label className="block">
          <div className="mb-2 text-sm font-medium text-slate-600">Fetch Interval</div>
          <select
            className="input"
            value={selectedPresetIdx >= 0 ? selectedPresetIdx : 2}
            onChange={(e) => handlePresetChange(e.target.value)}
            disabled={!schedule.enabled}
          >
            {INTERVAL_PRESETS.map((p, i) => (
              <option key={i} value={i}>{p.label}</option>
            ))}
          </select>
        </label>

        {/* Daily time picker — only shown for "daily" */}
        {schedule.interval_type === "daily" && (
          <label className="block">
            <div className="mb-2 text-sm font-medium text-slate-600">Run at (UTC)</div>
            <input
              type="time"
              className="input"
              value={schedule.daily_time}
              disabled={!schedule.enabled}
              onChange={(e) => setSchedule((s) => ({ ...s, daily_time: e.target.value }))}
            />
          </label>
        )}

        {/* Fetch mode */}
        <label className="block">
          <div className="mb-2 text-sm font-medium text-slate-600">Fetch Mode</div>
          <select
            className="input"
            value={schedule.mode}
            disabled={!schedule.enabled}
            onChange={(e) => setSchedule((s) => ({ ...s, mode: e.target.value }))}
          >
            <option value="append">Append — keep existing, add new tickets</option>
            <option value="clean">Clean — clear existing data, fresh fetch</option>
          </select>
        </label>
      </div>

      {/* Next run status banner */}
      {schedule.enabled && nextRunTime && (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-800">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
          Next scheduled run: <span className="font-semibold">{formatNextRun(nextRunTime)}</span>
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-3">
        <button
          className="button-primary disabled:cursor-not-allowed disabled:opacity-60"
          disabled={saving}
          onClick={handleSave}
        >
          {saving ? "Saving..." : "Save Schedule"}
        </button>
        {schedule.enabled && (
          <button
            className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm font-semibold text-rose-700 transition hover:bg-rose-100 disabled:opacity-60"
            disabled={saving}
            onClick={handleDisable}
          >
            Disable
          </button>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Multi-recipient email input
// ---------------------------------------------------------------------------
const EmailRecipientsInput = ({ value, onChange }) => {
  const [draft, setDraft] = useState("");
  const inputRef = useRef(null);

  // value is a comma-separated string; split into array for display
  const recipients = value
    ? value.split(",").map((s) => s.trim()).filter(Boolean)
    : [];

  const addEmail = () => {
    const email = draft.trim().toLowerCase();
    if (!email) return;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      toast.error("Enter a valid email address");
      return;
    }
    if (recipients.includes(email)) {
      toast.error("Already in the list");
      return;
    }
    onChange([...recipients, email].join(", "));
    setDraft("");
    inputRef.current?.focus();
  };

  const remove = (email) => {
    onChange(recipients.filter((r) => r !== email).join(", "));
  };

  return (
    <div>
      {/* chips */}
      {recipients.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {recipients.map((email) => (
            <span
              key={email}
              className="flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 pl-3 pr-2 py-1 text-xs font-medium text-blue-700"
            >
              {email}
              <button
                type="button"
                className="flex h-4 w-4 items-center justify-center rounded-full bg-blue-200 text-blue-700 hover:bg-blue-300"
                onClick={() => remove(email)}
                aria-label={`Remove ${email}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {/* add row */}
      <div className="flex gap-2">
        <input
          ref={inputRef}
          className="input flex-1"
          type="email"
          placeholder="name@company.com"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addEmail(); } }}
        />
        <button
          type="button"
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          onClick={addEmail}
        >
          Add
        </button>
      </div>
      {recipients.length > 0 && (
        <p className="mt-1.5 text-xs text-slate-400">{recipients.length} recipient{recipients.length > 1 ? "s" : ""}</p>
      )}
    </div>
  );
};

const seed = {
  llm: { provider: "mock", deployment_name: "mock-llm", api_key: "", endpoint: "", api_version: "" },
  servicenow: { instance_url: "", client_id: "", client_secret: "", table: "incident" },
  notifications: { smtp_host: "", smtp_port: "587", smtp_user: "", smtp_password: "", email_from: "", email_to: "audit@example.com", webhook_url: "" }
};

const sections = [
  { key: "llm", title: "LLM Provider", fields: ["provider", "deployment_name", "api_key", "endpoint", "api_version"] },
  { key: "servicenow", title: "ServiceNow", fields: ["instance_url", "client_id", "client_secret", "table"] },
  { key: "notifications", title: "Email Notifications", fields: ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "email_from", "email_to", "webhook_url"] }
];

const SENSITIVE_TERMS = ["password", "token", "key", "secret"];
const isSensitiveField = (field) => SENSITIVE_TERMS.some((t) => field.toLowerCase().includes(t));

const ConnectionForms = ({ configs, onSaved }) => {
  // Track which config types have been saved to DB (for the "Saved" placeholder on sensitive fields)
  const savedTypes = useMemo(() => new Set(configs.map((c) => c.config_type)), [configs]);

  const existing = useMemo(() => {
    const mapped = {
      llm: { ...seed.llm },
      servicenow: { ...seed.servicenow },
      notifications: { ...seed.notifications },
    };
    configs.forEach((config) => {
      if (mapped[config.config_type] !== undefined) {
        mapped[config.config_type] = { ...mapped[config.config_type], ...config.data };
      }
    });
    if (mapped.servicenow.username && !mapped.servicenow.client_id) {
      mapped.servicenow.client_id = mapped.servicenow.username;
    }
    if (mapped.servicenow.password && !mapped.servicenow.client_secret) {
      mapped.servicenow.client_secret = mapped.servicenow.password;
    }
    return mapped;
  }, [configs]);

  const [values, setValues] = useState(existing);
  const [savingKey, setSavingKey] = useState("");
  const [testingKey, setTestingKey] = useState("");
  const [clearing, setClearing] = useState(false);
  const [includeConfigs, setIncludeConfigs] = useState(false);

  useEffect(() => {
    setValues(existing);
  }, [existing]);

  const saveSection = async (configType) => {
    setSavingKey(configType);
    try {
      // Strip blank sensitive fields so we don't overwrite saved credentials with empty strings
      const data = Object.fromEntries(
        Object.entries(values[configType]).filter(
          ([field, val]) => !(isSensitiveField(field) && val === "" && savedTypes.has(configType))
        )
      );
      await api.saveConfig({ config_type: configType, name: `${configType}-default`, data });
      toast.success(`${configType} config saved`);
      onSaved();
    } catch (error) {
      toast.error(`Failed to save ${configType} config`);
    } finally {
      setSavingKey("");
    }
  };

  const testSection = async (configType) => {
    setTestingKey(configType);
    try {
      if (configType === "llm") {
        const result = await api.testLLM(values.llm);
        if (result.skipped) {
          toast(result.message || "Mock provider selected. Live connection test skipped.");
          return;
        }
        if (!result.ok) {
          toast.error(result.message || "LLM test failed");
          return;
        }
        toast.success(result.message || `LLM test passed: ${result.provider}/${result.deployment_name}`);
        return;
      }
      if (configType === "servicenow") {
        const result = await api.testServiceNow(values.servicenow);
        toast.success(result.message || `ServiceNow test passed: ${result.tickets_found} tickets available`);
        return;
      }
      if (configType === "notifications") {
        const result = await api.testNotifications(values.notifications);
        toast.success(result.message || `Notification test passed: ${result.target}`);
      }
    } catch (error) {
      toast.error(`Failed to test ${configType} connection`);
    } finally {
      setTestingKey("");
    }
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-2">
        {sections.map((section) => (
          <div key={section.key} className="panel p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="label">{section.title}</div>
                <h3 className="mt-2 font-display text-2xl text-ink">Connection setup</h3>
              </div>
              {savedTypes.has(section.key) && (
                <span className="mt-1 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                  Configured
                </span>
              )}
            </div>
            <div className="mt-5 grid gap-4">
              {section.fields.map((field) => (
                <label key={field} className="block">
                  <div className="mb-2 text-sm font-medium capitalize text-slate-600">{field.replaceAll("_", " ")}</div>
                  {section.key === "llm" && field === "provider" ? (
                    <select
                      className="input"
                      value={values[section.key]?.[field] ?? "mock"}
                      onChange={(event) =>
                        setValues((current) => ({
                          ...current,
                          [section.key]: { ...current[section.key], [field]: event.target.value }
                        }))
                      }
                    >
                      <option value="mock">mock</option>
                      <option value="openai">openai</option>
                      <option value="azure_openai">azure_openai</option>
                      <option value="gemini">gemini</option>
                    </select>
                  ) : section.key === "notifications" && field === "email_to" ? (
                    <EmailRecipientsInput
                      value={values.notifications?.email_to ?? ""}
                      onChange={(val) =>
                        setValues((current) => ({
                          ...current,
                          notifications: { ...current.notifications, email_to: val }
                        }))
                      }
                    />
                  ) : (
                    <input
                      className="input"
                      type={isSensitiveField(field) ? "password" : "text"}
                      placeholder={
                        isSensitiveField(field) && savedTypes.has(section.key)
                          ? "Saved — leave blank to keep current"
                          : section.key === "llm" && field === "api_version"
                            ? "optional — defaults to 2024-02-01"
                            : ""
                      }
                      value={values[section.key]?.[field] ?? ""}
                      onChange={(event) =>
                        setValues((current) => ({
                          ...current,
                          [section.key]: { ...current[section.key], [field]: event.target.value }
                        }))
                      }
                    />
                  )}
                </label>
              ))}
            </div>
            <div className="mt-5 flex flex-wrap gap-3">
              <button className="button-primary disabled:cursor-not-allowed disabled:opacity-60" disabled={Boolean(savingKey || testingKey || clearing)} onClick={() => saveSection(section.key)}>
                {savingKey === section.key ? "Saving..." : "Save"}
              </button>
              <button className="button-secondary disabled:cursor-not-allowed disabled:opacity-60" disabled={Boolean(savingKey || testingKey || clearing)} onClick={() => testSection(section.key)}>
                {testingKey === section.key ? "Testing..." : "Test"}
              </button>
            </div>
          </div>
        ))}
      </div>

      <ScheduleSection />

      <div className="panel border-rose-200 bg-rose-50/40 p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="label text-rose-700">Data management</div>
            <h3 className="mt-2 text-2xl font-semibold text-rose-900">Clear Compliance Data</h3>
            <p className="mt-2 text-sm text-rose-800">
              This deletes all ingested tickets, rule results, alerts, runs, reports, and notifications from SQLite.
            </p>
            <label className="mt-3 inline-flex items-center gap-2 text-sm text-rose-900">
              <input
                type="checkbox"
                checked={includeConfigs}
                onChange={(event) => setIncludeConfigs(event.target.checked)}
              />
              Also delete saved configs (LLM/ServiceNow/Notifications and custom rules)
            </label>
          </div>
          <button
            className="rounded-lg bg-rose-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-rose-800 disabled:opacity-60"
            disabled={Boolean(savingKey || testingKey || clearing)}
            onClick={async () => {
              const msg = includeConfigs
                ? "Delete all compliance data and saved configs?"
                : "Delete all compliance data (keeping saved configs)?";
              if (!window.confirm(msg)) return;
              setClearing(true);
              try {
                const result = await api.clearComplianceData({ include_configs: includeConfigs });
                toast.success(result.message || "Compliance data cleared");
                onSaved();
              } catch {
                toast.error("Failed to clear compliance data");
              } finally {
                setClearing(false);
              }
            }}
          >
            {clearing ? "Clearing..." : "Clear Compliance Data"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConnectionForms;
