// Thin wrapper around the backend REST API. All paths are proxied to :8001 by Vite.

async function jsonFetch(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`)
  }
  return data
}

export const api = {
  getConfig: () => jsonFetch('/api/config'),

  getSettings: () => jsonFetch('/api/settings'),

  saveSettings: (body) =>
    jsonFetch('/api/settings', { method: 'POST', body: JSON.stringify(body) }),

  getLogs: (limit = 50) => jsonFetch(`/api/logs?limit=${limit}`),

  intentFromText: (body) =>
    jsonFetch('/api/intent/text', { method: 'POST', body: JSON.stringify(body) }),

  intentFromAudio: async ({ blob, parser, stt, llmProvider, llmModel, voiceOutput }) => {
    const form = new FormData()
    form.append('file', blob, 'clip.webm')
    form.append('parser', parser)
    form.append('stt', stt)
    if (voiceOutput) form.append('voice_output', voiceOutput)
    if (llmProvider) form.append('llm_provider', llmProvider)
    if (llmModel) form.append('llm_model', llmModel)
    const res = await fetch('/api/intent/audio', { method: 'POST', body: form })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `Transcription failed (${res.status})`)
    return data
  },

  speak: (text) =>
    jsonFetch('/api/speak', { method: 'POST', body: JSON.stringify({ text }) }),

  suggest: (body) =>
    jsonFetch('/api/suggestions', { method: 'POST', body: JSON.stringify(body) }),

  getVolume: () => jsonFetch('/api/volume'),

  setVolume: (level) =>
    jsonFetch('/api/volume', { method: 'POST', body: JSON.stringify({ level }) }),

  action: (body) =>
    jsonFetch('/api/action', { method: 'POST', body: JSON.stringify(body) }),

  execute: (body) =>
    jsonFetch('/api/execute', { method: 'POST', body: JSON.stringify(body) }),
}
