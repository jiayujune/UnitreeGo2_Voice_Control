import { useEffect, useState } from 'react'
import { api } from '../api.js'

// Modal for saving API keys (Groq / OpenAI). The backend persists them to a
// gitignored file and pushes them into its process env for STT / LLM calls.
export default function SettingsModal({ open, onClose, onSaved }) {
  const [status, setStatus] = useState(null)
  const [groq, setGroq] = useState('')
  const [openai, setOpenai] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [savedMsg, setSavedMsg] = useState('')

  useEffect(() => {
    if (!open) return
    setError('')
    setSavedMsg('')
    setGroq('')
    setOpenai('')
    api.getSettings().then(setStatus).catch((e) => setError(e.message))
  }, [open])

  if (!open) return null

  async function save() {
    setBusy(true)
    setError('')
    setSavedMsg('')
    try {
      // Only send fields the user actually typed into.
      const body = {}
      if (groq !== '') body.groq_api_key = groq.trim()
      if (openai !== '') body.openai_api_key = openai.trim()
      if (Object.keys(body).length === 0) {
        setSavedMsg('Nothing changed.')
        setBusy(false)
        return
      }
      const next = await api.saveSettings(body)
      setStatus(next)
      setGroq('')
      setOpenai('')
      setSavedMsg('Saved.')
      onSaved?.(next)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>API Keys</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <p className="muted small-note">
          用于浏览器录音的语音识别(STT)和 LLM 意图解析。Key 保存在后端本地文件
          <code> runtime/web_settings.json</code>(已 gitignore),不会上传任何地方。
        </p>

        <KeyField
          label="Groq API key"
          placeholder="gsk_..."
          value={groq}
          onChange={setGroq}
          isSet={status?.groq_api_key_set}
          hint={status?.groq_api_key_hint}
        />
        <KeyField
          label="OpenAI API key (可选)"
          placeholder="sk-..."
          value={openai}
          onChange={setOpenai}
          isSet={status?.openai_api_key_set}
          hint={status?.openai_api_key_hint}
        />

        {error && <p className="error">{error}</p>}
        {savedMsg && <p className="saved-msg">{savedMsg}</p>}

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>关闭</button>
          <button className="btn confirm" disabled={busy} onClick={save}>
            {busy ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

function KeyField({ label, placeholder, value, onChange, isSet, hint }) {
  return (
    <label className="key-field">
      <span className="key-label">
        {label}
        {isSet ? (
          <span className="badge ok-badge">已设置 {hint}</span>
        ) : (
          <span className="badge warn">未设置</span>
        )}
      </span>
      <input
        type="password"
        autoComplete="off"
        placeholder={isSet ? '已保存 — 留空则不修改，输入新值覆盖' : placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}
