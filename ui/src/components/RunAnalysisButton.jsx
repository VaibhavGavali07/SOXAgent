import toast from "react-hot-toast";
import { api } from "../api/client";

const RunAnalysisButton = ({ onRunStarted }) => {
  const trigger = async () => {
    const result = await api.fetchServiceNow({});
    onRunStarted(result.run_id);
    toast.success("ServiceNow analysis started");
  };

  return (
    <div className="flex flex-wrap gap-3">
      <button className="button-secondary" onClick={trigger}>
        Run ServiceNow Analysis
      </button>
    </div>
  );
};

export default RunAnalysisButton;
