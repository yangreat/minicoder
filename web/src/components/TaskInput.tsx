import React, { useState } from 'react';
import { apiClient } from '../api/client';
import { useStore } from '../store';
import type { StartRunRequest } from '../types';

export const TaskInput: React.FC = () => {
  const [task, setTask] = useState('');
  const [repoPath, setRepoPath] = useState('.');
  const [useMock, setUseMock] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { setError, setCurrentRun, setCurrentEvents } = useStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!task.trim()) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const request: StartRunRequest = {
        task: task.trim(),
        repo_path: repoPath,
        use_mock: useMock,
        max_steps: 30,
      };

      const response = await apiClient.startRun(request);
      const effectiveRepo = (response as { repo_path?: string }).repo_path || repoPath;
      const run = await apiClient.getRun(response.run_id, effectiveRepo);
      setCurrentEvents([]);
      setCurrentRun({ ...run, repo_path: effectiveRepo });
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to start run');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="task-input">
      <h2>New Task</h2>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="task">Task Description</label>
          <textarea
            id="task"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Describe what you want the agent to do..."
            rows={4}
            disabled={isSubmitting}
          />
        </div>

        <div className="form-group">
          <label htmlFor="repoPath">Repository Path</label>
          <input
            id="repoPath"
            type="text"
            value={repoPath}
            onChange={(e) => setRepoPath(e.target.value)}
            placeholder="."
            disabled={isSubmitting}
          />
        </div>

        <div className="form-group checkbox">
          <label>
            <input
              type="checkbox"
              checked={useMock}
              onChange={(e) => setUseMock(e.target.checked)}
              disabled={isSubmitting}
            />
            <span>Demo Mode (Mock LLM)</span>
          </label>
        </div>

        <button type="submit" disabled={isSubmitting || !task.trim()}>
          {isSubmitting ? 'Starting...' : 'Start Run'}
        </button>
      </form>
    </div>
  );
};
