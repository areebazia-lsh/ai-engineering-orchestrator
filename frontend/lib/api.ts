// API client for AI Engineering Orchestrator

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

interface ApiResponse<T> {
  data?: T;
  error?: string;
}

// Base fetch wrapper
async function apiFetch<T>(endpoint: string, options?: RequestInit): Promise<ApiResponse<T>> {
  try {
    const url = `${API_BASE_URL}${endpoint}`;
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || error.error || `API error: ${response.statusText}`);
    }

    const data = await response.json();
    return { data };
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

// Chat API
export async function createChatMessage({
  project_id,
  session_id,
  message,
  agent_mode,
}: {
  project_id?: string;
  session_id?: string;
  message: string;
  agent_mode?: string;
}) {
  return apiFetch<{
    session_id: string;
    intent?: string;
    workflow?: string;
    plan?: any;
    response: string;
    response_type?: string;
    total_tokens?: number;
    duration_ms?: number;
    agent_steps?: any[];
    error?: string;
    code_modification?: {
      target_file: string;
      diff: string;
      modified_content_preview: string;
    };
  }>(
    '/chat',
    {
      method: 'POST',
      body: JSON.stringify({ project_id, session_id, message, agent_mode }),
    }
  );
}

// Projects API
export async function getProjects() {
  return apiFetch<{ projects: Array<{ id: string; name: string; description?: string }> }>(
    '/projects'
  );
}

export async function createProject(name: string, description?: string) {
  return apiFetch<{ id: string }>(
    '/projects',
    {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    }
  );
}

// Sessions API
export async function getSessions(project_id: string) {
  return apiFetch<{ sessions: Array<{ id: string; title?: string; status: string }> }>(
    `/projects/${project_id}/sessions`
  );
}

export async function createSession(project_id: string, title?: string) {
  return apiFetch<{ id: string }>(
    `/projects/${project_id}/sessions`,
    {
      method: 'POST',
      body: JSON.stringify({ title }),
    }
  );
}

// Ingestion API
export async function ingestProject(project_id: string, repository_paths: string | string[], clear_existing: boolean = false) {
  const paths = Array.isArray(repository_paths) ? repository_paths : [repository_paths];
  return apiFetch<{ status: string; message: string }>(
    `/projects/${project_id}/ingest`,
    {
      method: 'POST',
      body: JSON.stringify({ repository_paths: paths, clear_existing }),
    }
  );
}

export async function getIngestionStatus(project_id: string) {
  return apiFetch<{ project_id: string; ingestion_status: string; ingested_at: any }>(
    `/projects/${project_id}/ingest/status`
  );
}

export async function getKnowledgeStats(project_id: string) {
  return apiFetch<{ vectors: Record<string, number> }>(
    `/projects/${project_id}/knowledge/stats`
  );
}

export async function getProjectFiles(project_id: string) {
  return apiFetch<{ path: string; chunk_count: number }[]>(
    `/projects/${project_id}/knowledge/files`
  );
}

export async function deleteFile(project_id: string, file_path: string) {
  return apiFetch<{ status: string; message: string }>(
    `/projects/${project_id}/files`,
    {
      method: 'DELETE',
      body: JSON.stringify({ file_path }),
    }
  );
}

// Settings API
export async function getSettings() {
  return apiFetch<{
    success: boolean;
    provider: string;
    model: string;
    api_key_masked: string;
  }>('/settings/llm-provider');
}

export async function setSettings({ provider, api_key }: { provider: string; api_key?: string }) {
  return apiFetch<{
    success: boolean;
    provider: string;
    model: string;
    api_key_masked: string;
  }>('/settings/llm-provider', {
    method: 'POST',
    body: JSON.stringify({ provider, api_key }),
  });
}

// Patches API
export async function applyPatch({
  project_id,
  session_id,
  file_path,
  patch_content,
  original_content,
}: {
  project_id: string;
  session_id: string;
  file_path: string;
  patch_content: string;
  original_content: string;
}) {
  return apiFetch<{ success: boolean; patch_id: string }>(
    '/patches/apply',
    {
      method: 'POST',
      body: JSON.stringify({ project_id, session_id, file_path, patch_content, original_content }),
    }
  );
}

export async function rollbackPatch(patch_id: string, reason: string = '') {
  return apiFetch<{ success: boolean }>(
    '/patches/rollback',
    {
      method: 'POST',
      body: JSON.stringify({ patch_id, reason }),
    }
  );
}

export async function getPatchHistory(project_id: string, file_path?: string) {
  return apiFetch<{ id: string; file_path: string; applied_by: string; applied_at: string; rolled_back_at?: string }[]>(
    `/patches/history/${project_id}${file_path ? `?file_path=${encodeURIComponent(file_path)}` : ''}`
  );
}