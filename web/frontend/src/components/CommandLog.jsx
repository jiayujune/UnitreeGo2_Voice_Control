import { useState } from 'react'

// Read-only history of commands, newest first, from the backend log file.
// Collapsible, with refresh (reload) and clear (wipe) actions.
export default function CommandLog({ events, onRefresh, onClear }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <section className="card">
      <div className="log-header">
        <button
          type="button"
          className="log-toggle"
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          <span className="caret">{collapsed ? '▸' : '▾'}</span>
          <h2>Command History</h2>
          {events.length > 0 && <span className="log-count">{events.length}</span>}
        </button>
        <div className="log-actions">
          <button className="btn small ghost" onClick={onRefresh}>↻ Refresh</button>
          <button
            className="btn small ghost danger"
            onClick={onClear}
            disabled={events.length === 0}
          >
            🗑 Clear
          </button>
        </div>
      </div>

      {!collapsed &&
        (events.length === 0 ? (
          <p className="muted">No commands yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Source</th>
                  <th>Transcript</th>
                  <th>Action</th>
                  <th>Exec</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev, i) => {
                  const intent = ev.intent || {}
                  const time = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : '—'
                  return (
                    <tr key={i}>
                      <td className="mono">{time}</td>
                      <td><span className="tag">{ev.source}</span></td>
                      <td className="ellipsis" title={ev.transcript}>{ev.transcript || '—'}</td>
                      <td><code>{intent.action || 'none'}</code></td>
                      <td>
                        {ev.dry_run ? (
                          <span className="dot dry" title="dry run" />
                        ) : ev.executed ? (
                          <span className="dot ok" title="sent" />
                        ) : (
                          <span className="dot no" title="not sent" />
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))}
    </section>
  )
}
