import { useState } from 'react'
import { api } from '../api.js'

// Action buttons grouped by safety class. Movement actions require confirmation.
const POSTURE = [
  { cmd: 'stand_up', label: 'Stand Up', icon: '⬆' },
  { cmd: 'stand_down', label: 'Stand Down', icon: '⬇' },
  { cmd: 'balance', label: 'Balance', icon: '⚖' },
  { cmd: 'recovery', label: 'Recovery', icon: '🔧' },
]
const MOVEMENT = [
  { cmd: 'forward', label: 'Forward', icon: '↑' },
  { cmd: 'backward', label: 'Backward', icon: '↓' },
  { cmd: 'turn_left', label: 'Turn Left', icon: '↺' },
  { cmd: 'turn_right', label: 'Turn Right', icon: '↻' },
]

export default function ActionPanel({ movementActions, onResult }) {
  const [pending, setPending] = useState(null) // action waiting for confirmation
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')

  const movementSet = new Set(movementActions)

  async function send(cmd, confirmed = false) {
    setError('')
    setBusy(cmd)
    try {
      const data = await api.action({ command: cmd, duration: 0.8, confirmed })
      if (data.needs_confirmation) {
        setPending(cmd)
      } else {
        setPending(null)
        onResult(data)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  function handleClick(cmd) {
    if (movementSet.has(cmd)) {
      setPending(cmd) // ask for confirmation first
    } else {
      send(cmd)
    }
  }

  return (
    <section className="card">
      <h2>Action Panel</h2>

      <div className="action-row danger">
        <button className="btn stop" disabled={busy === 'stop'} onClick={() => send('stop')}>
          ■ STOP
        </button>
        <span className="hint">Always safe — sent immediately.</span>
      </div>

      <h3 className="group-label">Posture</h3>
      <div className="action-grid">
        {POSTURE.map((a) => (
          <button key={a.cmd} className="btn" disabled={busy === a.cmd} onClick={() => handleClick(a.cmd)}>
            <span className="icon">{a.icon}</span>
            {a.label}
          </button>
        ))}
      </div>

      <h3 className="group-label">Movement <span className="badge warn">needs confirm</span></h3>
      <div className="action-grid">
        {MOVEMENT.map((a) => (
          <button key={a.cmd} className="btn move" disabled={busy === a.cmd} onClick={() => handleClick(a.cmd)}>
            <span className="icon">{a.icon}</span>
            {a.label}
          </button>
        ))}
      </div>

      {pending && (
        <div className="confirm-bar">
          <span>
            Confirm movement: <strong>{pending.replace('_', ' ')}</strong>?
          </span>
          <div>
            <button className="btn small confirm" onClick={() => send(pending, true)}>
              Yes, send
            </button>
            <button className="btn small ghost" onClick={() => setPending(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
    </section>
  )
}
