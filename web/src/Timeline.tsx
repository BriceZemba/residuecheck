import { useEffect, useRef, useState } from 'react'
import type { CheckResult } from './api'

const DAY = 86_400_000
const RIGHT = 18
const TOP = 46
const ROW = 34

const t = (iso: string) => new Date(iso + 'T00:00:00').getTime()
const short = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + '…' : s)

/** Sprays, their waiting time before harvest, and the harvest and EU arrival dates on one line. */
export function Timeline({ result }: { result: CheckResult }) {
  // Drawn at the card's real width so text stays readable on a phone.
  const box = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(640)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(300, Math.round(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const LABEL = W < 480 ? 96 : 150
  const nameChars = W < 480 ? 12 : 20
  const apps = result.applications.map((a) => {
    const start = t(a.applied_on)
    const end = a.dar_days != null ? start + a.dar_days * DAY : null
    return { name: a.trade_name ?? a.input, start, end, dar: a.dar_days, planned: a.applied_on > result.today }
  })
  const harvest = t(result.harvest_on)
  const arrival = t(result.arrival_on)
  const today = t(result.today)
  const lo = Math.min(today, ...apps.map((a) => a.start)) - 5 * DAY
  const hi = Math.max(arrival, ...apps.map((a) => a.end ?? a.start)) + 5 * DAY
  const x = (ms: number) => LABEL + ((ms - lo) / (hi - lo)) * (W - LABEL - RIGHT)
  const H = TOP + apps.length * ROW + 30

  const months: number[] = []
  const m = new Date(lo)
  m.setDate(1)
  m.setMonth(m.getMonth() + 1)
  while (m.getTime() < hi) {
    months.push(m.getTime())
    m.setMonth(m.getMonth() + 1)
  }

  // Two label rows so close dates (harvest and arrival are 10 days apart) do not overlap.
  const markers = [
    { at: today, label: 'Today', cls: 'today' },
    { at: harvest, label: 'Harvest', cls: 'harvest' },
    { at: arrival, label: 'EU arrival', cls: 'arrival' },
  ]
    .sort((p, q) => p.at - q.at)
    .map((mk) => ({ ...mk, row: 0 }))
  markers.forEach((mk, i) => {
    if (i > 0 && x(mk.at) - x(markers[i - 1].at) < 74) mk.row = 1 - markers[i - 1].row
  })

  return (
    <div className="card timeline" ref={box}>
      <h4>Spray calendar</h4>
      <p className="small muted">Each bar is the waiting time a product needs before harvest. A red bar still runs on harvest day.</p>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Timeline of sprays, waiting times, harvest and EU arrival">
        {months.map((ms) => (
          <g key={ms} className="tl-month">
            <line x1={x(ms)} x2={x(ms)} y1={TOP - 6} y2={H - 24} />
            <text x={x(ms) + 4} y={H - 10}>
              {new Date(ms).toLocaleDateString('en-GB', { month: 'short' })}
            </text>
          </g>
        ))}
        {apps.map((a, i) => {
          const y = TOP + i * ROW + ROW / 2
          const late = a.end != null && a.end > harvest
          return (
            <g key={i} className="tl-row" style={{ animationDelay: `${200 + i * 120}ms` }}>
              <text className="tl-name" x={LABEL - 12} y={y + 4} textAnchor="end">
                <title>{a.name}</title>
                {clip(a.name, nameChars)}
              </text>
              <line className="tl-track" x1={LABEL} x2={W - RIGHT} y1={y} y2={y} />
              {a.end != null && (
                <rect
                  className={`tl-bar ${late ? 'late' : 'ok'}`}
                  style={{ animationDelay: `${350 + i * 120}ms` }}
                  x={x(a.start)}
                  y={y - 6}
                  width={Math.max(2, x(a.end) - x(a.start))}
                  height={12}
                  rx={6}
                >
                  <title>{`${a.name}: sprayed ${short(a.start)}, wait ${a.dar} days, until ${short(a.end)}`}</title>
                </rect>
              )}
              <circle className={a.planned ? 'tl-dot planned' : 'tl-dot'} cx={x(a.start)} cy={y} r={6} />
              {a.end == null && (
                <text className="tl-unknown" x={x(a.start) + 12} y={y + 4}>
                  waiting time unknown
                </text>
              )}
            </g>
          )
        })}
        {markers.map((mk) => (
          <g key={mk.cls} className={`tl-marker ${mk.cls}`}>
            <line x1={x(mk.at)} x2={x(mk.at)} y1={TOP - 26 + mk.row * 14} y2={H - 24} />
            <text x={Math.min(W - 34, Math.max(LABEL + 30, x(mk.at)))} y={TOP - 30 + mk.row * 14} textAnchor="middle">
              {mk.label}
            </text>
          </g>
        ))}
      </svg>
      <div className="tl-legend small">
        <span>
          <i className="dot" /> spray done
        </span>
        <span>
          <i className="dot hollow" /> spray planned
        </span>
        <span>
          <i className="bar ok" /> waiting time over by harvest
        </span>
        <span>
          <i className="bar late" /> not over by harvest
        </span>
      </div>
    </div>
  )
}
