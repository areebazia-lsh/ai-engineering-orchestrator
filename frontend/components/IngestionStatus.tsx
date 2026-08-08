'use client';

import { useState, useEffect } from 'react';
import { ingestProject, getIngestionStatus } from '@/lib/api';

interface IngestionStatusProps {
  projectId: string;
  projectName: string;
  onIngested?: () => void;
}

export function IngestionStatus({ projectId, projectName, onIngested }: IngestionStatusProps) {
  const [isIngesting, setIsIngesting] = useState(false);
  const [status, setStatus] = useState<string>('pending');
  const [stats, setStats] = useState<{ project_id: string; ingestion_status: string; ingested_at: any } | null>(null);

  useEffect(() => {
    if (projectId && status === 'pending') {
      checkStatus();
    }
  }, [projectId, status]);

  const checkStatus = async () => {
    const { data, error } = await getIngestionStatus(projectId);
    if (data) {
      setStats(data);
      if (data.ingestion_status === 'done') {
        setStatus('done');
        onIngested?.();
      }
    } else if (error) {
      setStatus('pending');
    }
  };

  const handleIngest = async () => {
    setIsIngesting(true);
    setStatus('running');

    // Use the project's repository path from the backend
    // For now, use a default path - in production, fetch this from the project
    const repoPath = "e:/DevEps/ai-engineering-orchestrator/backend";
    
    const { error } = await ingestProject(projectId, repoPath);

    if (error) {
      setIsIngesting(false);
      setStatus('error');
      alert(`Ingestion failed: ${error}`);
    } else {
      // Poll for completion
      setTimeout(() => checkStatus(), 1000);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-blue-400">Ingestion Status</h3>
        <span className={`text-xs px-2 py-1 rounded ${
          status === 'done' ? 'bg-green-900/30 text-green-400' :
          status === 'error' ? 'bg-red-900/30 text-red-400' :
          status === 'running' ? 'bg-blue-900/30 text-blue-400 animate-pulse' :
          'bg-gray-700 text-gray-300'
        }`}>
          {status.toUpperCase()}
        </span>
      </div>

      <div className="space-y-2 text-sm">
        <p>Project: {projectName}</p>
        {stats ? (
          <>
            <p>Project: {stats.project_id}</p>
            <p>Status: {stats.ingestion_status}</p>
            <p>Ingested at: {stats.ingested_at || 'N/A'}</p>
          </>
        ) : (
          <p className="text-gray-500">No ingestion data yet</p>
        )}
      </div>

      {status !== 'done' && !isIngesting && (
        <button
          onClick={handleIngest}
          className="mt-3 w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm"
        >
          Trigger Ingestion
        </button>
      )}

      {isIngesting && (
        <div className="mt-3 text-center text-blue-400 animate-pulse">
          Ingesting...
        </div>
      )}
    </div>
  );
}