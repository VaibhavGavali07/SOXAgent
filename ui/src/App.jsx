import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";
import { api } from "./api/client";
import RunModeModal from "./components/RunModeModal";
import SidebarNav from "./components/SidebarNav";
import Connections from "./pages/Connections";
import Dashboard from "./pages/Dashboard";
import Rules from "./pages/Rules";
import TicketInfo from "./pages/TicketInfo";
import Violations from "./pages/Violations";

const App = () => {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [configs, setConfigs] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [refreshingSummary, setRefreshingSummary] = useState(false);
  const [backendOnline, setBackendOnline] = useState(null);
  const [runId, setRunId] = useState("");
  const [runProgress, setRunProgress] = useState({
    status: "idle",
    progress: 0,
    total: 0,
    message: "",
  });
  const [runEvents, setRunEvents] = useState([]);
  const [showProgress, setShowProgress] = useState(false);
  const [lastCompletedRunId, setLastCompletedRunId] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [runningSource, setRunningSource] = useState("");
  const [ticketPreset, setTicketPreset] = useState({});
  const [showRunModal, setShowRunModal] = useState(false);
  const suppressAutoRefreshRef = useRef(false);

  const checkBackend = async () => {
    try {
      await api.health();
      setBackendOnline(true);
      return true;
    } catch {
      setBackendOnline(false);
      return false;
    }
  };

  const loadConfigs = async () => {
    try {
      const data = await api.getConfigs();
      setConfigs(data);
    } catch {
      toast.error("Failed to load configs");
    }
  };

  const loadSummary = async ({ initial = false } = {}) => {
    if (initial) {
      setLoadingSummary(true);
    } else {
      setRefreshingSummary(true);
    }
    try {
      const data = await api.dashboardSummary();
      setSummary(data);
      if (data.latest_run?.run_id && !runId) {
        setRunId(data.latest_run.run_id);
      }
    } catch {
      toast.error("Failed to load dashboard summary");
    } finally {
      if (initial) {
        setLoadingSummary(false);
      } else {
        setRefreshingSummary(false);
      }
    }
  };

  useEffect(() => {
    const bootstrap = async () => {
      const online = await checkBackend();
      if (!online) {
        setLoadingSummary(false);
        return;
      }
      loadConfigs();
      loadSummary({ initial: true });
    };
    bootstrap();
  }, []);

  const handleRunStarted = (nextRunId) => {
    setRunId(nextRunId);
    setRunEvents([]);
    setRunProgress({ status: "running", progress: 0, total: 0, message: "Starting compliance scan..." });
    setActiveTab("dashboard");
  };

  const handleConnectionSaved = async () => {
    await loadConfigs();
    await loadSummary({ initial: false });
    setRefreshKey((value) => value + 1);
  };

  const openTicketsWithFilters = (filters = {}) => {
    setTicketPreset({ ...filters, __ts: Date.now() });
    setActiveTab("tickets");
  };

  const waitForRunCompletion = (pendingRunId) =>
    new Promise((resolve, reject) => {
      const source = new EventSource(api.runEventsUrl(pendingRunId));
      source.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.status === "completed") {
          source.close();
          resolve(payload);
          return;
        }
        if (payload.status === "failed") {
          source.close();
          reject(new Error(payload.message || `Run ${pendingRunId} failed`));
        }
      };
      source.onerror = () => {
        source.close();
        reject(new Error(`Run ${pendingRunId} stream disconnected`));
      };
    });

  const triggerFetchNowTickets = async (mode = "append") => {
    if (backendOnline === false || runningSource) return;
    try {
      suppressAutoRefreshRef.current = true;
      setRunningSource("all");
      setRunEvents([]);
      setRunProgress({ status: "running", progress: 0, total: 0, message: "Starting ServiceNow scan..." });
      setActiveTab("dashboard");
      if (mode === "clean") {
        await api.clearComplianceData({ include_configs: false });
      }
      const serviceNowResult = await api.fetchServiceNow({});
      setRunId(serviceNowResult.run_id);
      await waitForRunCompletion(serviceNowResult.run_id);

      setLastCompletedRunId(serviceNowResult.run_id);
      setRefreshKey((value) => value + 1);
      await loadSummary({ initial: false });
      toast.success("ServiceNow analysis completed");
    } catch {
      toast.error("Failed to complete fetch and analysis");
    } finally {
      suppressAutoRefreshRef.current = false;
      setRunningSource("");
    }
  };

  useEffect(() => {
    if (runProgress.status === "running") {
      setShowProgress(true);
      return undefined;
    }
    if (runProgress.status === "completed" || runProgress.status === "failed") {
      setShowProgress(true);
      const timer = window.setTimeout(() => setShowProgress(false), 2500);
      return () => window.clearTimeout(timer);
    }
    setShowProgress(false);
    return undefined;
  }, [runProgress.status]);

  useEffect(() => {
    if (!runId) return;
    setRunEvents([]);
    const source = new EventSource(api.runEventsUrl(runId));
    source.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      const nextStatus = payload.status || "running";
      setRunEvents((current) => [payload, ...current].slice(0, 6));
      setRunProgress((current) => ({
        status: nextStatus,
        progress: typeof payload.progress === "number" ? payload.progress : current.progress,
        total: typeof payload.total === "number" ? payload.total : current.total,
        message: payload.message || current.message,
      }));
      if (nextStatus === "completed" || nextStatus === "failed") {
        setRunningSource("");
        if (!suppressAutoRefreshRef.current && runId && runId !== lastCompletedRunId) {
          setLastCompletedRunId(runId);
          setRefreshKey((value) => value + 1);
          loadSummary({ initial: false });
        }
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, [runId, lastCompletedRunId]);

  const progressPercent =
    runProgress.total > 0
      ? Math.min(100, Math.round((runProgress.progress / runProgress.total) * 100))
      : runProgress.status === "completed"
        ? 100
        : 0;

  return (
    <div className="min-h-screen bg-[#edf2f7] text-ink">
      <div className="flex min-h-screen flex-col lg:flex-row lg:items-start">
        <SidebarNav activeTab={activeTab} onChange={setActiveTab} />
        <main className="min-w-0 flex-1">
          <div className="border-b border-slate-200 bg-white px-6 py-5 lg:px-8">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-2xl font-semibold text-slate-900">Compliance Dashboard</h1>
                <p className="mt-1 text-sm text-slate-500">Real-time ITGC monitoring across ServiceNow</p>
                {backendOnline === false ? (
                  <p className="mt-2 text-sm font-medium text-rose-600">
                    Backend is offline at {api.apiBase}. Start FastAPI and click Retry Connection.
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                  onClick={async () => {
                    const online = await checkBackend();
                    if (online) {
                      await loadConfigs();
                      await loadSummary({ initial: false });
                      toast.success("Backend connection restored");
                    } else {
                      toast.error("Backend is still offline");
                    }
                  }}
                >
                  Retry Connection
                </button>
                <button
                  className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                  disabled={Boolean(runningSource) || backendOnline === false}
                  onClick={() => setShowRunModal(true)}
                >
                  {runningSource === "all" ? "Fetching Tickets..." : "Fetch Now Tickets"}
                </button>
                <div className="flex items-center gap-2 text-sm font-medium text-emerald-600">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                  <span>Monitoring Active</span>
                </div>
              </div>
            </div>
            {showProgress ? (
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-4 text-sm">
                  <div className="font-medium text-slate-700">
                    {runProgress.message || "Compliance scan in progress"}
                  </div>
                  <div className="text-slate-600">
                    {runProgress.status === "completed" ? "Completed" : `${progressPercent}%`}
                  </div>
                </div>
                <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${
                      runProgress.status === "failed" ? "bg-rose-500" : "bg-teal-600"
                    }`}
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
              </div>
            ) : null}
          </div>

          <div className="px-6 py-6 lg:px-8">
            {activeTab === "connections" ? <Connections configs={configs} onSaved={handleConnectionSaved} /> : null}
            {activeTab === "dashboard" ? (
              <Dashboard
                summary={summary}
                loading={loadingSummary}
                refreshing={refreshingSummary}
                runId={runId}
                runProgress={runProgress}
                runEvents={runEvents}
                onRefresh={() => loadSummary({ initial: false })}
                onOpenTickets={openTicketsWithFilters}
              />
            ) : null}
            {activeTab === "violations" ? <Violations refreshKey={refreshKey} /> : null}
            {activeTab === "rules" ? <Rules /> : null}
            {activeTab === "tickets" ? <TicketInfo refreshKey={refreshKey} onRunStarted={handleRunStarted} presetFilters={ticketPreset} /> : null}
          </div>
        </main>
      </div>
      {showRunModal && (
        <RunModeModal
          onSelect={(mode) => { setShowRunModal(false); triggerFetchNowTickets(mode); }}
          onCancel={() => setShowRunModal(false)}
        />
      )}
    </div>
  );
};

export default App;
