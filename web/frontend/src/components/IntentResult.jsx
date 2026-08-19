import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

function speakInBrowser(text) {
  if (!text || typeof window === 'undefined' || !window.speechSynthesis) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.rate = 1.0
  window.speechSynthesis.speak(utterance)
}

// Spoken phrasing for each robot action, mirroring robot_action_label in the CLI.
const ACTION_LABELS = {
  stop: 'stop',
  balance: 'balance stand',
  stand_up: 'stand up',
  stand_down: 'stand down',
  recovery: 'recovery stand',
  forward: 'move forward',
  backward: 'move backward',
  turn_left: 'turn left',
  turn_right: 'turn right',
}

function actionLabel(action) {
  return ACTION_LABELS[action] || (action ? action.replace(/_/g, ' ') : 'do that')
}

function capitalize(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text
}

// Renders the most recent parse/execute result: transcript, safety verdict,
// the raw intent JSON, and (for executable commands) a "send to robot" button.
export default function IntentResult({ result, executeEnabled, voiceOutput = 'browser', onExecuted }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [speakMsg, setSpeakMsg] = useState('')
  const [seqStatus, setSeqStatus] = useState([])

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

  // Speak feedback for every new result — both casual chat replies AND robot
  // command confirmations ("Okay. Move forward."), mirroring the CLI. Previously
  // only chat replies were voiced, so plain commands were silent.
  const chatReply = result?.chat_reply
  const lastSpokenRef = useRef('')
  useEffect(() => {
    if (!result || voiceOutput === 'off') return

    const intent = result.intent || {}
    const label = actionLabel(intent.action)

    let phrase = ''
    if (chatReply) {
      phrase = chatReply
    } else if (intent.executable) {
      if (result.dry_run) phrase = `Dry run. I would ${label}.`
      else if (result.executed) phrase = `Okay. ${capitalize(label)}.`
      else if (intent.need_confirmation) phrase = `Ready to ${label}. Please confirm.`
      else phrase = `Ready to ${label}.`
    } else if (result.chat_error) {
      phrase = 'Sorry, I could not reach my language model.'
    } else if (result.transcript !== undefined) {
      phrase = 'Sorry, I did not catch a supported command.'
    }
    if (!phrase) return

    // Dedupe so the same result (and React StrictMode's double-invoke) speaks once.
    const sig = `${phrase}|${result.executed}|${result.dry_run}`
    if (sig === lastSpokenRef.current) return
    lastSpokenRef.current = sig

    if (voiceOutput === 'browser') {
      speakInBrowser(phrase)
      setSpeakMsg('')
      return
    }

    // robot mode
    if (chatReply) {
      // Chat replies are spoken server-side (see maybe_chat_reply); just surface status.
      if (result.spoke_on_robot) setSpeakMsg('Played on robot speaker 🔊')
      else if (result.speak_error) setSpeakMsg(`Robot speaker failed: ${result.speak_error}`)
      else setSpeakMsg('')
    } else if (intent.executable && result.executed !== undefined) {
      // Command confirmation: speak on the robot only once it has actually run,
      // to avoid double-talk on the choppy robot speaker.
      setSpeakMsg('Sending to robot speaker…')
      api
        .speak(phrase)
        .then((r) => setSpeakMsg(r.ok ? 'Played on robot speaker 🔊' : `Robot speaker failed: ${JSON.stringify(r.result)}`))
        .catch((e) => setSpeakMsg(`Robot speaker failed: ${e.message}`))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result])

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
  const world = result.world_model
  let verdict = executable ? (needsConfirm ? 'confirm' : 'safe') : 'blocked'
  let verdictLabel = { safe: 'SAFE · executable', confirm: 'NEEDS CONFIRMATION', blocked: 'NOT EXECUTABLE' }[verdict]
  if (world?.used) {
    // The raw intent is not directly executable, but the assumed world model
    // turned it into a runnable orient-and-approach sequence.
    verdict = 'confirm'
    verdictLabel = 'EXECUTABLE · assumed world'
  }

  const commands = result.commands || []
  // A world-model plan can be a single step (object straight ahead); treat any
  // command list as a runnable sequence when the top intent isn't directly executable.
  const isSequence = commands.length > 1 || (commands.length >= 1 && !executable)

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

  // Execute a multi-command utterance ("forward and turn right") in order. Each
  // step goes through /api/execute; a failure or a 'stop' halts the rest.
  async function runSequence() {
    if (executeEnabled && commands.some((c) => c.need_confirmation)) {
      const plan = commands.map((c) => c.label).join(', then ')
      if (!window.confirm(`Run this sequence on the robot: ${plan}?`)) return
    }
    setBusy(true)
    setError('')
    const statuses = commands.map(() => 'pending')
    setSeqStatus([...statuses])
    let lastData = null
    for (let i = 0; i < commands.length; i++) {
      statuses[i] = 'running'
      setSeqStatus([...statuses])
      try {
        const data = await api.execute({
          command: commands[i].action,
          duration: Number(commands[i].duration || 0),
          transcript: result.transcript || '',
          parser: intent.parser || 'rule',
        })
        lastData = data
        const ok = data.dry_run || data.executed
        statuses[i] = ok ? 'done' : 'failed'
        setSeqStatus([...statuses])
        if (!ok) {
          setError(data.result?.error || 'Robot rejected the command — stopped the sequence.')
          break
        }
        if (commands[i].action === 'stop') break // stop halts the rest
      } catch (e) {
        statuses[i] = 'failed'
        setSeqStatus([...statuses])
        setError(e.message)
        break
      }
    }
    if (lastData) onExecuted?.(lastData)
    setBusy(false)
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

      {world?.used && (
        <div className="kv">
          <span className="k">World model</span>
          <span className="v">
            <span className="verdict assumed">ASSUMED WORLD</span>
            <span className="muted">
              {' '}· {world.object} is {world.direction} ({world.distance_m}m) → orient &amp; approach
              {world.blocked_by
                ? `, blocked by ${world.blocked_by} (stops short)`
                : world.detour_around
                  ? `, detour around ${world.detour_around}`
                  : ''}
              , {world.step_count} steps. Position is operator-set, not perceived.
            </span>
          </span>
        </div>
      )}

      {intent.reason && !isSequence && (
        <div className="kv">
          <span className="k">Reason</span>
          <span className="v muted">{intent.reason}</span>
        </div>
      )}

      {isSequence && (
        <div className="kv">
          <span className="k">Sequence</span>
          <span className="v">
            <ol className="seq-list">
              {commands.map((c, i) => (
                <li key={i} className={`seq-step ${seqStatus[i] || ''}`}>
                  {c.label}
                  {seqStatus[i] === 'done' && ' ✓'}
                  {seqStatus[i] === 'running' && ' …'}
                  {seqStatus[i] === 'failed' && ' ✗'}
                </li>
              ))}
            </ol>
          </span>
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

      {isSequence ? (
        <div className="execute-bar">
          <button className="btn confirm" disabled={busy} onClick={runSequence}>
            {busy
              ? 'Running…'
              : executeEnabled
                ? `▶ Send sequence (${commands.length})`
                : `▶ Send sequence (${commands.length}, dry run)`}
          </button>
          {!executeEnabled && <span className="hint">Live execution is off (GO2_EXECUTE=0).</span>}
        </div>
      ) : executable ? (
        <div className="execute-bar">
          <button className="btn confirm" disabled={busy} onClick={runExecute}>
            {busy ? 'Sending…' : executeEnabled ? '▶ Send to robot' : '▶ Send (dry run)'}
          </button>
          {!executeEnabled && <span className="hint">Live execution is off (GO2_EXECUTE=0).</span>}
        </div>
      ) : null}

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
