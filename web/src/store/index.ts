import { create } from 'zustand';
import type { Run, AgentEvent } from '../types';

interface AppState {
  runs: Run[];
  currentRun: Run | null;
  currentEvents: AgentEvent[];
  isLoading: boolean;
  error: string | null;

  setRuns: (runs: Run[]) => void;
  setCurrentRun: (run: Run | null) => void;
  setCurrentEvents: (events: AgentEvent[]) => void;
  addEvent: (event: AgentEvent) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  updateRun: (run: Run) => void;
}

export const useStore = create<AppState>((set) => ({
  runs: [],
  currentRun: null,
  currentEvents: [],
  isLoading: false,
  error: null,

  setRuns: (runs) => set({ runs }),
  setCurrentRun: (run) => set({ currentRun: run }),
  setCurrentEvents: (events) => set({ currentEvents: events }),
  addEvent: (event) => set((state) => {
    if (state.currentEvents.some((existing) => existing.id === event.id)) {
      return state;
    }
    return { currentEvents: [...state.currentEvents, event] };
  }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  updateRun: (run) => set((state) => ({
    runs: state.runs.map((r) => (r.run_id === run.run_id ? run : r)),
    currentRun: state.currentRun?.run_id === run.run_id ? run : state.currentRun,
  })),
}));
