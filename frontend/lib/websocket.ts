// WebSocket client for streaming agent steps

let socket: WebSocket | null = null;
let messageHandlers: Map<string, (data: any) => void> = new Map();
let lastMessageId = 0;

export function connectWebSocket(projectId: string, sessionId: string, apiKey: string) {
  const url = `ws://localhost:8000/ws/${projectId}/${sessionId}`;
  
  socket = new WebSocket(url);
  
  socket.onopen = () => {
    console.log('[WS] Connected');
  };
  
  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      const handler = messageHandlers.get(data.type);
      if (handler) {
        handler(data);
      }
    } catch (e) {
      console.error('[WS] Parse error:', e);
    }
  };
  
  socket.onclose = () => {
    console.log('[WS] Disconnected');
    socket = null;
  };
  
  socket.onerror = (error) => {
    console.error('[WS] Error:', error);
  };
  
  return () => {
    if (socket) {
      socket.close();
    }
  };
}

export function onStep(callback: (data: any) => void) {
  const id = `step_${++lastMessageId}`;
  messageHandlers.set('agent_step', callback);
  return () => messageHandlers.delete('agent_step');
}

export function onFinalResponse(callback: (data: any) => void) {
  const id = `response_${++lastMessageId}`;
  messageHandlers.set('final_response', callback);
  return () => messageHandlers.delete('final_response');
}

export function disconnectWebSocket() {
  if (socket) {
    socket.close();
    socket = null;
  }
}