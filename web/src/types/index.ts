export interface Run {
  run_id: string;
  task: string;
  repo_path: string;
  state: 'planning' | 'executing' | 'waiting_tool' | 'done' | 'failed';
  created_at: number;
  updated_at: number;
  total_steps: number;
  token_usage: number;
}

export interface AgentEvent {
  id: string;
  run_id: string;
  timestamp: number;
  event_type: 'run_started' | 'state_changed' | 'message_added' | 'tool_called' | 'tool_result' | 'checkpoint_created' | 'error';
  data: Record<string, unknown>;
}

export interface Checkpoint {
  sha: string;
  full_sha: string;
  message: string;
  timestamp: string;
}

export interface StartRunRequest {
  task: string;
  repo_path?: string;
  model?: string;
  base_url?: string;
  api_key?: string;
  max_steps?: number;
  use_docker?: boolean;
  use_mock?: boolean;
}

export interface ResumeRunRequest {
  run_id: string;
  model?: string;
  base_url?: string;
  api_key?: string;
  max_steps?: number;
  use_mock?: boolean;
}

export interface RollbackRequest {
  checkpoint_sha: string;
}

export interface SSEEvent {
  event: string;
  data: string;
}
