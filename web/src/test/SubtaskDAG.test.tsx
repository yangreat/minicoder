import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SubtaskDAG } from '../components/SubtaskDAG';
import { useStore } from '../store';

describe('SubtaskDAG', () => {
  it('renders empty state when no run selected', () => {
    render(<SubtaskDAG />);
    expect(screen.getByText(/No run selected/i)).toBeInTheDocument();
  });

  it('renders empty state when no subtasks available', () => {
    useStore.setState({
      currentRun: {
        run_id: 'test-1',
        task: 'Test task',
        repo_path: '.',
        state: 'executing',
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        total_steps: 1,
        token_usage: 100,
      },
      currentEvents: [],
    });

    render(<SubtaskDAG />);
    expect(screen.getByText(/No subtasks yet/i)).toBeInTheDocument();
  });

  it('renders DAG header when subtasks exist', () => {
    useStore.setState({
      currentRun: {
        run_id: 'test-1',
        task: 'Test task',
        repo_path: '.',
        state: 'executing',
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        total_steps: 1,
        token_usage: 100,
      },
      currentEvents: [
        {
          id: 'evt-1',
          run_id: 'test-1',
          timestamp: Date.now() / 1000,
          event_type: 'task_created',
          data: {
            subtask: {
              id: 'task-1',
              description: 'Test subtask',
              status: 'pending',
              priority: 1,
              dependencies: [],
            },
          },
        },
      ],
    });

    render(<SubtaskDAG />);
    expect(screen.getByText(/Task Dependency Graph/i)).toBeInTheDocument();
  });
});
