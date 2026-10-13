import React, { useState, useEffect } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { apiClient } from '../api/client';
import { useStore } from '../store';

export const DiffViewer: React.FC = () => {
  const { currentRun, setError } = useStore();
  const [diff, setDiff] = useState('');
  const [original, setOriginal] = useState('');
  const [modified, setModified] = useState('');
  const [checkpoints, setCheckpoints] = useState<Array<{ sha: string; full_sha: string; message: string; timestamp: string }>>([]);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<string | null>(null);

  useEffect(() => {
    if (!currentRun) return;

    const loadDiff = async () => {
      try {
        const result = await apiClient.getDiff(currentRun.run_id, currentRun.repo_path);
        setDiff(result.diff);
        parseDiff(result.diff);
      } catch (error) {
        setError(error instanceof Error ? error.message : 'Failed to load diff');
      }
    };

    const loadCheckpoints = async () => {
      try {
        const cps = await apiClient.listCheckpoints(currentRun.run_id, currentRun.repo_path);
        setCheckpoints(cps);
        if (cps.length > 0) {
          setSelectedCheckpoint(cps[0].full_sha);
        }
      } catch (error) {
        console.error('Failed to load checkpoints:', error);
      }
    };

    loadDiff();
    loadCheckpoints();
  }, [currentRun?.run_id]);

  const parseDiff = (diffText: string) => {
    const lines = diffText.split('\n');
    const origLines: string[] = [];
    const modLines: string[] = [];

    for (const line of lines) {
      if (line.startsWith('-') && !line.startsWith('---')) {
        origLines.push(line.substring(1));
      } else if (line.startsWith('+') && !line.startsWith('+++')) {
        modLines.push(line.substring(1));
      } else if (!line.startsWith('@@') && !line.startsWith('diff')) {
        origLines.push(line);
        modLines.push(line);
      }
    }

    setOriginal(origLines.join('\n'));
    setModified(modLines.join('\n'));
  };

  const handleApprove = () => {
    alert('Changes approved! (In a real implementation, this would commit the changes)');
  };

  const handleReject = async () => {
    if (!currentRun || !selectedCheckpoint) return;

    if (!confirm('Are you sure you want to rollback to this checkpoint? This will revert all changes.')) {
      return;
    }

    try {
      await apiClient.rollback(currentRun.run_id, { checkpoint_sha: selectedCheckpoint }, currentRun.repo_path);
      alert('Successfully rolled back to checkpoint ' + selectedCheckpoint.substring(0, 8));
      
      const result = await apiClient.getDiff(currentRun.run_id, currentRun.repo_path);
      setDiff(result.diff);
      parseDiff(result.diff);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to rollback');
    }
  };

  if (!currentRun) {
    return <div className="diff-viewer empty">No run selected</div>;
  }

  if (!diff) {
    return <div className="diff-viewer empty">No changes yet</div>;
  }

  return (
    <div className="diff-viewer">
      <div className="diff-header">
        <h3>Code Changes</h3>
        <div className="diff-actions">
          {checkpoints.length > 0 && (
            <select
              value={selectedCheckpoint || ''}
              onChange={(e) => setSelectedCheckpoint(e.target.value)}
              className="checkpoint-select"
            >
              {checkpoints.map((cp) => (
                <option key={cp.full_sha} value={cp.full_sha}>
                  {cp.sha} - {cp.message}
                </option>
              ))}
            </select>
          )}
          <button onClick={handleApprove} className="approve-btn">
            ✓ Approve
          </button>
          <button onClick={handleReject} className="reject-btn">
            ✗ Reject & Rollback
          </button>
        </div>
      </div>
      <DiffEditor
        height="600px"
        language="python"
        original={original}
        modified={modified}
        theme="vs-dark"
        options={{
          readOnly: true,
          renderSideBySide: true,
        }}
      />
    </div>
  );
};
