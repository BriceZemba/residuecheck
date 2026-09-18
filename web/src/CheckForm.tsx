import { useEffect, useId, useRef, useState } from 'react'
import { api, type Crop, type Scenario, type SprayRow } from './api'

export interface FormValue {
  cropCode: string
  harvestOn: string
  rows: SprayRow[]
  csvText: string
  mode: 'rows' | 'csv'
  today?: string // fixed reference date of a demo lot (so a recorded run replays); cleared on edit
}

interface Props {
  crops: Crop[]
  value: FormValue
  onChange: (v: FormValue) => void
  onSubmit: () => void
  scenarios: Scenario[]
  replay: boolean
  onLoadScenario: (s: Scenario) => void
  busy: boolean
}

// Main Moroccan export crops, shown as one-tap choices above the full list.
const QUICK_CROPS = ['0110020', '0110050', '0231010', '0152000', '0231020', '0110030']

function frName(c: Crop) {
  const fr = (c.name_fr ?? '').replace(/^[a-z]\)\s*/, '')
  return fr && fr.toLowerCase() !== c.name.toLowerCase() ? ` · ${fr}` : ''
}

function cropLabel(c: Crop) {
  return c.name.replace(/\/.*$/, '')
}

function ProductInput({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const listId = useId()
  const [options, setOptions] = useState<string[]>([])
  const timer = useRef<number | undefined>(undefined)
  const tooShort = value.trim().length < 2

  useEffect(() => {
    window.clearTimeout(timer.current)
    if (tooShort) return
    timer.current = window.setTimeout(() => {
      api.products(value).then((r) => setOptions(r.products)).catch(() => setOptions([]))
    }, 200)
    return () => window.clearTimeout(timer.current)
  }, [value, tooShort])

  return (
    <>
      <input
        aria-label={label}
        className="input"
        list={listId}
        placeholder="Trade name, e.g. ACTARA 25 WG"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
      />
      <datalist id={listId}>
        {(tooShort ? [] : options).map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </>
  )
}

export function CheckForm({ crops, value, onChange, onSubmit, scenarios, replay, onLoadScenario, busy }: Props) {
  const set = (patch: Partial<FormValue>) => onChange({ ...value, ...patch, today: undefined })
  const setRow = (i: number, patch: Partial<SprayRow>) => set({ rows: value.rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) })
  const filled = value.rows.filter((r) => r.product.trim() && r.applied_on).length
  const ready = value.mode === 'csv' ? value.csvText.trim().length > 0 : filled > 0
  const canSubmit = !busy && !!value.cropCode && !!value.harvestOn && ready
  const quick = QUICK_CROPS.map((code) => crops.find((c) => c.code === code)).filter((c): c is Crop => !!c)

  return (
    <form
      className="card form reveal"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSubmit) onSubmit()
      }}
    >
      {scenarios.length > 0 && (
        <div className="demos">
          <p className="demos-title">No spray log at hand? Try a demo lot:</p>
          <div className="demo-list">
            {scenarios.map((s) => (
              <button key={s.id} type="button" className="demo" onClick={() => onLoadScenario(s)} disabled={busy}>
                <strong>{s.title}</strong>
                <span>{s.blurb}</span>
                {replay && s.recorded && <em className="tag ai">recorded AI run</em>}
              </button>
            ))}
          </div>
        </div>
      )}

      <fieldset className="stage">
        <legend>
          <span className="stage-num">1</span> Crop and harvest
        </legend>
        <p className="hint">The EU limit that counts is the one in force when the fruit arrives, about 10 days after harvest.</p>
        {quick.length > 0 && (
          <div className="chips" role="group" aria-label="Common crops">
            {quick.map((c) => (
              <button
                key={c.code}
                type="button"
                className={c.code === value.cropCode ? 'chip on' : 'chip'}
                aria-pressed={c.code === value.cropCode}
                onClick={() => set({ cropCode: c.code })}
              >
                {cropLabel(c)}
              </button>
            ))}
          </div>
        )}
        <div className="grid-2">
          <label className="field">
            <span>Crop</span>
            <select className="input" value={value.cropCode} onChange={(e) => set({ cropCode: e.target.value })}>
              {crops.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                  {frName(c)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Planned harvest date</span>
            <input className="input" type="date" value={value.harvestOn} onChange={(e) => set({ harvestOn: e.target.value })} />
          </label>
        </div>
        <p className="route">
          <span>Morocco</span>
          <svg viewBox="0 0 40 10" aria-hidden="true">
            <path d="M0 5h36m-5-4 5 4-5 4" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <span>European Union</span>
          <small>Products from the ONSSA register</small>
        </p>
      </fieldset>

      <fieldset className="stage">
        <legend>
          <span className="stage-num">2</span> What you sprayed
        </legend>
        <p className="hint">One line per spray, as written in your notebook. Include planned sprays with their future date to get safer options.</p>

        {value.mode === 'rows' ? (
          <div className="rows">
            <div className="row row-head" aria-hidden="true">
              <span>Product (trade name)</span>
              <span>Sprayed on</span>
              <span />
            </div>
            {value.rows.map((r, i) => (
              <div className="row" key={i}>
                <ProductInput label={`Product ${i + 1}`} value={r.product} onChange={(v) => setRow(i, { product: v })} />
                <input
                  aria-label={`Spray date ${i + 1}`}
                  className="input"
                  type="date"
                  value={r.applied_on}
                  onChange={(e) => setRow(i, { applied_on: e.target.value })}
                />
                <button
                  type="button"
                  className="btn icon"
                  aria-label={`Remove spray ${i + 1}`}
                  disabled={value.rows.length === 1}
                  onClick={() => set({ rows: value.rows.filter((_, j) => j !== i) })}
                >
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
            ))}
            <div className="row-actions">
              <button
                type="button"
                className="btn ghost small"
                onClick={() => set({ rows: [...value.rows, { product: '', applied_on: '' }] })}
                disabled={value.rows.length >= 40}
              >
                + Add a spray
              </button>
              <button type="button" className="linklike small" onClick={() => set({ mode: 'csv' })}>
                Paste from a spreadsheet instead
              </button>
            </div>
          </div>
        ) : (
          <div className="csv">
            <label className="field">
              <span>One spray per line: product, date (YYYY-MM-DD or DD/MM/YYYY)</span>
              <textarea
                aria-label="Spray log pasted from a spreadsheet"
                className="input mono"
                rows={7}
                placeholder={'produit;date\nACTARA 25 WG;15/08/2026\nCYMIL;01/09/2026'}
                value={value.csvText}
                onChange={(e) => set({ csvText: e.target.value })}
              />
            </label>
            <button type="button" className="linklike small" onClick={() => set({ mode: 'rows' })}>
              Back to typing sprays one by one
            </button>
          </div>
        )}
      </fieldset>

      <button type="submit" className="btn primary big submit" disabled={!canSubmit}>
        {busy ? (
          <>
            <span className="spinner light" aria-hidden="true" /> Checking…
          </>
        ) : (
          <>
            Check this lot
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M4 10h11m-4-4 4 4-4 4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </>
        )}
      </button>
      {!ready && !busy && <p className="hint center">Add at least one product with its spray date.</p>}
    </form>
  )
}
