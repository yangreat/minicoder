import React, { useEffect, useState } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useStore } from '../store';
import type { AgentEvent } from '../types';

interface SubtaskNode {
  id: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'blocked';
  priority: number;
  dependencies: string[];
}

export const SubtaskDAG: React.FC = () => {
  const { currentRun, currentEvents } = useStore();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [subtasks, setSubtasks] = useState<Map<string, SubtaskNode>>(new Map());

  useEffect(() => {
    if (!currentEvents) return;

    const taskMap = new Map<string, SubtaskNode>();

    currentEvents.forEach((event: AgentEvent) => {
      if (event.event_type === 'task_created' && event.data.subtask) {
        const task = event.data.subtask as SubtaskNode;
        taskMap.set(task.id, task);
      } else if (event.event_type === 'task_status_changed' && event.data.task_id) {
        const taskId = event.data.task_id as string;
        const existing = taskMap.get(taskId);
        if (existing) {
          taskMap.set(taskId, {
            ...existing,
            status: event.data.new_status as SubtaskNode['status'],
          });
        }
      }
    });

    setSubtasks(taskMap);
  }, [currentEvents]);

  useEffect(() => {
    if (subtasks.size === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }

    const flowNodes: Node[] = [];
    const flowEdges: Edge[] = [];

    const taskArray = Array.from(subtasks.values()).sort((a, b) => b.priority - a.priority);

    taskArray.forEach((task, index) => {
      const statusColors = {
        pending: '#94a3b8',
        running: '#3b82f6',
        completed: '#10b981',
        failed: '#ef4444',
        blocked: '#f59e0b',
      };

      flowNodes.push({
        id: task.id,
        type: 'default',
        position: { x: 40 + (index % 3) * 280, y: 40 + Math.floor(index / 3) * 140 },
        data: {
          label: (
            <div style={{ padding: '10px', minWidth: '200px' }}>
              <div style={{ fontWeight: 'bold', marginBottom: '5px' }}>
                {task.description}
              </div>
              <div style={{ fontSize: '12px', color: '#64748b' }}>
                Priority: {task.priority} | Status: {task.status}
              </div>
            </div>
          ),
        },
        style: {
          background: '#1e293b',
          color: '#f1f5f9',
          border: `2px solid ${statusColors[task.status]}`,
          borderRadius: '8px',
          fontSize: '14px',
        },
      });

      task.dependencies.forEach((depId) => {
        if (subtasks.has(depId)) {
          flowEdges.push({
            id: `${depId}-${task.id}`,
            source: depId,
            target: task.id,
            type: 'smoothstep',
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { stroke: '#64748b' },
          });
        }
      });
    });

    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [subtasks, setNodes, setEdges]);

  if (!currentRun) {
    return (
      <div className="subtask-dag empty">
        <p>No run selected</p>
      </div>
    );
  }

  if (subtasks.size === 0) {
    return (
      <div className="subtask-dag empty">
        <p>No subtasks available. Subtask decomposition coming soon.</p>
      </div>
    );
  }

  return (
    <div className="subtask-dag" data-testid="subtask-dag">
      <div className="dag-header">
        <h3>Task Dependency Graph</h3>
        <div className="legend">
          <span className="legend-item">
            <span className="legend-dot" style={{ background: '#94a3b8' }}></span>
            Pending
          </span>
          <span className="legend-item">
            <span className="legend-dot" style={{ background: '#3b82f6' }}></span>
            Running
          </span>
          <span className="legend-item">
            <span className="legend-dot" style={{ background: '#10b981' }}></span>
            Completed
          </span>
          <span className="legend-item">
            <span className="legend-dot" style={{ background: '#ef4444' }}></span>
            Failed
          </span>
        </div>
      </div>
      <div style={{ height: '500px', background: '#0f172a' }}>
        <ReactFlow
          key={nodes.length}
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          fitView
        >
          <Controls />
          <Background color="#475569" gap={16} />
        </ReactFlow>
      </div>
    </div>
  );
};
