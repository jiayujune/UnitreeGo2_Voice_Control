import { useEffect, useState } from 'react'
import { api } from '../api.js'

function speakInBrowser(text) {
  if (!text || typeof window === 'undefined' || !window.speechSynthesis) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.rate = 1.0
  window.speechSynthesis.speak(utterance)
}

// Renders the most recent parse/execute result: transcript, safety verdict,
// the raw intent JSON, and (for executable commands) a "send to robot" button.
export default function IntentResult({ result, executeEnabled, voiceOutput = 'browser', onExecuted }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [speakMsg, setSpeakMsg] = useState('')

  // Manual replay (🔊 button). Robot replies go through the backend speaker.
  async function speakReply(text) {
    if (voiceOutput === 'off' || !text) return
    if (voiceOutput === 'robot') {
      setSpeakMsg('Sending to robot speaker…')
      try {
        const r = await api.speak(text)
        setSpeakMsg(r.ok ? 'Played on robot speaker 🔊' : `Robot speaker failed: ${JSON.stringify(r.result)}`)
      } catch (e) {
        setSpeakMsg(`Robot speaker failed: ${e.message}`)
      }
    } else {
      speakInBrowser(text)
      setSpeakMsg('')
    }
  }

  // New chat reply: the backend already spoke it on the robot when voice_output
  // was 'robot' (see spoke_on_robot). Here we only handle the browser case and
  // surface the robot status.
  const chatReply = result?.chat_reply
  useEffect(() => {
    if (!chatReply) return
    if (voiceOutput === 'browser') {
      speakInBrowser(chatReply)
      setSpeakMsg('')
    } else if (result?.spoke_on_robot) {
      setSpeakMsg('Played on robot speaker 🔊')
    } else if (result?.speak_error) {
      setSpeakMsg(`Robot speaker failed: ${result.speak_error}`)
    } else {
      setSpeakMsg('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatReply])

  if (!result) {
    return (
      <section className="card">
        <h2>Result</h2>
        <p className="muted">Send a command to see the parsed intent, safety verdict, and plan.</p>
      </section>
    )
  }

  const intent = result.intent || {}
  const executable = !!intent.executable
  const needsConfirm = !!intent.need_confirmation
  const verdict = executable ? (needsConfirm ? 'confirm' : 'safe') : 'blocked'
  const verdictLabel = { safe: 'SAFE · executable', confirm: 'NEEDS CONFIRMATION', blocked: 'NOT EXECUTABLE' }[verdict]

  async function runExecute() {
    setBusy(true)
    setError('')
    try {
      const data = await api.execute({
        command: intent.action,
        duration: Number(intent.duration || 0),
        transcript: result.transcript || '',
        parser: intent.parser || 'rule',
      })
      onExecuted?.(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2>Result</h2>

      {result.transcript !== undefined && (
        <div className="kv">
          <span className="k">Transcript</span>
          <span className="v">{result.transcript || '—'}</span>
        </div>
      )}

      {chatReply && (
        <div className="chat-bubble">
          <span className="chat-avatar">🐾</span>
          <div className="chat-body">
            <div className="chat-name">Go2 says</div>
            <p className="chat-text">{chatReply}</p>
          </div>
          <button
            className="icon-btn speak"
            title={voiceOutput === 'robot' ? 'Replay on robot speaker' : 'Replay voice'}
            onClick={() => speakReply(chatReply)}
          >
            🔊
          </button>
        </div>
      )}

      {speakMsg && <p className="hint">{speakMsg}</p>}

      {result.chat_error && (
        <p className="hint">Chat reply unavailable: {result.chat_error}</p>
      )}

      <div className="kv">
        <span className="k">Intent</span>
        <span className="v">
          <code>{intent.intent}</code> → <code>{intent.action}</code>
          {intent.target ? <> · target <code>{intent.target}</code></> : null}
        </span>
      </div>

      <div className="kv">
        <span className="k">Safety</span>
        <span className="v">
          <span className={`verdict ${verdict}`}>{verdictLabel}</span>
          {executable && <span className="muted"> · duration {Number(intent.duration || 0).toFixed(2)}s</span>}
        </span>
      </div>

      {intent.reason && (
        <div className="kv">
          <span className="k">Reason</span>
          <span className="v muted">{intent.reason}</span>
        </div>
      )}

      {result.executed !== undefined && (
        <div className="kv">
          <span className="k">Execution</span>
          <span className="v">
            {result.dry_run ? (
              <span className="verdict confirm">DRY RUN — nothing sent</span>
            ) : result.executed ? (
              <span className="verdict safe">SENT TO ROBOT</span>
            ) : (
              <span className="verdict blocked">NOT SENT</span>
            )}
          </span>
        </div>
      )}

      {executable && (
        <div className="execute-bar">
          <button className="btn confirm" disabled={busy} onClick={runExecute}>
            {busy ? 'Sending…' : executeEnabled ? '▶ Send to robot' : '▶ Send (dry run)'}
          </button>
          {!executeEnabled && <span className="hint">Live execution is off (GO2_EXECUTE=0).</span>}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <details className="json-details">
        <summary>Raw intent JSON</summary>
        <pre>{JSON.stringify(intent, null, 2)}</pre>
      </details>

      {result.plan && (
        <details className="json-details">
          <summary>High-level plan</summary>
          <pre>{JSON.stringify(result.plan, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
