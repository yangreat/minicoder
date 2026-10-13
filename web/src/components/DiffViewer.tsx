import React, { useState, useEffect } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { apiClient } from '../api/client';
import { useStore } from '../store';

export const DiffViewer: React.FC = () => {
  const { currentRun, setError } = useStore();
  const [diff, setDiff] = useState('');
  const [original, setOriginal] = useState('');
  const [modified, setModified] = useState('');

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

    loadDiff();
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
