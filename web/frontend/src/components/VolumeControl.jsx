import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

// Robot speaker volume (Go2 vui, 0-10). Reads current level on mount; writes
// are debounced so dragging the slider doesn't spam the robot.
export default function VolumeControl() {
  const [level, setLevel] = useState(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const debounceRef = useRef(null)

  useEffect(() => {
    api
      .getVolume()
      .then((r) => {
        if (r.ok && typeof r.volume === 'number') setLevel(r.volume)
        else setError('Could not read robot volume.')
      })
      .catch((e) => setError(e.message))
  }, [])

  function onSlide(next) {
    setLevel(next)
    setStatus('')
    setError('')
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        const r = await api.setVolume(next)
        if (r.ok) setStatus(`Set to ${r.volume}`)
        else setError(r.error || 'Failed to set volume.')
      } catch (e) {
        setError(e.message)
      }
    }, 350)
  }

  const disabled = level === null && !error

  return (
    <section className="card">
      <div className="vol-head">
        <h2>Robot Speaker Volume</h2>
        <span className="vol-value">{level === null ? '—' : level}</span>
      </div>

      <div className="vol-row">
        <span className="vol-icon">🔈</span>
        <input
          type="range"
          min={0}
          max={10}
          step={1}
          value={level ?? 0}
          disabled={disabled}
          onChange={(e) => onSlide(Number(e.target.value))}
          className="vol-slider"
        />
        <span className="vol-icon">🔊</span>
      </div>

      <div className="vol-ticks">
        {Array.from({ length: 11 }, (_, i) => (
          <span key={i} className={i === level ? 'on' : ''}>{i}</span>
        ))}
      </div>

      {status && <p className="saved-msg">{status}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  )
}
