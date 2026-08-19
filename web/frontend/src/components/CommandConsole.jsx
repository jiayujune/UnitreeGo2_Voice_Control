import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const SEED_SUGGESTIONS = ['go two stand up', 'move forward a little', 'sit down', 'stop', 'how are you, Go2?', 'find the apple']

// Text command box + browser microphone recording. Both produce a result object
// ({transcript, intent, plan}) handed back to the parent via onResult.
export default function CommandConsole({ config, parser, setParser, llmProvider, stt, setStt, voiceOutput, setVoiceOutput, context, onResult }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [recording, setRecording] = useState(false)

  const [suggestions, setSuggestions] = useState(SEED_SUGGESTIONS)
  const [loadingSuggestions, setLoadingSuggestions] = useState(false)

  const mediaRef = useRef(null)
  const chunksRef = useRef([])

  // Fetch context-aware "what to say next" chips. `avoid` lets refresh return a
  // fresh batch instead of repeating the current ones.
  const loadSuggestions = useCallback(
    async (avoid = []) => {
      setLoadingSuggestions(true)
      try {
        const data = await api.suggest({
          context: context || '',
          avoid,
          llm_provider: llmProvider || undefined,
        })
        if (Array.isArray(data.suggestions) && data.suggestions.length) {
          setSuggestions(data.suggestions)
        }
      } catch {
        /* keep the previous chips on failure */
      } finally {
        setLoadingSuggestions(false)
      }
    },
    [context, llmProvider],
  )

  // Auto-update suggestions whenever the conversation context changes.
  useEffect(() => {
    loadSuggestions()
  }, [loadSuggestions])

  async function submitText(e) {
    e?.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    setError('')
    try {
      const data = await api.intentFromText({
        text: text.trim(),
        parser,
        llm_provider: llmProvider || undefined,
        voice_output: voiceOutput,
      })
      onResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function startRecording() {
    setError('')

    // Browsers expose getUserMedia only in a "secure context": HTTPS or
    // localhost/127.0.0.1. Opening the app via a LAN IP over http makes
    // navigator.mediaDevices undefined, which looks like a broken mic.
    if (!navigator.mediaDevices?.getUserMedia) {
      const viaIp = !/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname)
      setError(
        viaIp
          ? `Microphone blocked: open the app at http://localhost:5173 (not ${location.hostname}). ` +
            'Browsers disable the mic on http pages that are not localhost.'
          : 'Microphone unavailable: this browser does not expose getUserMedia. Try Firefox or Chrome.',
      )
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (ev) => ev.data.size > 0 && chunksRef.current.push(ev.data)
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        await transcribeBlob(blob)
      }
      mediaRef.current = recorder
      recorder.start()
      setRecording(true)
    } catch (err) {
      const hints = {
        NotAllowedError:
          'permission denied. Click the 🔒 / camera icon in the address bar, allow the microphone, then retry.',
        NotFoundError: 'no microphone found. Check your input device in system Sound settings.',
        NotReadableError:
          'the microphone is busy in another app (e.g. the voice CLI or another tab). Close it and retry.',
        SecurityError: 'blocked by the browser. Open the app at http://localhost:5173 (not an IP).',
      }
      setError(`Microphone unavailable: ${hints[err.name] || err.message} [${err.name}]`)
    }
  }

  function stopRecording() {
    mediaRef.current?.stop()
    setRecording(false)
  }

  async function transcribeBlob(blob) {
    setBusy(true)
    setError('')
    try {
      const data = await api.intentFromAudio({ blob, parser, stt, llmProvider, voiceOutput })
      setText(data.transcript || '')
      onResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2>Command Console</h2>

      <form onSubmit={submitText} className="console-form">
        <textarea
          rows={2}
          placeholder='Type a command, e.g. "go two stand up"'
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="console-controls">
          <button type="submit" className="btn confirm" disabled={busy || !text.trim()}>
            {busy ? 'Parsing…' : 'Parse intent'}
          </button>

          <button
            type="button"
            className={`btn mic ${recording ? 'recording' : ''}`}
            onClick={recording ? stopRecording : startRecording}
            disabled={busy && !recording}
          >
            {recording ? '● Stop & transcribe' : '🎙 Record'}
          </button>
        </div>
      </form>

      <div className="suggest-head">
        <span className="suggest-label">{context ? 'You might say next' : 'Try saying'}</span>
        <button
          type="button"
          className="chip refresh-chip"
          onClick={() => loadSuggestions(suggestions)}
          disabled={loadingSuggestions}
          title="Show a different batch"
        >
          {loadingSuggestions ? '…' : '↻ refresh'}
        </button>
      </div>
      <div className={`examples ${loadingSuggestions ? 'loading' : ''}`}>
        {suggestions.map((ex) => (
          <button key={ex} type="button" className="chip" onClick={() => setText(ex)}>
            {ex}
          </button>
        ))}
      </div>

      <div className="selectors">
        <label>
          Parser
          <select value={parser} onChange={(e) => setParser(e.target.value)}>
            {config.parsers.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <label>
          STT
          <select value={stt} onChange={(e) => setStt(e.target.value)}>
            {config.stt_modes.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Voice out
          <select value={voiceOutput} onChange={(e) => setVoiceOutput(e.target.value)}>
            <option value="browser">browser</option>
            <option value="robot">robot speaker</option>
            <option value="off">off</option>
          </select>
        </label>
      </div>

      {error && <p className="error">{error}</p>}
    </section>
  )
}
