'use client';

import { useState, useEffect, useRef } from 'react';
import { createChatMessage, getProjects, createProject, getKnowledgeStats, getSettings, setSettings, ingestProject, getIngestionStatus, applyPatch, rollbackPatch } from '@/lib/api';
import { connectWebSocket, disconnectWebSocket, onStep, onFinalResponse } from '@/lib/websocket';
import { DiffViewer } from '../components/DiffViewer';
import { PatchApproval } from '../components/PatchApproval';

// Error formatting helper to prevent [object Object] display
function formatError(error: any): string {
  if (!error) return 'An unknown error occurred';
  
  // If it's already a string, return it
  if (typeof error === 'string') {
    // Check for common error patterns and make them user-friendly
    if (error.includes('Failed to fetch')) return 'Network error: Could not connect to the server';
    if (error.includes('404')) return 'Resource not found';
    if (error.includes('500')) return 'Server error: Please try again later';
    return error;
  }
  
  // If it's an Error object
  if (error instanceof Error) {
    return error.message;
  }
  
  // If it's an object with a message or detail property
  if (typeof error === 'object') {
    if (error.message) return error.message;
    if (error.detail) return error.detail;
    if (error.error) return error.error;
    
    // Handle validation errors (arrays)
    if (Array.isArray(error)) {
      return error.map(e => e.msg || e.message || 'Validation error').join(', ');
    }
    
    // Handle FastAPI-style validation errors
    if (error.errors || Array.isArray(error.errors)) {
      return error.errors.map((e: any) => e.msg || e.message || 'Validation error').join(', ');
    }
  }
  
  // Fallback - convert to string safely
  return String(error);
}

export default function ChatPage() {
  const [project, setProject] = useState<{ id: string; name: string } | null>(null);
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<{role: string; content: string}[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [agentSteps, setAgentSteps] = useState<any[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [projectStats, setProjectStats] = useState<Record<string, number> | null>(null);
  const [showAgentWorkflow, setShowAgentWorkflow] = useState(true);
  
  // Settings state
  const [settings, setSettingsState] = useState<{ provider: string; model: string; api_key_masked: string } | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [newProvider, setNewProvider] = useState('groq');
  const [newApiKey, setNewApiKey] = useState('');
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  
  // Agent mode selection - persists per session
  const [agentMode, setAgentMode] = useState<string>('auto');
  
  // Ingestion state
  const [showIngestion, setShowIngestion] = useState(false);
  // Selected files/sources that persist even when modal closes
  const [selectedFiles, setSelectedFiles] = useState<{path: string; type: string; status: string}[]>([]);
  const [ingestionPath, setIngestionPath] = useState('');
  const [ingestionStatus, setIngestionStatus] = useState<string>('idle');
  const [ingestionError, setIngestionError] = useState<string | null>(null);
  const [filesProcessed, setFilesProcessed] = useState<number>(0);
  const [chunksCreated, setChunksCreated] = useState<number>(0);
  
  // Code modification state (patch flow)
  const [pendingPatch, setPendingPatch] = useState<{
    patchContent: string;
    originalContent: string;
    filePath: string;
  } | null>(null);
  
  // RAG sources state
  const [ragSources, setRagSources] = useState<{type: string; source: string}[]>([]);
  
  // Dark mode state
  const [darkMode, setDarkMode] = useState<boolean>(true);
  
  // Abort controller for canceling requests
  const [abortController, setAbortController] = useState<AbortController | null>(null);
  // Load projects on mount
  useEffect(() => {
    // Load dark mode from localStorage
    const savedMode = localStorage.getItem('darkMode');
    if (savedMode !== null) {
      setDarkMode(savedMode === 'true');
    }
    
    getProjects().then(({ data, error }) => {
      if (error) {
        console.error('Failed to load projects:', error);
        return;
      }
      if (data?.projects) {
        setProjects(data.projects);
        if (data.projects.length > 0) {
          setProject(data.projects[0]);
          loadStats(data.projects[0].id);
        }
      }
    });
    // Load current settings
    getSettings().then(({ data, error }) => {
      if (error) {
        console.error('Failed to load settings:', error);
        return;
      }
      if (data && !error) {
        setSettingsState({ provider: data.provider, model: data.model, api_key_masked: data.api_key_masked });
      }
    });
  }, []);
  
  // Save dark mode to localStorage when it changes
  useEffect(() => {
    localStorage.setItem('darkMode', darkMode.toString());
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  const loadStats = async (projectId: string) => {
    const { data, error } = await getKnowledgeStats(projectId);
    if (error) {
      console.error('Failed to load stats:', error);
      return;
    }
    setProjectStats(data?.vectors || null);
  };

  const handleSaveSettings = async () => {
    setSavingSettings(true);
    setSettingsError(null);
    const { data, error } = await setSettings({ 
      provider: newProvider,
      api_key: newApiKey || undefined 
    });
    setSavingSettings(false);
    
    if (data && !error) {
      setSettingsState({ 
        provider: data.provider, 
        model: data.model, 
        api_key_masked: data.api_key_masked 
      });
      setNewApiKey('');
      setShowSettings(false);
    } else {
      setSettingsError(error || 'Failed to update settings');
    }
  };

  const handleStartIngestion = async () => {
    // Get paths from selected files
    const rawPaths = selectedFiles.map(f => f.path);
    
    if (rawPaths.length === 0) {
      setIngestionError('Please select at least one file or path');
      return;
    }
    
    setIngestionStatus('running');
    setIngestionError(null);
    setFilesProcessed(0);
    setChunksCreated(0);
    
    try {
      const { data, error } = await ingestProject(project!.id, rawPaths);
      if (error) {
        setIngestionStatus('error');
        setIngestionError(formatError(error));
        return;
      }
      
      // Poll for progress
      const pollInterval = setInterval(async () => {
        const { data: statusData, error: statusError } = await getIngestionStatus(project!.id);
        if (statusError) {
          clearInterval(pollInterval);
          setIngestionStatus('error');
          setIngestionError(formatError(statusError));
          return;
        }
        
        if (statusData && statusData.ingestion_status === 'done') {
          clearInterval(pollInterval);
          setIngestionStatus('done');
          // Refresh stats
          loadStats(project!.id);
        } else if (statusData && statusData.ingestion_status === 'failed') {
          clearInterval(pollInterval);
          setIngestionStatus('error');
          setIngestionError('Repository ingestion failed');
        }
      }, 2000);
      
      // Also load stats after delay
      setTimeout(() => loadStats(project!.id), 1000);
      
    } catch (e) {
      setIngestionStatus('error');
      setIngestionError('Failed to start ingestion: ' + formatError(e));
    }
  };

  // Session state for multi-turn conversation persistence
  const [session_id, setSessionId] = useState<string | undefined>(undefined);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    // Create a new AbortController for this request
    const controller = new AbortController();
    setAbortController(controller);

    const userMsg = input;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setIsStreaming(true);
    setAgentSteps([]);
    setPendingPatch(null);
    setRagSources([]);
    setIngestionError(null);

    // Build request body - omit session_id on first message, include it on subsequent
    const requestBody: { project_id?: string; session_id?: string; message: string; agent_mode?: string } = {
      message: userMsg,
      agent_mode: agentMode,
    };
    if (project) {
      requestBody.project_id = project.id;
    }
    if (session_id) {
      requestBody.session_id = session_id;
    }

    try {
      const { data, error } = await createChatMessage(requestBody as any);
      setAbortController(null);

      setIsStreaming(false);

      if (error) {
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${formatError(error)}` }]);
      } else if (data) {
        // Capture the real session_id from first response for subsequent messages
        if (data.session_id && !session_id) {
          setSessionId(data.session_id);
        }
        
        // Add the assistant's response
        if (data.response) {
          setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
        }
        
        // Capture agent steps
        if (data.agent_steps && Array.isArray(data.agent_steps)) {
          setAgentSteps(data.agent_steps);
          
          // Extract RAG sources from knowledge_agent steps
          const knowledgeSteps = data.agent_steps.filter(s => s.agent === 'knowledge_agent');
          if (knowledgeSteps.length > 0) {
            const lastStep = knowledgeSteps[knowledgeSteps.length - 1];
            const sources = [];
            if (lastStep.output_summary) {
              const codeMatch = lastStep.output_summary.match(/code=(\d+) chunks/);
              const docMatch = lastStep.output_summary.match(/docs=(\d+) chunks/);
              if (codeMatch && parseInt(codeMatch[1]) > 0) {
                sources.push({ type: 'code', source: `${codeMatch[1]} code chunks` });
              }
              if (docMatch && parseInt(docMatch[1]) > 0) {
                sources.push({ type: 'docs', source: `${docMatch[1]} doc chunks` });
              }
            }
            setRagSources(sources);
          }
        }
        
        // Capture code_modification if present (patch flow)
        if (data.code_modification) {
          setPendingPatch({
            patchContent: data.code_modification.diff || '',
            originalContent: data.code_modification.modified_content_preview || '',
            filePath: data.code_modification.target_file || '',
          });
        }
      }
    } catch (err: any) {
      setAbortController(null);
      setIsStreaming(false);
      
      // Check if this was an abort
      if (err?.name === 'AbortError' || err?.message?.includes('User cancelled')) {
        setMessages(prev => [...prev, { role: 'assistant', content: `Request cancelled by user` }]);
      } else {
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${formatError(err)}` }]);
      }
    }
  };

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = (e.target as HTMLFormElement).project_name.value;
    const desc = (e.target as HTMLFormElement).project_desc?.value as string || '';
    
    const { data, error } = await createProject(name, desc);
    
    if (data?.id) {
      setProjects(prev => [...prev, { id: data.id, name }]);
      setProject({ id: data.id, name });
      // Auto-close modal on success
      (document.getElementById('create-project-modal') as HTMLDialogElement)?.close();
      (e.target as HTMLFormElement).reset();
    } else {
      alert(error || 'Failed to create project');
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !project) return;
    
    // Ingestion would be triggered here via API call
    alert('File upload handled - would trigger ingestion');
  };

  // Handle abort/cancel current request
  const handleAbort = () => {
    if (abortController) {
      abortController.abort('User cancelled');
      setAbortController(null);
      setIsStreaming(false);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, agentSteps]);
  return (
    <div className={`h-screen flex flex-col ${darkMode ? 'bg-[#0D1117] text-gray-100' : 'bg-[#F5F7FA] text-gray-900'}`}>
      {/* TOP HEADER - Fixed at top, doesn't scroll */}
      <div className={`h-14 flex-shrink-0 border-b flex items-center justify-between px-6 ${darkMode ? 'border-[#2E3645] bg-[#161B22]' : 'border-[#D1D9E6] bg-white'}`}>
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-[#4F8CFF] rounded-lg flex items-center justify-center shadow-lg shadow-[#4F8CFF]/20">
            <span className="text-white font-bold text-lg">AI</span>
          </div>
          <h1 className="text-lg font-bold tracking-tight text-blue-400 dark:text-blue-400">AI Orchestrator</h1>
        </div>
        <div className="flex items-center gap-2">
          {/* Settings button - single entry point */}
          <button
            onClick={() => setShowSettings(true)}
            className={`p-2 rounded-lg transition-all ${
              darkMode 
                ? 'hover:bg-[#2E3645] text-[#9CA3AF]' 
                : 'hover:bg-[#E5E7EB] text-[#6B7280]'
            }`}
            title="Settings"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
          {/* Theme toggle */}
          <button
            onClick={() => setDarkMode(!darkMode)}
            className={`p-2 rounded-lg transition-all ${
              darkMode 
                ? 'hover:bg-[#2E3645] text-[#9CA3AF] hover:text-yellow-400' 
                : 'hover:bg-[#E5E7EB] text-[#6B7280] hover:text-[#2563EB]'
            }`}
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {darkMode ? (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>
        </div>
      </div>
      
      {/* THREE-PANEL LAYOUT */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* LEFT PANEL - Projects, Agent Mode, Workspace */}
        <div className={`w-72 border-r flex flex-col overflow-y-auto ${darkMode ? 'border-[#2E3645] bg-[#161B22]' : 'border-[#D1D9E6] bg-white'}`}>
          {/* Projects section */}
          <div className="px-4 py-4 space-y-1">
            <h2 className={`text-xs font-bold uppercase tracking-wider mb-2 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>Projects</h2>
            <div className="space-y-1">
              {projects.map(p => (
                <button
                  key={p.id}
                  onClick={() => { setProject(p); loadStats(p.id); }}
                  className={`w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    project?.id === p.id
                      ? (darkMode 
                          ? 'bg-[#1E3A8A]/30 border border-[#4F8CFF]/30 text-[#60A5FA]' 
                          : 'bg-[#DBEAFE]/50 border border-[#93C5FD] text-[#1E40AF]')
                      : (darkMode 
                          ? 'hover:bg-[#1E293B] text-[#9CA3AF]' 
                          : 'hover:bg-[#F3F4F6] text-[#4B5563]')
                  }`}
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>
          
          {/* Agent Mode section */}
          <div className="px-4 py-3 border-t border-[#2E3645]">
            <h2 className={`text-xs font-bold uppercase tracking-wider mb-2 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>Agent Mode</h2>
            <select
              value={agentMode}
              onChange={(e) => setAgentMode(e.target.value)}
              className={`w-full px-3 py-2.5 rounded-lg text-sm transition-colors ${
                darkMode 
                  ? 'bg-[#1E293B] border-[#374151] text-[#E5E7EB] hover:bg-[#2E3645]' 
                  : 'bg-[#F3F4F6] border-[#D1D9E6] text-[#111827] hover:bg-[#E5E7EB]'
              }`}
            >
              <option value="auto">Auto (LangGraph routing)</option>
              <option value="router_agent">Router Agent</option>
              <option value="planner_agent">Planner Agent</option>
              <option value="knowledge_agent">Knowledge Agent</option>
              <option value="code_intelligence_agent">Code Intelligence Agent</option>
              <option value="coding_agent">Coding Agent</option>
              <option value="testing_agent">Testing Agent</option>
              <option value="validation_agent">Validation Agent</option>
              <option value="response_generator">Response Generator</option>
            </select>
            <p className={`text-xs mt-2 ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>
              {agentMode === 'auto' 
                ? 'LangGraph automatically selects agents based on your request intent'
                : 'Run a specific agent directly without routing'}
            </p>
          </div>
          
          {/* Workspace info */}
          {project && (
            <div className="px-4 py-3 border-t border-[#2E3645]">
              <h2 className={`text-xs font-bold uppercase tracking-wider mb-2 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>Workspace</h2>
              <div className={`p-3 rounded-lg text-sm ${
                darkMode ? 'bg-[#0F172A] border border-[#1E293B]' : 'bg-[#F3F4F6] border border-[#D1D9E6]'
              }`}>
                <div className={`text-xs ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>Project</div>
                <div className={`font-medium mt-0.5 ${darkMode ? 'text-[#F3F4F6]' : 'text-[#111827]'}`}>{project.name}</div>
                <div className={`text-xs mt-1 ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>
                  {project.id.slice(0, 8)}...
                </div>
              </div>
            </div>
          )}

          {/* Active LLM Provider */}
          <div className="px-4 py-3 border-t border-[#2E3645] mt-auto">
            <h2 className={`text-xs font-bold uppercase tracking-wider mb-2 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>LLM Provider</h2>
            {settings ? (
              <div className={`p-3 rounded-lg text-sm ${
                darkMode ? 'bg-[#0F172A] border border-[#1E293B]' : 'bg-[#F3F4F6] border border-[#D1D9E6]'
              }`}>
                <div className={`flex items-center gap-2 text-xs ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  {settings.provider.charAt(0).toUpperCase() + settings.provider.slice(1)}
                </div>
                <div className={`text-xs mt-1 ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>
                  {settings.model}
                </div>
                <div className={`text-xs mt-1 ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>
                  API Key: {settings.api_key_masked || 'Not set'}
                </div>
              </div>
            ) : (
              <div className={`text-sm ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>
                Loading...
              </div>
            )}
          </div>
        </div>
        {/* CENTER PANEL - Main chat interface */}
        <div className={`flex-1 flex flex-col overflow-hidden ${darkMode ? 'bg-[#0F1117]' : 'bg-[#F8FAFC]'}`}>
          {/* Messages area */}
          <div className={`flex-1 overflow-y-auto p-6 space-y-6 ${darkMode ? 'scrollbar-thin scrollbar-thumb-[#2E3645] scrollbar-track-[#0F1117]' : 'scrollbar-thin scrollbar-thumb-[#D1D9E6] scrollbar-track-[#F8FAFC]'}`}>
            
            {/* Empty state */}
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full max-w-2xl mx-auto">
                {!project ? (
                  <div className="flex flex-col items-center">
                    <div className={`w-24 h-24 rounded-2xl flex items-center justify-center mb-4 ${
                      darkMode ? 'bg-[#1E293B]' : 'bg-[#E5E7EB]'
                    }`}>
                      <svg className="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                      </svg>
                    </div>
                    <button
                      onClick={() => (document.getElementById('create-project-modal') as HTMLDialogElement)?.showModal()}
                      className="px-8 py-3 bg-[#4F8CFF] hover:bg-[#3B82F6] text-white rounded-xl font-medium transition-all shadow-lg shadow-[#4F8CFF]/20"
                    >
                      + Create New Project
                    </button>
                    <p className={`mt-4 text-center max-w-md mx-auto ${
                      darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'
                    }`}>
                      Choose an existing project from the sidebar or create a new one to get started with AI code assistance.
                    </p>
                  </div>
                ) : (
                  <div className="text-center">
                    <div className={`w-24 h-24 rounded-2xl flex items-center justify-center mb-6 mx-auto ${
                      darkMode ? 'bg-[#1E293B]' : 'bg-[#E5E7EB]'
                    }`}>
                      <svg className="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                      </svg>
                    </div>
                    <h3 className={`text-2xl font-bold mb-3 ${darkMode ? 'text-[#F3F4F6]' : 'text-[#111827]'}`}>
                      Ready to Ask
                    </h3>
                    <p className={`mb-6 text-center max-w-lg mx-auto ${
                      darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'
                    }`}>
                      Ask me about your codebase or request code changes.
                      {projectStats && projectStats.total === 0 && (
                        <span className={`block mt-3 px-4 py-2 rounded-lg ${
                          darkMode ? 'bg-[#713F12]/20 text-[#FBBF24]' : 'bg-[#FEF3C7] text-[#92400E]'
                        } text-sm`}>
                          📝 Repository not yet ingested. Click "Start Ingestion" in the sidebar to index your code.
                        </span>
                      )}
                    </p>
                    
                    {/* Suggested prompts */}
                    {projectStats && projectStats.total > 0 && (
                      <div className={`text-sm max-w-lg mx-auto p-4 rounded-xl ${
                        darkMode ? 'bg-[#1E293B] border border-[#374151]' : 'bg-white border border-[#E5E7EB] shadow-sm'
                      }`}>
                        <div className={`font-semibold mb-3 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>
                          Try asking:
                        </div>
                        <div className="space-y-2">
                          {[
                            "Explain the project architecture",
                            "How does authentication work?",
                            "Find potential bugs in the project",
                            "Explain the main API endpoints",
                            "Where is the database connection configured?"
                          ].map((prompt, i) => (
                            <button
                              key={i}
                              onClick={() => setInput(prompt)}
                              className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                                darkMode 
                                  ? 'hover:bg-[#374151] text-[#D1D5DB]' 
                                  : 'hover:bg-[#F3F4F6] text-[#374151]'
                              }`}
                            >
                              {prompt}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
            
            {/* Messages */}
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-3xl px-5 py-4 rounded-2xl shadow-sm ${
                  msg.role === 'user'
                    ? 'bg-[#4F8CFF] text-white rounded-br-none'
                    : (darkMode 
                        ? 'bg-[#1E293B] text-[#E5E7EB] border border-[#374151] rounded-bl-none' 
                        : 'bg-white text-[#111827] border border-[#E5E7EB] rounded-bl-none')
                }`}>
                  <div className={`text-xs font-semibold mb-2 ${
                    msg.role === 'user' ? 'text-[#BFDBFE]/80' : (darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]')
                  }`}>
                    {msg.role === 'user' ? 'You' : 'AI'}
                  </div>
                  <pre className={`whitespace-pre-wrap text-sm font-medium leading-relaxed ${
                    msg.role === 'user' ? '' : (darkMode ? 'text-[#E5E7EB]' : 'text-[#111827]')
                  }`}>
                    {msg.content}
                  </pre>
                </div>
              </div>
            ))}
            
            {/* Patch approval UI */}
            {pendingPatch && (
              <div className="flex justify-start">
                <div className="max-w-3xl">
                  <PatchApproval
                    projectId={project!.id}
                    sessionId={session_id!}
                    patchContent={pendingPatch.patchContent}
                    originalContent={pendingPatch.originalContent}
                    filePath={pendingPatch.filePath}
                    onApproved={() => {
                      setPendingPatch(null);
                      setRagSources([]);
                      setMessages(prev => [...prev, { role: 'assistant', content: `[OK] Patch approved and applied to ${pendingPatch.filePath}` }]);
                    }}
                    onRejected={() => {
                      setPendingPatch(null);
                      setRagSources([]);
                      setMessages(prev => [...prev, { role: 'assistant', content: `[FAIL] Patch rejected` }]);
                    }}
                  />
                </div>
              </div>
            )}
            
            {/* RAG sources attribution */}
            {ragSources.length > 0 && (
              <div className="flex justify-start">
                <div className={`max-w-3xl p-4 rounded-2xl ${
                  darkMode ? 'bg-[#1E293B]/50 border border-[#374151]' : 'bg-[#F3F4F6] border border-[#E5E7EB]'
                }`}>
                  <div className={`text-xs font-semibold mb-2 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>
                    Sources:
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {ragSources.map((source, i) => (
                      <span key={i} className={`px-2.5 py-1 rounded-md text-xs font-medium ${
                        darkMode 
                          ? 'bg-[#1E3A8A]/30 border border-[#3B82F6]/30 text-[#60A5FA]' 
                          : 'bg-[#DBEAFE]/50 border border-[#93C5FD] text-[#1E40AF]'
                      }`}>
                        {source.source}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}
            
            {isStreaming && (
              <div className="flex justify-start">
                <div className={`px-4 py-3 rounded-2xl animate-pulse ${
                  darkMode ? 'bg-[#1E293B] border border-[#374151]' : 'bg-white border border-[#E5E7EB]'
                }`}>
                  <span className="flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    AI is thinking...
                  </span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          {/* Agent steps visualization */}
          {agentSteps.length > 0 && (
            <div className={`border-t px-6 py-4 ${darkMode ? 'border-[#2E3645] bg-[#0F1117]' : 'border-[#D1D9E6] bg-[#F8FAFC]'}`}>
              <div className="flex items-start gap-2 mb-3 cursor-pointer" onClick={() => setShowAgentWorkflow(!showAgentWorkflow)}>
                <svg className={`w-4 h-4 ${darkMode ? 'text-[#4F8CFF]' : 'text-[#2563EB]'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                <div className="flex-1">
                  <h3 className={`text-sm font-semibold ${darkMode ? 'text-[#9CA3AF]' : 'text-[#374151]'}`}>
                    Agent workflow
                  </h3>
                </div>
                <svg className={`w-4 h-4 ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'} transition-transform ${showAgentWorkflow ? '' : 'rotate-180'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
              {showAgentWorkflow && (
                <div className="space-y-2 max-h-64 overflow-y-auto pr-2">
                  {agentSteps.map((step, i) => (
                    <div key={i} className={`text-sm px-3 py-2 rounded-lg ${
                      darkMode ? 'bg-[#1E293B] border border-[#374151]' : 'bg-[#F3F4F6] border border-[#E5E7EB]'
                    }`}>
                      <div className={`flex items-center gap-2 mb-1`}>
                        <span className={`px-2 py-0.5 rounded-md text-xs font-medium ${
                          darkMode ? 'bg-[#3B82F6]/20 text-[#60A5FA]' : 'bg-[#DBEAFE] text-[#1E40AF]'
                        }`}>
                          {step.agent}
                        </span>
                        <span className={`text-xs ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>
                          Step {step.step}
                        </span>
                      </div>
                      {step.input_summary && (
                        <div className={`text-xs mb-1 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#4B5563]'}`}>
                          Input: {step.input_summary}
                        </div>
                      )}
                      {step.output_summary && (
                        <div className={`text-xs ${darkMode ? 'text-[#E5E7EB]' : 'text-[#111827]'}`}>
                          Output: {step.output_summary}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Chat input - Fixed at bottom */}
          <div className={`p-4 border-t ${darkMode ? 'border-[#2E3645] bg-[#0F1117]' : 'border-[#E5E7EB] bg-[#F8FAFC]'}`}>
            <form onSubmit={handleSendMessage} className="flex gap-3 max-w-4xl mx-auto">
              <div className="flex-1 relative">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ask about your codebase..."
                  disabled={isStreaming}
                  className={`w-full px-4 py-3 pr-12 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#4F8CFF] transition-all ${
                    darkMode 
                      ? 'bg-[#1E293B] border-[#374151] text-[#E5E7EB] placeholder-[#6B7280]' 
                      : 'bg-white border-[#E5E7EB] text-[#111827] placeholder-[#9CA3AF]'
                  } ${isStreaming ? 'opacity-60 cursor-not-allowed' : ''}`}
                />
              </div>
              <button
                type="button"
                onClick={handleAbort}
                disabled={!abortController}
                className={`px-4 py-3 rounded-xl font-medium transition-all ${
                  !abortController
                    ? (darkMode ? 'opacity-0' : 'opacity-0') // Hidden when no abort
                    : (darkMode 
                        ? 'bg-[#EF4444] hover:bg-[#DC2626] text-white' 
                        : 'bg-[#EF4444] hover:bg-[#DC2626] text-white')
                }`}
                title="Cancel current request"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
              <button
                type="submit"
                disabled={!input.trim() || isStreaming}
                className={`px-6 py-3 rounded-xl font-medium transition-all shadow-lg ${
                  !input.trim() || isStreaming
                    ? (darkMode ? 'bg-[#374151] text-[#6B7280] cursor-not-allowed' : 'bg-[#E5E7EB] text-[#9CA3AF] cursor-not-allowed')
                    : (darkMode 
                        ? 'bg-[#4F8CFF] hover:bg-[#3B82F6] text-white shadow-[#4F8CFF]/20' 
                        : 'bg-[#2563EB] hover:bg-[#1D4ED8] text-white shadow-[#2563EB]/20')
                }`}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>
            </form>
            <div className={`text-center text-xs mt-2 ${darkMode ? 'text-[#6B7280]' : 'text-[#9CA3AF]'}`}>
              Press Enter to send
            </div>
          </div>
        </div>
        {/* RIGHT PANEL - Codebase/Project Context */}
        <div className={`w-80 border-l flex flex-col overflow-hidden ${darkMode ? 'border-[#2E3645] bg-[#161B22]' : 'border-[#D1D9E6] bg-white'}`}>
          <div className={`p-5 border-b ${darkMode ? 'border-[#2E3645] bg-[#0F172A]' : 'border-[#E5E7EB] bg-[#F8FAFC]'}`}>
            <h2 className={`text-sm font-bold uppercase tracking-wider ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>
              Codebase
            </h2>
          </div>
          
          <div className="flex-1 overflow-y-auto p-5 space-y-6">
            {/* Project info */}
            <div>
              <h3 className={`text-xs font-bold uppercase tracking-wider mb-3 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>
                Current Project
              </h3>
              <div className={`p-4 rounded-xl ${
                darkMode ? 'bg-[#0F172A] border border-[#1E293B]' : 'bg-white border border-[#E5E7EB]'
              }`}>
                <div className={`text-sm font-medium ${darkMode ? 'text-[#F3F4F6]' : 'text-[#111827]'}`}>
                  {project?.name || 'No project selected'}
                </div>
                <div className={`text-xs mt-2 ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>
                  ID: {project?.id ? `${project.id.slice(0, 8)}...` : 'N/A'}
                </div>
              </div>
            </div>

            {/* Repository status */}
            {project && (
              <div>
                <h3 className={`text-xs font-bold uppercase tracking-wider mb-3 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>
                  Repository Status
                </h3>
                <div className={`p-4 rounded-xl ${
                  darkMode ? 'bg-[#0F172A] border border-[#1E293B]' : 'bg-white border border-[#E5E7EB]'
                }`}>
                  <div className="flex items-center gap-2 mb-3">
                    <div className={`w-2.5 h-2.5 rounded-full ${
                      ingestionStatus === 'running' 
                        ? 'bg-[#4F8CFF] animate-pulse' 
                        : (ingestionStatus === 'done' 
                            ? 'bg-[#10B981]' 
                            : (ingestionStatus === 'error' 
                                ? 'bg-red-500' 
                                : 'bg-[#6B7280]'))
                    }`}></div>
                    <span className={`text-sm font-medium capitalize ${
                      darkMode 
                        ? (ingestionStatus === 'error' ? 'text-red-400' : 'text-[#9CA3AF]') 
                        : (ingestionStatus === 'error' ? 'text-red-600' : 'text-[#6B7280]')
                    }`}>
                      {ingestionStatus}
                    </span>
                  </div>
                  
                  {ingestionStatus === 'error' && ingestionError && (
                    <div className={`mt-2 text-xs p-2 rounded-lg bg-red-500/10 border border-red-500/20`}>
                      <span className="text-red-400">⚠️</span> {ingestionError}
                    </div>
                  )}
                  
                  {ingestionStatus === 'idle' && !projectStats?.total && (
                    <div className={`mt-3 p-3 rounded-lg text-xs ${
                      darkMode ? 'bg-[#1E293B]' : 'bg-[#F3F4F6]'
                    }`}>
                      Repository not yet ingested. Click "Start Repository Ingestion" to index your code.
                    </div>
                  )}
                  
                  {ingestionStatus === 'done' && projectStats && (
                    <div className="mt-4 grid grid-cols-2 gap-3">
                      <div className={`text-center p-2 rounded-lg ${
                        darkMode ? 'bg-[#1E293B]' : 'bg-[#F3F4F6]'
                      }`}>
                        <div className={`text-xs ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>Files</div>
                        <div className={`text-lg font-semibold ${darkMode ? 'text-[#4F8CFF]' : 'text-[#2563EB]'}`}>
                          {projectStats.files || 0}
                        </div>
                      </div>
                      <div className={`text-center p-2 rounded-lg ${
                        darkMode ? 'bg-[#1E293B]' : 'bg-[#F3F4F6]'
                      }`}>
                        <div className={`text-xs ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>Chunks</div>
                        <div className={`text-lg font-semibold ${darkMode ? 'text-[#4F8CFF]' : 'text-[#2563EB]'}`}>
                          {projectStats.chunks || 0}
                        </div>
                      </div>
                      <div className={`text-center p-2 rounded-lg ${
                        darkMode ? 'bg-[#1E293B]' : 'bg-[#F3F4F6]'
                      }`}>
                        <div className={`text-xs ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>Vectors</div>
                        <div className={`text-lg font-semibold ${darkMode ? 'text-[#4F8CFF]' : 'text-[#2563EB]'}`}>
                          {projectStats.total || 0}
                        </div>
                      </div>
                      <div className={`text-center p-2 rounded-lg ${
                        darkMode ? 'bg-[#1E293B]' : 'bg-[#F3F4F6]'
                      }`}>
                        <div className={`text-xs ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>Embeddings</div>
                        <div className={`text-lg font-semibold ${darkMode ? 'text-[#4F8CFF]' : 'text-[#2563EB]'}`}>
                          {projectStats.embeddings || 0}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Quick actions */}
            {project && (
              <div className={`space-y-2 ${ingestionStatus === 'done' ? '' : 'pt-6'}`}>
                <h3 className={`text-xs font-bold uppercase tracking-wider mb-3 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>
                  Quick Actions
                </h3>
                
                {ingestionStatus === 'idle' || ingestionStatus === 'error' || ingestionStatus === 'done' ? (
                  <button
                    onClick={() => setShowIngestion(true)}
                    className={`w-full px-4 py-2.5 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2 ${
                      darkMode 
                        ? 'bg-[#4F8CFF] hover:bg-[#3B82F6] text-white shadow-[#4F8CFF]/20' 
                        : 'bg-[#2563EB] hover:bg-[#1D4ED8] text-white shadow-[#2563EB]/20'
                    }`}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                    </svg>
                    {ingestionStatus === 'done' ? 'Re-ingest Repository' : 'Start Repository Ingestion'}
                  </button>
                ) : ingestionStatus === 'running' && (
                  <div className={`w-full px-4 py-3 rounded-lg text-sm text-center ${
                    darkMode ? 'bg-[#1E293B]' : 'bg-[#F3F4F6]'
                  }`}>
                    Ingestion in progress...
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      {/* Settings Modal */}
      <dialog id="settings-modal" open={showSettings} className="bg-[#1F2937] rounded-xl p-6 max-w-md w-full shadow-2xl">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-bold text-[#F3F4F6]">Settings</h2>
          <button
            onClick={() => {
              setShowSettings(false);
              (document.getElementById('settings-modal') as HTMLDialogElement)?.close();
              setSettingsError(null);
            }}
            className="text-[#9CA3AF] hover:text-[#F3F4F6] transition-colors"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        
        {settingsError && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
            <p className="text-sm text-red-400">⚠️ {settingsError}</p>
          </div>
        )}
        
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1 text-[#E5E7EB]">LLM Provider</label>
            <select
              value={newProvider}
              onChange={(e) => setNewProvider(e.target.value)}
              className="w-full bg-[#374151] border border-[#4B5563] rounded-lg px-4 py-2.5 text-[#E5E7EB] focus:outline-none focus:ring-2 focus:ring-[#4F8CFF]"
            >
              <option value="openai">OpenAI</option>
              <option value="claude">Anthropic (Claude)</option>
              <option value="groq">Groq</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1 text-[#E5E7EB]">
              API Key <span className="text-[#6B7280] text-xs">(optional - uses current if empty)</span>
            </label>
            <input
              type="password"
              value={newApiKey}
              onChange={(e) => setNewApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full bg-[#374151] border border-[#4B5563] rounded-lg px-4 py-2.5 font-mono text-sm text-[#E5E7EB] focus:outline-none focus:ring-2 focus:ring-[#4F8CFF]"
            />
          </div>
          {settings && (
            <div className={`text-sm p-3 rounded-lg ${
              darkMode ? 'bg-[#374151]' : 'bg-[#F3F4F6]'
            }`}>
              <span className="text-[#9CA3AF]">Currently active: </span>
              <strong className="text-[#4F8CFF]">{settings.provider}</strong> (
              {settings.model})
            </div>
          )}
        </div>
        
        <div className="flex gap-3 justify-end mt-6">
          <button
            type="button"
            onClick={() => {
              setShowSettings(false);
              (document.getElementById('settings-modal') as HTMLDialogElement)?.close();
              setSettingsError(null);
            }}
            className="px-4 py-2.5 bg-[#374151] hover:bg-[#4B5563] rounded-lg text-[#E5E7EB] font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSaveSettings}
            disabled={savingSettings}
            className="px-4 py-2.5 bg-[#4F8CFF] hover:bg-[#3B82F6] rounded-lg text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-[#4F8CFF]/20"
          >
            {savingSettings ? (
              <span className="flex items-center gap-2">
                <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Saving...
              </span>
            ) : 'Save Settings'}
          </button>
        </div>
      </dialog>

      {/* Ingestion Modal */}
      <dialog id="ingestion-modal" open={showIngestion} className="backdrop:bg-black/50 bg-transparent p-4 m-auto">
        <div className="bg-[#1F2937] rounded-xl p-6 max-w-md w-full shadow-2xl max-h-[90vh] overflow-y-auto">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-bold text-[#F3F4F6]">Repository Ingestion</h2>
          <button
            onClick={() => {
  // Closing modal should NOT reset ingestion state if running
  // Only reset if ingestion is idle or done
  setShowIngestion(false);
  if (ingestionStatus !== 'running') {
    setIngestionPath('');
    setIngestionError(null);
  }
}}
            className="text-[#9CA3AF] hover:text-[#F3F4F6] transition-colors"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        
        <div className="space-y-4">
          {/* Selected files list */}
          {selectedFiles.length > 0 && (
            <div>
              <h3 className={`text-sm font-medium mb-2 ${darkMode ? 'text-[#9CA3AF]' : 'text-[#6B7280]'}`}>
                Selected Sources ({selectedFiles.length})
              </h3>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {selectedFiles.map((file, idx) => (
                  <div key={idx} className={`flex items-center justify-between px-3 py-2 rounded-lg text-sm ${
                    darkMode ? 'bg-[#1E293B] border border-[#374151]' : 'bg-[#F3F4F6] border border-[#E5E7EB]'
                  }`}>
                    <span className={`font-mono truncate max-w-[200px] ${darkMode ? 'text-[#E5E7EB]' : 'text-[#111827]'}`}>
                      {file.path}
                    </span>
                    <button
                      onClick={() => setSelectedFiles(prev => prev.filter((_, i) => i !== idx))}
                      className="text-red-400 hover:text-red-500 transition-colors"
                      title="Remove file"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Add sources controls */}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                darkMode 
                  ? 'bg-[#374151] hover:bg-[#4B5563] text-[#E5E7EB]' 
                  : 'bg-[#E5E7EB] hover:bg-[#D1D9E6] text-[#111827]'
              }`}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
              </svg>
              Upload Files
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files || []);
                if (files.length > 0) {
                  setSelectedFiles(prev => [...prev, ...files.map(f => ({ path: f.name, type: 'file', status: 'pending' }))]);
                  // Reset the input so same file can be selected again
                  e.target.value = '';
                }
              }}
            />
            <button
              type="button"
              onClick={() => {
                // Add repository path from textarea
                const paths = ingestionPath.split(/[\n,]/).map(p => p.trim()).filter(p => p.length > 0);
                if (paths.length > 0) {
                  setSelectedFiles(prev => [...prev, ...paths.map(p => ({ path: p, type: 'path', status: 'pending' }))]);
                  setIngestionPath('');
                }
              }}
              className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                darkMode 
                  ? 'bg-[#374151] hover:bg-[#4B5563] text-[#E5E7EB]' 
                  : 'bg-[#E5E7EB] hover:bg-[#D1D9E6] text-[#111827]'
              }`}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4-4m0 0L8 8m4-4v8" />
              </svg>
              Add Path
            </button>
          </div>
          
          <div className="flex justify-between items-center mt-2">
            <button
              type="button"
              onClick={() => setSelectedFiles([])}
              className="text-sm text-red-400 hover:text-red-500"
            >
              Clear All
            </button>
          </div>
          
          <p className={`text-sm ${darkMode ? 'text-[#6B7280]' : 'text-[#6B7280]'}`}>
            {selectedFiles.length === 0 
              ? 'No sources selected. Add files or repository paths above.'
              : `${selectedFiles.length} source(s) ready for ingestion.`}
          </p>
          
          <div className="space-y-2">
            <label className="block text-sm font-medium mb-1 text-[#E5E7EB]">Repository Path (fallback)</label>
            <textarea
              value={ingestionPath}
              onChange={(e) => setIngestionPath(e.target.value)}
              placeholder="e:/DevEps/ai-engineering-orchestrator/backend"
              className="w-full bg-[#374151] border border-[#4B5563] rounded-lg px-4 py-2.5 font-mono text-sm text-[#E5E7EB] focus:outline-none focus:ring-2 focus:ring-[#4F8CFF] min-h-[80px]"
            />
          </div>
          
          {ingestionError && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
              <p className="text-sm text-red-400">⚠️ {ingestionError}</p>
            </div>
          )}
          
          {ingestionStatus === 'running' && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm text-[#4F8CFF]">
                <div className="w-2 h-2 bg-[#4F8CFF] rounded-full animate-pulse"></div>
                <span>Ingestion in progress...</span>
              </div>
              <div className={`h-2 rounded-full overflow-hidden ${
                darkMode ? 'bg-[#374151]' : 'bg-[#E5E7EB]'
              }`}>
                <div className="h-full bg-[#4F8CFF] animate-[pulse_1.5s_ease-in-out_infinite]" style={{width: '65%'}}></div>
              </div>
            </div>
          )}
          
          {ingestionStatus === 'done' && (
            <div className="flex items-center gap-2 text-sm text-[#10B981]">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              Ingestion complete!
            </div>
          )}
        </div>
        
        <div className="flex gap-3 justify-end mt-6">
          <button
            type="button"
            onClick={() => {
              setShowIngestion(false);
              // Only reset state if ingestion isn't running
              if (ingestionStatus !== 'running') {
                setIngestionStatus('idle');
                setIngestionPath('');
                setIngestionError(null);
                setSelectedFiles([]);
              }
              (document.getElementById('ingestion-modal') as HTMLDialogElement)?.close();
            }}
            className="px-4 py-2.5 bg-[#374151] hover:bg-[#4B5563] rounded-lg text-[#E5E7EB] font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleStartIngestion}
            disabled={ingestionStatus === 'running' || selectedFiles.length === 0}
            className="px-4 py-2.5 bg-[#4F8CFF] hover:bg-[#3B82F6] rounded-lg text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-[#4F8CFF]/20"
          >
            {ingestionStatus === 'running' ? 'Ingesting...' : 'Start Ingestion'}
          </button>
        </div>
        </div>
      </dialog>

      {/* Create Project Modal */}
      <dialog id="create-project-modal" className="backdrop:bg-black/50 bg-transparent p-4 m-auto">
  <div className="bg-[#1F2937] rounded-xl p-6 max-w-md w-full shadow-2xl max-h-[90vh] overflow-y-auto">
          <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-bold text-[#F3F4F6]">Create New Project</h2>
          <button
            onClick={() => (document.getElementById('create-project-modal') as HTMLDialogElement)?.close()}
            className="text-[#9CA3AF] hover:text-[#F3F4F6] transition-colors"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        
        <form onSubmit={handleCreateProject} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1 text-[#E5E7EB]">Project Name</label>
            <input 
              name="project_name" 
              required 
              className="w-full bg-[#374151] border border-[#4B5563] rounded-lg px-4 py-2.5 text-[#E5E7EB] focus:outline-none focus:ring-2 focus:ring-[#4F8CFF]" 
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1 text-[#E5E7EB]">Description <span className="text-[#6B7280]">(optional)</span></label>
            <input 
              name="project_desc" 
              className="w-full bg-[#374151] border border-[#4B5563] rounded-lg px-4 py-2.5 text-[#E5E7EB] focus:outline-none focus:ring-2 focus:ring-[#4F8CFF]" 
            />
          </div>
          <div className="flex gap-3 justify-end mt-6">
            <button 
              type="button" 
              onClick={() => (document.getElementById('create-project-modal') as HTMLDialogElement)?.close()} 
              className="px-4 py-2.5 bg-[#374151] hover:bg-[#4B5563] rounded-lg text-[#E5E7EB] font-medium transition-colors"
            >
              Cancel
            </button>
            <button 
              type="submit" 
              className="px-4 py-2.5 bg-[#4F8CFF] hover:bg-[#3B82F6] rounded-lg text-white font-medium transition-colors shadow-lg shadow-[#4F8CFF]/20"
            >
              Create Project
            </button>
          </div>
        </form>
        </div>
      </dialog>
    </div>
  );
}
