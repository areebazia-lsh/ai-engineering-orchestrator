'use client';

import { useState } from 'react';

interface DiffViewerProps {
  diff: string;
  originalFile?: string;
  onApprove?: () => void;
  onReject?: () => void;
}

export function DiffViewer({ diff, originalFile, onApprove, onReject }: DiffViewerProps) {
  const [showFullDiff, setShowFullDiff] = useState(false);

  const parseDiff = () => {
    const lines = diff.split('\n');
    const hunks: { header: string; lines: { text: string; type: 'context' | 'add' | 'remove' }[] }[] = [];
    let currentHunk: typeof hunks[0] | null = null;

    lines.forEach(line => {
      if (line.startsWith('diff ') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++') || line.startsWith('@@')) {
        if (currentHunk) hunks.push(currentHunk);
        currentHunk = { header: line, lines: [] };
        if (line.startsWith('@@')) {
          currentHunk = { header: line, lines: [] };
        }
      } else if (line.startsWith('+')) {
        currentHunk?.lines.push({ text: line, type: 'add' });
      } else if (line.startsWith('-')) {
        currentHunk?.lines.push({ text: line, type: 'remove' });
      } else if (line.startsWith(' ')) {
        currentHunk?.lines.push({ text: line, type: 'context' });
      }
    });
    if (currentHunk) hunks.push(currentHunk);

    return hunks;
  };

  const hunks = diff ? parseDiff() : [];

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg overflow-hidden">
      <div className="flex justify-between items-center p-3 border-b border-gray-700 bg-gray-800">
        <div className="text-sm font-medium">
          {originalFile || 'patch.diff'}
          <span className="ml-2 text-xs text-gray-400">{diff.split('\n').length} lines</span>
        </div>
        <div className="flex gap-2">
          {onApprove && (
            <button
              onClick={onApprove}
              className="px-3 py-1 bg-green-600 hover:bg-green-700 rounded text-sm"
            >
              Approve & Apply
            </button>
          )}
          {onReject && (
            <button
              onClick={onReject}
              className="px-3 py-1 bg-red-600 hover:bg-red-700 rounded text-sm"
            >
              Reject
            </button>
          )}
          <button
            onClick={() => setShowFullDiff(!showFullDiff)}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
          >
            {showFullDiff ? 'Show Preview' : 'Show Full Diff'}
          </button>
        </div>
      </div>

      <div className="h-64 overflow-auto bg-gray-950 font-mono text-sm">
        {!diff ? (
          <div className="p-4 text-gray-500">No diff available</div>
        ) : showFullDiff ? (
          <pre className="p-4 whitespace-pre-wrap text-gray-300">
            {diff}
          </pre>
        ) : (
          <div className="p-4 space-y-2">
            {hunks.map((hunk, i) => (
              <div key={i} className="mb-4">
                <div className="text-yellow-500 text-xs mb-2">{hunk.header}</div>
                {hunk.lines.map((line, li) => (
                  <div key={li} className={`font-mono text-xs ${line.type === 'add' ? 'bg-green-900/20 text-green-400' : line.type === 'remove' ? 'bg-red-900/20 text-red-400' : 'text-gray-400'}`}>
                    <span className="inline-block w-8 text-gray-600 select-none">{line.text.slice(0, 2)}</span>
                    <span className="whitespace-pre-wrap">{line.text.slice(2)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}