import { useEffect, useId, useRef, useState } from 'react'
import { api, type Crop, type SprayRow } from './api'

export interface FormValue {
  cropCode: string
  harvestOn: string
  rows: SprayRow[]
  csvText: string
  mode: 'rows' | 'csv'
}

interface Props {
  crops: Crop[]
  value: FormValue
  onChange: (v: FormValue) => void
  onSubmit: () => void
  onLoadExample: () => void
  busy: boolean
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

export function CheckForm({ crops, value, onChange, onSubmit, onLoadExample, busy }: Props) {
  const set = (patch: Partial<FormValue>) => onChange({ ...value, ...patch })
  const setRow = (i: number, patch: Partial<SprayRow>) =>
    set({ rows: value.rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) })
  const canSubmit =
    !busy &&
    value.cropCode &&
    value.harvestOn &&
    (value.mode === 'csv'
      ? value.csvText.trim().length > 0
      : value.rows.some((r) => r.product.trim() && r.applied_on))

  return (
    <form
      className="panel form"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSubmit) onSubmit()
      }}
    >
      <div className="panel-head">
        <h2>Lot to check</h2>
        <button type="button" className="btn ghost small" onClick={onLoadExample}>
          Load example (seeded)
        </button>
      </div>

      <div className="grid-2">
        <label className="field">
          <span>Crop</span>
          <select className="input" value={value.cropCode} onChange={(e) => set({ cropCode: e.target.value })}>
            {crops.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
                {c.name_fr ? ` · ${c.name_fr.replace(/^[a-z]\)\s*/, '')}` : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Planned harvest</span>
          <input className="input" type="date" value={value.harvestOn} onChange={(e) => set({ harvestOn: e.target.value })} />
        </label>
      </div>

      <div className="grid-2">
        <label className="field">
          <span>Origin</span>
          <select className="input" value="MA" disabled>
            <option value="MA">Morocco (ONSSA register)</option>
          </select>
        </label>
        <label className="field">
          <span>Destination</span>
          <select className="input" value="EU" disabled>
            <option value="EU">European Union</option>
          </select>
        </label>
      </div>

      <div className="tabs" role="tablist" aria-label="Spray log input">
        <button type="button" role="tab" aria-selected={value.mode === 'rows'} className={value.mode === 'rows' ? 'tab on' : 'tab'} onClick={() => set({ mode: 'rows' })}>
          Spray records
        </button>
        <button type="button" role="tab" aria-selected={value.mode === 'csv'} className={value.mode === 'csv' ? 'tab on' : 'tab'} onClick={() => set({ mode: 'csv' })}>
          Paste CSV
        </button>
      </div>

      {value.mode === 'rows' ? (
        <div className="rows">
          <div className="row row-head">
            <span>Product</span>
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
                aria-label={`Remove product ${i + 1}`}
                disabled={value.rows.length === 1}
                onClick={() => set({ rows: value.rows.filter((_, j) => j !== i) })}
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn ghost small add"
            onClick={() => set({ rows: [...value.rows, { product: '', applied_on: '' }] })}
            disabled={value.rows.length >= 40}
          >
            + Add product
          </button>
        </div>
      ) : (
        <label className="field">
          <span>One product per line: name, date (YYYY-MM-DD or DD/MM/YYYY)</span>
          <textarea
            aria-label="Spray log as CSV"
            className="input mono"
            rows={7}
            placeholder={'produit;date\nACTARA 25 WG;15/08/2026\nCYMIL;01/09/2026'}
            value={value.csvText}
            onChange={(e) => set({ csvText: e.target.value })}
          />
        </label>
      )}

      <button type="submit" className="btn primary" disabled={!canSubmit}>
        {busy ? 'Checking…' : 'Check lot'}
      </button>
    </form>
  )
}
