import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

// Top-down "assumed world" editor. Go2 sits at the center facing up; the operator
// drags objects around it. Each object's canvas position is converted to a
// bearing (deg from the robot's front, + = right) and distance (m), persisted to
// the backend scene so the planner can turn "find the apple" into turn+approach.

const SIZE = 320
const C = SIZE / 2
const MAX_DISTANCE_M = 2.5
const MAX_RADIUS_PX = 140
const PX_PER_M = MAX_RADIUS_PX / MAX_DISTANCE_M
const RINGS_M = [0.5, 1.0, 1.5, 2.0, 2.5]

const OBJ_TYPES = [
  { name: 'apple', emoji: '🍎' },
  { name: 'ball', emoji: '🎾' },
  { name: 'bone', emoji: '🦴' },
  { name: 'chair', emoji: '🪑' },
  { name: 'box', emoji: '📦' },
  { name: 'person', emoji: '🧍' },
]
const EMOJI = Object.fromEntries(OBJ_TYPES.map((o) => [o.name, o.emoji]))
const emojiFor = (name) => EMOJI[name] || '📍'

function xyToPolar(x, y) {
  const dx = x - C
  const dy = y - C
  return {
    bearing_deg: (Math.atan2(dx, -dy) * 180) / Math.PI, // 0 = up/front, + = right
    distance_m: Math.hypot(dx, dy) / PX_PER_M,
  }
}

function polarToXy(bearing_deg, distance_m) {
  const r = Math.min(distance_m * PX_PER_M, MAX_RADIUS_PX)
  const a = (bearing_deg * Math.PI) / 180
  return { x: C + r * Math.sin(a), y: C - r * Math.cos(a) }
}

function clampToField(x, y) {
  const dx = x - C
  const dy = y - C
  const r = Math.hypot(dx, dy)
  if (r <= MAX_RADIUS_PX) return { x, y }
  const k = MAX_RADIUS_PX / r
  return { x: C + dx * k, y: C + dy * k }
}

function directionWord(bearing_deg) {
  const b = (((bearing_deg + 180) % 360) + 360) % 360 - 180
  const a = Math.abs(b)
  if (a <= 25) return 'ahead'
  if (a >= 155) return 'behind'
  const side = b > 0 ? 'right' : 'left'
  return a <= 90 ? side : `back-${side}`
}

export default function SceneEditor() {
  const [objects, setObjects] = useState([])
  const [status, setStatus] = useState('')
  const svgRef = useRef(null)
  const dragRef = useRef(null)

  useEffect(() => {
    api
      .getScene()
      .then((scene) => {
        const objs = (scene.objects || []).map((o, i) => {
          const pos =
            o.x != null && o.y != null
              ? { x: o.x, y: o.y }
              : polarToXy(o.bearing_deg || 0, o.distance_m || 0)
          return { id: o.id || `${o.name}-${i}`, name: o.name, ...pos }
        })
        setObjects(objs)
      })
      .catch(() => {})
  }, [])

  function persist(objs) {
    const payload = objs.map((o) => {
      const { bearing_deg, distance_m } = xyToPolar(o.x, o.y)
      return {
        id: o.id,
        name: o.name,
        bearing_deg: Math.round(bearing_deg * 10) / 10,
        distance_m: Math.round(distance_m * 100) / 100,
        x: Math.round(o.x * 10) / 10,
        y: Math.round(o.y * 10) / 10,
      }
    })
    setStatus('Saving…')
    api
      .saveScene(payload)
      .then(() => setStatus('Saved ✓'))
      .catch((e) => setStatus(`Save failed: ${e.message}`))
  }

  function addObject(name) {
    setObjects((prev) => {
      const n = prev.length
      const spread = polarToXy(((n * 55) % 360) - 180, 1.0)
      const pos = clampToField(spread.x, spread.y)
      const id = `${name}-${Date.now()}`
      const next = [...prev, { id, name, ...pos }]
      persist(next)
      return next
    })
  }

  function removeObject(id) {
    setObjects((prev) => {
      const next = prev.filter((o) => o.id !== id)
      persist(next)
      return next
    })
  }

  function clearAll() {
    persist([])
    setObjects([])
  }

  function clientToSvg(evt) {
    const svg = svgRef.current
    const ctm = svg && svg.getScreenCTM()
    if (!ctm) return { x: C, y: C }
    const pt = svg.createSVGPoint()
    pt.x = evt.clientX
    pt.y = evt.clientY
    const p = pt.matrixTransform(ctm.inverse())
    return { x: p.x, y: p.y }
  }

  function onPointerDown(evt, id) {
    evt.preventDefault()
    dragRef.current = id
    evt.target.setPointerCapture?.(evt.pointerId)
  }

  function onPointerMove(evt) {
    if (!dragRef.current) return
    const p = clientToSvg(evt)
    const { x, y } = clampToField(p.x, p.y)
    setObjects((prev) => prev.map((o) => (o.id === dragRef.current ? { ...o, x, y } : o)))
  }

  function onPointerUp() {
    if (!dragRef.current) return
    dragRef.current = null
    setObjects((prev) => {
      persist(prev)
      return prev
    })
  }

  return (
    <section className="card scene-card">
      <div className="scene-head">
        <h2>Scene · assumed world</h2>
        <span className="scene-status muted">{status}</span>
      </div>
      <p className="muted scene-sub">
        No camera yet — drag objects to tell Go2 what's around it. Lets it plan
        “find the apple” as turn&nbsp;+&nbsp;approach. Tap the red&nbsp;✕ (or
        double-click) to remove one.
      </p>

      <svg
        ref={svgRef}
        className="scene-svg"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {RINGS_M.map((m) => (
          <g key={m}>
            <circle cx={C} cy={C} r={m * PX_PER_M} className="scene-ring" />
            <text x={C + 3} y={C - m * PX_PER_M + 13} className="scene-ring-label">
              {m}m
            </text>
          </g>
        ))}

        <line x1={C} y1={C - MAX_RADIUS_PX} x2={C} y2={C + MAX_RADIUS_PX} className="scene-axis" />
        <line x1={C - MAX_RADIUS_PX} y1={C} x2={C + MAX_RADIUS_PX} y2={C} className="scene-axis" />

        <polygon
          points={`${C - 7},${C - MAX_RADIUS_PX + 15} ${C + 7},${C - MAX_RADIUS_PX + 15} ${C},${C - MAX_RADIUS_PX + 3}`}
          className="scene-front"
        />
        <text x={C} y={C - MAX_RADIUS_PX - 4} textAnchor="middle" className="scene-front-label">
          front
        </text>

        <circle cx={C} cy={C} r={18} className="scene-robot" />
        <text x={C} y={C + 7} textAnchor="middle" fontSize="20">
          🐕
        </text>

        {objects.map((o) => (
          <g key={o.id} className="scene-obj">
            <line x1={C} y1={C} x2={o.x} y2={o.y} className="scene-link" />
            <g
              onPointerDown={(e) => onPointerDown(e, o.id)}
              onDoubleClick={() => removeObject(o.id)}
            >
              <circle cx={o.x} cy={o.y} r={15} className="scene-obj-dot" />
              <text x={o.x} y={o.y + 5} textAnchor="middle" fontSize="16">
                {emojiFor(o.name)}
              </text>
            </g>
            {/* Per-object delete button: stop propagation so it never starts a drag. */}
            <g
              className="scene-del"
              onPointerDown={(e) => {
                e.stopPropagation()
                e.preventDefault()
              }}
              onClick={(e) => {
                e.stopPropagation()
                removeObject(o.id)
              }}
            >
              <circle cx={o.x + 14} cy={o.y - 14} r={8} className="scene-del-dot" />
              <text x={o.x + 14} y={o.y - 11} textAnchor="middle" className="scene-del-x">
                ✕
              </text>
            </g>
          </g>
        ))}
      </svg>

      <div className="scene-palette">
        {OBJ_TYPES.map((t) => (
          <button key={t.name} type="button" className="chip" onClick={() => addObject(t.name)}>
            {t.emoji} {t.name}
          </button>
        ))}
        {objects.length > 0 && (
          <button type="button" className="chip danger" onClick={clearAll}>
            ✕ clear
          </button>
        )}
      </div>

      {objects.length > 0 && (
        <ul className="scene-list">
          {objects.map((o) => {
            const { bearing_deg, distance_m } = xyToPolar(o.x, o.y)
            return (
              <li key={o.id}>
                <span className="scene-list-name">
                  {emojiFor(o.name)} {o.name}
                </span>
                <span className="muted">
                  {directionWord(bearing_deg)} · {distance_m.toFixed(2)}m · {Math.round(bearing_deg)}°
                </span>
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => removeObject(o.id)}
                  title="Remove"
                >
                  ✕
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
