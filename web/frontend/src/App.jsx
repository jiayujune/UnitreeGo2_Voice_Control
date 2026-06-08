import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import CommandConsole from './components/CommandConsole.jsx'
import IntentResult from './components/IntentResult.jsx'
import ActionPanel from './components/ActionPanel.jsx'
import CommandLog from './components/CommandLog.jsx'
import SettingsModal from './components/SettingsModal.jsx'
import VolumeControl from './components/VolumeControl.jsx'

export default function App() {
  const [config, setConfig] = useState(null)
  const [configError, setConfigError] = useState('')
  const [result, setResult] = useState(null)
  const [events, setEvents] = useState([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settings, setSettings] = useState(null)

  const [parser, setParser] = useState('rule')
  const [stt, setStt] = useState('groq')
  const [voiceOutput, setVoiceOutput] = useState('robot') // browser | robot | off

  const refreshLogs = useCallback(async () => {
    try {
      const data = await api.getLogs(50)
      setEvents(data.events || [])
    } catch {
      /* ignore log read errors */
    }
  }, [])

  useEffect(() => {
    api
      .getConfig()
      .then(setConfig)
      .catch((e) => setConfigError(e.message))
    api.getSettings().then(setSettings).catch(() => {})
    refreshLogs()
  }, [refreshLogs])

  // Any new result also refreshes the history.
  const handleResult = useCallback(
    (data) => {
      setResult(data)
      refreshLogs()
    },
    [refreshLogs],
  )

  const handleExecuted = useCallback(
    (data) => {
      setResult((prev) => ({ ...prev, ...data }))
      refreshLogs()
    },
    [refreshLogs],
  )

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">🐾</span>
          <div>
            <h1>Unitree Go2 Voice Control</h1>
            <p className="sub">Mic / text → Whisper → intent → safety → robot</p>
          </div>
        </div>
        <div className="topbar-right">
          <StatusPills config={config} configError={configError} settings={settings} />
          <button className="btn ghost small gear" onClick={() => setSettingsOpen(true)}>
            ⚙ Settings
          </button>
        </div>
      </header>

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={setSettings}
      />

      {configError && (
        <div className="banner error-banner">
          Backend not reachable: {configError}. Start it with
          <code> uvicorn app:app --port 8001</code> in <code>web/backend</code>.
        </div>
      )}

      {config && (
        <main className="grid">
          <div className="col">
            <CommandConsole
              config={config}
              parser={parser}
              setParser={setParser}
              stt={stt}
              setStt={setStt}
              voiceOutput={voiceOutput}
              setVoiceOutput={setVoiceOutput}
              context={buildContext(result)}
              onResult={handleResult}
            />
            <ActionPanel movementActions={config.movement_actions} onResult={handleResult} />
            <VolumeControl />
          </div>
          <div className="col">
            <IntentResult
              result={result}
              executeEnabled={config.execute_enabled}
              voiceOutput={voiceOutput}
              onExecuted={handleExecuted}
            />
            <CommandLog events={events} onRefresh={refreshLogs} />
          </div>
        </main>
      )}
    </div>
  )
}

// Compact context string from the latest result, fed to the suggestion engine.
function buildContext(result) {
  if (!result) return ''
  const parts = []
  if (result.transcript) parts.push(`User said: "${result.transcript}"`)
  const action = result.intent?.action
  if (action && action !== 'none') parts.push(`Robot action: ${action}`)
  if (result.chat_reply) parts.push(`Go2 replied: "${result.chat_reply}"`)
  return parts.join('\n')
}

function StatusPills({ config, configError, settings }) {
  const online = !!config && !configError
  return (
    <div className="status-pills">
      <span className={`pill ${online ? 'ok' : 'off'}`}>
        <span className="dot-inline" /> {online ? 'Backend online' : 'Backend offline'}
      </span>
      {config && (
        <>
          <span className={`pill ${config.execute_enabled ? 'live' : 'safe'}`}>
            {config.execute_enabled ? 'LIVE EXECUTION' : 'DRY RUN'}
          </span>
          <span className={`pill ${settings?.groq_api_key_set ? 'ok' : 'neutral'}`} title="Groq API key">
            Groq key {settings?.groq_api_key_set ? '✓' : '—'}
          </span>
        </>
      )}
    </div>
  )
}
