import { TaskInput } from './components/TaskInput';
import { EventTimeline } from './components/EventTimeline';
import { DiffViewer } from './components/DiffViewer';
import { RunsList } from './components/RunsList';
import { useStore } from './store';
import './App.css';

function App() {
  const { error, setError } = useStore();

  return (
    <div className="app">
      <header className="app-header">
        <h1>🤖 MiniCoder Console</h1>
        <p>AI Coding Agent with Task Scheduling & State Management</p>
      </header>

      {error && (
        <div className="error-banner">
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      <div className="app-content">
        <div className="sidebar">
          <TaskInput />
          <RunsList />
        </div>

        <div className="main-content">
          <EventTimeline />
          <DiffViewer />
        </div>
      </div>
    </div>
  );
}

export default App;
