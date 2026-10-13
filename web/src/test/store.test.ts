import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useStore } from '../store';
import type { Run } from '../types';

describe('Store', () => {
  it('should set runs', () => {
    const { result } = renderHook(() => useStore());

    const mockRuns: Run[] = [
      {
        run_id: 'test-1',
        task: 'Test task',
        repo_path: '.',
        state: 'done',
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        total_steps: 5,
        token_usage: 100,
      },
    ];

    act(() => {
      result.current.setRuns(mockRuns);
    });

    expect(result.current.runs).toEqual(mockRuns);
  });

  it('should set current run', () => {
    const { result } = renderHook(() => useStore());

    const mockRun: Run = {
      run_id: 'test-1',
      task: 'Test task',
      repo_path: '.',
      state: 'done',
      created_at: Date.now() / 1000,
      updated_at: Date.now() / 1000,
      total_steps: 5,
      token_usage: 100,
    };

    act(() => {
      result.current.setCurrentRun(mockRun);
    });

    expect(result.current.currentRun).toEqual(mockRun);
  });

  it('should add events', () => {
    const { result } = renderHook(() => useStore());

    const mockEvent = {
      id: 'evt-1',
      run_id: 'test-1',
      timestamp: Date.now() / 1000,
      event_type: 'run_started' as const,
      data: {},
    };

    act(() => {
      result.current.addEvent(mockEvent);
    });

    expect(result.current.currentEvents).toContainEqual(mockEvent);
  });
});
