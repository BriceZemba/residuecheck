import { useEffect, useState } from 'react'
import { api, type CheckResult, type Crop, type Health } from './api'
import { CheckForm, type FormValue } from './CheckForm'
import { ResultView } from './ResultView'

function isoInDays(days: number) {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

const EMPTY: FormValue = {
  cropCode: '0110020',
  harvestOn: isoInDays(14),
  rows: [{ product: '', applied_on: '' }],
  csvText: '',
  mode: 'rows',
}

// Seeded spray records (invented) checked against real regulatory data.
const EXAMPLE: FormValue = {
  cropCode: '0110020',
  harvestOn: '2026-10-01',
  rows: [
    { product: 'ACTARA 25 WG', applied_on: '2026-08-15' },
    { product: 'AKTARA 25 WG', applied_on: '2026-08-20' },
    { product: 'ADMIRAL 10 EC', applied_on: '2026-09-10' },
  ],
  csvText: '',
  mode: 'rows',
}

export default function App() {
  const [crops, setCrops] = useState<Crop[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [form, setForm] = useState<FormValue>(EMPTY)
  const [result, setResult] = useState<CheckResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isExample, setIsExample] = useState(false)

  useEffect(() => {
    api.crops().then(setCrops).catch((e) => setError(`Cannot reach the API: ${e.message}`))
    api.health().then(setHealth).catch(() => undefined)
  }, [])

  const run = async (value: FormValue) => {
    setBusy(true)
    setError(null)
    try {
      const r =
        value.mode === 'csv'
          ? await api.checkCsv({ crop_code: value.cropCode, harvest_on: value.harvestOn, csv_text: value.csvText })
          : await api.check({
              crop_code: value.cropCode,
              harvest_on: value.harvestOn,
              applications: value.rows.filter((r) => r.product.trim() && r.applied_on),
            })
      setResult(r)
    } catch (e) {
      setResult(null)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const useSuggestion = (from: string, to: string) => {
    const next = { ...form, mode: 'rows' as const, rows: form.rows.map((r) => (r.product === from ? { ...r, product: to } : r)) }
    setForm(next)
    run(next)
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={32} height={32} />
          <div>
            <h1>ResidueCheck</h1>
            <p className="tagline">Check a spray log against EU residue limits before harvest.</p>
          </div>
        </div>
        {health && (
          <span className="engine-badge" title={health.engine.note}>
            Preview · rules only, no AI model yet
          </span>
        )}
      </header>

      <main className="layout">
        <CheckForm
          crops={crops}
          value={form}
          onChange={(v) => {
            setForm(v)
            setIsExample(false)
          }}
          onSubmit={() => run(form)}
          onLoadExample={() => {
            setForm(EXAMPLE)
            setIsExample(true)
            run(EXAMPLE)
          }}
          busy={busy}
        />

        <div className="right">
          {error && (
            <div className="panel error" role="alert">
              {error}
            </div>
          )}
          {isExample && result && <div className="seeded-note">Example spray records are invented; the rules and data they are checked against are real.</div>}
          {result ? (
            <ResultView result={result} onUseSuggestion={useSuggestion} />
          ) : (
            !error && (
              <div className="panel empty">
                <h2>What this does</h2>
                <ol>
                  <li>Finds each product in Morocco's official ONSSA index: active substances, crops it is registered for, days to wait before harvest.</li>
                  <li>Checks every substance against the EU maximum residue limit in force when the lot arrives, including recent and upcoming changes.</li>
                  <li>Tells you whether the lot is safe to ship, what blocks it, and the earliest safe harvest date, with the regulation linked.</li>
                </ol>
                <p className="muted">It never guesses: a product it cannot find is marked “cannot verify”.</p>
              </div>
            )
          )}
        </div>
      </main>

      <footer className="foot">
        {health ? (
          <span>
            EU Pesticides Database snapshot {health.eu_snapshot} · ONSSA index ({health.onssa_products} products) updated {health.onssa_index_updated} · {health.crops} crops
          </span>
        ) : (
          <span>Connecting…</span>
        )}
        <span>Decision support, not a lab test. Residue levels are not predicted.</span>
      </footer>
    </div>
  )
}
