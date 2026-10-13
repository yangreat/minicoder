import type {
  Run,
  AgentEvent,
  Checkpoint,
  StartRunRequest,
  ResumeRunRequest,
  RollbackRequest,
} from '../types';

const API_BASE = '/api';

class ApiClient {
  async listRuns(repoPath = '.', limit = 50): Promise<Run[]> {
    const response = await fetch(`${API_BASE}/runs?repo_path=${encodeURIComponent(repoPath)}&limit=${limit}`);
    if (!response.ok) throw new Error('Failed to fetch runs');
    return response.json();
  }

  async getRun(runId: string, repoPath = '.'): Promise<Run> {
    const response = await fetch(`${API_BASE}/runs/${runId}?repo_path=${encodeURIComponent(repoPath)}`);
    if (!response.ok) throw new Error('Failed to fetch run');
    return response.json();
  }

  async getRunEvents(runId: string, repoPath = '.', limit?: number): Promise<AgentEvent[]> {
    const url = new URL(`${window.location.origin}${API_BASE}/runs/${runId}/events`);
    url.searchParams.set('repo_path', repoPath);
    if (limit) url.searchParams.set('limit', limit.toString());

    const response = await fetch(url.toString());
    if (!response.ok) throw new Error('Failed to fetch events');
    return response.json();
  }

  async startRun(request: StartRunRequest): Promise<{ run_id: string; status: string }> {
    const response = await fetch(`${API_BASE}/runs/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!response.ok) throw new Error('Failed to start run');
    return response.json();
  }

  async resumeRun(runId: string, request: ResumeRunRequest): Promise<{ run_id: string; status: string }> {
    const response = await fetch(`${API_BASE}/runs/${runId}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!response.ok) throw new Error('Failed to resume run');
    return response.json();
  }

  async abortRun(runId: string): Promise<{ status: string }> {
    const response = await fetch(`${API_BASE}/runs/${runId}/abort`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to abort run');
    return response.json();
  }

  async listCheckpoints(runId: string, repoPath = '.'): Promise<Checkpoint[]> {
    const response = await fetch(`${API_BASE}/runs/${runId}/checkpoints?repo_path=${encodeURIComponent(repoPath)}`);
    if (!response.ok) throw new Error('Failed to fetch checkpoints');
    return response.json();
  }

  async rollback(runId: string, request: RollbackRequest, repoPath = '.'): Promise<{ status: string; checkpoint: string }> {
    const response = await fetch(`${API_BASE}/runs/${runId}/rollback?repo_path=${encodeURIComponent(repoPath)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!response.ok) throw new Error('Failed to rollback');
    return response.json();
  }

  async getDiff(runId: string, repoPath = '.', fromSha?: string): Promise<{ diff: string }> {
    const url = new URL(`${window.location.origin}${API_BASE}/runs/${runId}/diff`);
    url.searchParams.set('repo_path', repoPath);
    if (fromSha) url.searchParams.set('from_sha', fromSha);

    const response = await fetch(url.toString());
    if (!response.ok) throw new Error('Failed to fetch diff');
    return response.json();
  }

  createEventSource(runId: string, repoPath = '.'): EventSource {
    return new EventSource(`${API_BASE}/runs/${runId}/stream?repo_path=${encodeURIComponent(repoPath)}`);
  }
}

export const apiClient = new ApiClient();
