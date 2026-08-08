'use client';

import { useState } from 'react';
import { applyPatch, rollbackPatch } from '@/lib/api';
import { DiffViewer } from './DiffViewer';

interface PatchApprovalProps {
  projectId: string;
  sessionId: string;
  patchContent: string;
  originalContent: string;
  filePath: string;
  onApproved?: () => void;
  onRejected?: () => void;
}

export function PatchApproval({
  projectId,
  sessionId,
  patchContent,
  originalContent,
  filePath,
  onApproved,
  onRejected,
}: PatchApprovalProps) {
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [patchId, setPatchId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleApprove = async () => {
    setApplying(true);
    setError(null);

    const { data, error: apiError } = await applyPatch({
      project_id: projectId,
      session_id: sessionId,
      file_path: filePath,
      patch_content: patchContent,
      original_content: originalContent,
    });

    setApplying(false);

    if (apiError) {
      setError(apiError);
    } else {
      setPatchId(data?.patch_id || null);
      setApplied(true);
      onApproved?.();
    }
  };

  const handleReject = () => {
    onRejected?.();
  };

  const handleRollback = async () => {
    if (patchId) {
      const { error: rollbackError } = await rollbackPatch(patchId, 'User requested rollback');
      if (!rollbackError) {
        setApplied(false);
        setPatchId(null);
        setError('Patch rolled back');
      } else {
        setError(rollbackError);
      }
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-blue-400">Patch Preview</h3>
        <div className="flex gap-2">
          {!applied && (
            <>
              <button
                onClick={handleApprove}
                disabled={applying}
                className="px-3 py-2 bg-green-600 hover:bg-green-700 rounded disabled:opacity-50"
              >
                {applying ? 'Applying...' : 'Apply Patch'}
              </button>
              <button
                onClick={handleReject}
                className="px-3 py-2 bg-red-600 hover:bg-red-700 rounded"
              >
                Reject
              </button>
            </>
          )}
          {applied && (
            <>
              <button
                onClick={handleRollback}
                className="px-3 py-2 bg-orange-600 hover:bg-orange-700 rounded"
              >
                Rollback
              </button>
              <span className="text-green-400">Patch applied</span>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-2 bg-red-900/30 border border-red-800 rounded text-sm text-red-300">
          Error: {error}
        </div>
      )}

      <DiffViewer
        diff={patchContent}
        originalFile={filePath}
        onApprove={handleApprove}
        onReject={handleReject}
      />
    </div>
  );
}