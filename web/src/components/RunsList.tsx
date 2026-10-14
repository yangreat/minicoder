import React, { useEffect } from 'react';
import { apiClient } from '../api/client';
import { useStore } from '../store';

export const RunsList: React.FC = () => {
  const { runs, setRuns, setCurrentRun, setError, currentRun } = useStore();

  useEffect(() => {
    const loadRuns = async () => {
      try {
        const fetchedRuns = await apiClient.listRuns();
        setRuns(fetchedRuns);
      } catch (error) {
        setError(error instanceof Error ? error.message : 'Failed to load runs');
      }
    };

    loadRuns();
    const interval = setInterval(loadRuns, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleSelectRun = (runId: string) => {
    const run = runs.find((r) => r.run_id === runId);
    if (run) {
      setCurrentRun(run);
    }
  };

  const handleResume = async (runId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await apiClient.resumeRun(runId, { run_id: runId, use_mock: true });
      const run = await apiClient.getRun(runId);
      setCurrentRun(run);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to resume run');
    }
  };

  return (
    <div className="runs-list">
      <h2>Run History</h2>
      <div className="runs">
        {runs.length === 0 ? (
          <div className="empty">No runs yet</div>
        ) : (
          runs.map((run) => (
            <div
              key={run.run_id}
              className={`run-item ${currentRun?.run_id === run.run_id ? 'active' : ''}`}
              onClick={() => handleSelectRun(run.run_id)}
            >
              <div className="run-header">
                <span className={`status status-${run.state}`}>{run.state}</span>
                <span className="run-id">{run.run_id.substring(0, 8)}</span>
              </div>
              <div className="run-task">{run.task}</div>
              <div className="run-meta">
                <span>{run.total_steps} steps</span>
                <span>{run.token_usage} tokens</span>
                <span>{new Date(run.created_at * 1000).toLocaleString()}</span>
              </div>
              {(run.state === 'failed' || run.state === 'done') && (
                <button
                  className="resume-btn"
                  onClick={(e) => handleResume(run.run_id, e)}
                >
                  Resume
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};
