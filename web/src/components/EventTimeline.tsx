import React, { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { apiClient } from '../api/client';
import { useStore } from '../store';
import type { AgentEvent } from '../types';

export const EventTimeline: React.FC = () => {
  const { currentRun, currentEvents, addEvent, setCurrentEvents, setError, updateRun } = useStore();
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!currentRun) return;

    let cancelled = false;

    const refreshRun = async () => {
      try {
        const run = await apiClient.getRun(currentRun.run_id, currentRun.repo_path);
        if (!cancelled) updateRun(run);
        return run;
      } catch {
        return null;
      }
    };

    const loadEvents = async () => {
      try {
        const events = await apiClient.getRunEvents(currentRun.run_id, currentRun.repo_path);
        if (!cancelled) setCurrentEvents(events);
      } catch (error) {
        if (!cancelled) setError(error instanceof Error ? error.message : 'Failed to load events');
      }
    };

    loadEvents();

    const eventSource = apiClient.createEventSource(currentRun.run_id, currentRun.repo_path);

    eventSource.addEventListener('agent_event', (e) => {
      const event = JSON.parse(e.data) as AgentEvent;
      addEvent(event);
    });

    eventSource.addEventListener('run_complete', () => {
      void loadEvents();
      void refreshRun();
      eventSource.close();
    });

    eventSource.onerror = () => {
      void loadEvents();
    };

    eventSourceRef.current = eventSource;

    const poll = window.setInterval(() => {
      void loadEvents();
      void refreshRun();
    }, 800);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [currentRun?.run_id, currentRun?.repo_path]);

  if (!currentRun) {
    return <div className="event-timeline empty">No run selected</div>;
  }

  return (
    <div className="event-timeline">
      <div className="timeline-header">
        <h2>Event Timeline</h2>
        <div className="run-info">
          <span className={`status status-${currentRun.state}`}>{currentRun.state}</span>
          <span className="steps">{currentRun.total_steps} steps</span>
          <span className="tokens">{currentRun.token_usage} tokens</span>
        </div>
      </div>

      <div className="events">
        {currentEvents.map((event) => (
          <EventItem key={event.id} event={event} />
        ))}
      </div>
    </div>
  );
};

const EventItem: React.FC<{ event: AgentEvent }> = ({ event }) => {
  const renderEventContent = () => {
    switch (event.event_type) {
      case 'run_started':
        return (
          <div className="event-content">
            <strong>Run Started</strong>
            <p>Task: {event.data.task as string}</p>
          </div>
        );

      case 'state_changed':
        return (
          <div className="event-content">
            <strong>State Changed</strong>
            <p>New state: {event.data.new_state as string}</p>
          </div>
        );

      case 'message_added':
        return (
          <div className="event-content">
            <strong>{String(event.data.role)}</strong>
            {event.data.content ? (
              <div className="message-content">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeHighlight]}
                >
                  {String(event.data.content)}
                </ReactMarkdown>
              </div>
            ) : null}
          </div>
        );

      case 'tool_called':
        return (
          <div className="event-content tool-call">
            <strong>Tool Called: {event.data.tool as string}</strong>
            <pre>{JSON.stringify(event.data.arguments, null, 2)}</pre>
          </div>
        );

      case 'tool_result':
        return (
          <div className="event-content tool-result">
            <strong>Tool Result</strong>
            <pre>{JSON.stringify(event.data.result, null, 2)}</pre>
          </div>
        );

      case 'checkpoint_created':
        return (
          <div className="event-content">
            <strong>Checkpoint Created</strong>
            <p>SHA: {event.data.sha as string}</p>
          </div>
        );

      case 'error':
        return (
          <div className="event-content error">
            <strong>Error</strong>
            <p>{event.data.error as string}</p>
          </div>
        );

      case 'task_created': {
        const subtask = event.data.subtask as { description?: string; status?: string } | undefined;
        return (
          <div className="event-content">
            <strong>Subtask created</strong>
            <p>{subtask?.description} ({subtask?.status})</p>
          </div>
        );
      }

      case 'task_status_changed':
        return (
          <div className="event-content">
            <strong>Subtask {String(event.data.new_status)}</strong>
          </div>
        );

      default:
        return (
          <div className="event-content">
            <strong>{event.event_type}</strong>
            <pre>{JSON.stringify(event.data, null, 2)}</pre>
          </div>
        );
    }
  };

  return (
    <div className={`event event-item event-${event.event_type}`} data-testid="event-item">
      <div className="event-time">
        {new Date(event.timestamp * 1000).toLocaleTimeString()}
      </div>
      {renderEventContent()}
    </div>
  );
};
