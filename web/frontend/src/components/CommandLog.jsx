// Read-only history of commands, newest first, from the backend log file.
export default function CommandLog({ events, onRefresh }) {
  return (
    <section className="card">
      <div className="log-header">
        <h2>Command History</h2>
        <button className="btn small ghost" onClick={onRefresh}>↻ Refresh</button>
      </div>

      {events.length === 0 ? (
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
      )}
    </section>
  )
}
