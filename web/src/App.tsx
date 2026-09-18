import { useEffect, useRef, useState } from 'react'
import { api, type CheckResult, type Crop, type EngineInfo, type Health, type Scenario } from './api'
import { CheckForm, type FormValue } from './CheckForm'
import { Guide, VerdictLegend } from './Guide'
import { PHOTOS } from './photos'
import { ResultView } from './ResultView'
import { useReveal } from './useReveal'

function isoInDays(days: number) {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

const EMPTY: FormValue = {
  cropCode: '0110020',
  harvestOn: isoInDays(21),
  rows: [{ product: '', applied_on: '' }],
  csvText: '',
  mode: 'rows',
}

const BADGE: Record<EngineInfo['mode'], string> = {
  live: 'Live AI · Nemotron + Tavily',
  replay: 'Recorded AI runs · no keys',
  rules: 'Fixed rules · no AI model',
}

function fromScenario(s: Scenario): FormValue {
  return {
    cropCode: s.request.crop_code,
    harvestOn: s.request.harvest_on,
    rows: s.request.applications.map((a) => ({ ...a })),
    csvText: '',
    mode: 'rows',
    today: s.request.today,
  }
}

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="18" fill="var(--citrus)" />
      <circle cx="20" cy="20" r="13.5" fill="var(--citrus-pale)" />
      {Array.from({ length: 8 }, (_, i) => (
        <line key={i} x1="20" y1="20" x2={20 + 13 * Math.cos((i * Math.PI) / 4)} y2={20 + 13 * Math.sin((i * Math.PI) / 4)} stroke="var(--citrus)" strokeWidth="1.6" />
      ))}
      <path d="M13.5 20.5l4.2 4.2 8.8-9.4" fill="none" stroke="var(--orchard)" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

const STEPS = [
  {
    photo: PHOTOS.tree,
    title: 'Pick the crop and the harvest date',
    text: 'The EU limit that counts is the one in force when your fruit arrives. We add the usual 10 days of transport.',
  },
  {
    photo: PHOTOS.spraying,
    title: 'List what you sprayed',
    text: 'Trade names and dates, straight from your spray notebook. Misspelled names are suggested, never guessed.',
  },
  {
    photo: PHOTOS.clementines,
    title: 'Get a verdict you can act on',
    text: 'Safe to ship or not, why, the earliest safe harvest date, safer products for the next spray, and the regulation behind each point.',
  },
]

export default function App() {
  const [crops, setCrops] = useState<Crop[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [form, setForm] = useState<FormValue>(EMPTY)
  const [result, setResult] = useState<CheckResult | null>(null)
  const [runId, setRunId] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isExample, setIsExample] = useState(false)
  const resultRef = useRef<HTMLDivElement>(null)
  useReveal()

  useEffect(() => {
    api.crops().then(setCrops).catch((e) => setError(`Cannot reach the service: ${e.message}`))
    api.health().then(setHealth).catch(() => undefined)
    api.scenarios().then(setScenarios).catch(() => undefined)
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
              today: value.today,
              applications: value.rows.filter((r) => r.product.trim() && r.applied_on),
            })
      setResult(r)
      setRunId((n) => n + 1)
      if (window.matchMedia('(max-width: 960px)').matches) {
        requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
      }
    } catch (e) {
      setResult(null)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const loadScenario = (s: Scenario) => {
    const next = fromScenario(s)
    setForm(next)
    setIsExample(true)
    document.getElementById('check')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    run(next)
  }

  // Shareable demo links: /?demo=<scenario id> opens that demo lot and runs it.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('demo')
    const s = id && scenarios.find((x) => x.id === id)
    if (s) loadScenario(s)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarios])

  const useSuggestion = (from: string, to: string) => {
    const next = { ...form, mode: 'rows' as const, today: undefined, rows: form.rows.map((r) => (r.product === from ? { ...r, product: to } : r)) }
    setForm(next)
    run(next)
  }

  return (
    <>
      <header className="nav">
        <a className="brand" href="#top">
          <Logo />
          <span>ResidueCheck</span>
        </a>
        <nav aria-label="Sections">
          <a href="#how">How it works</a>
          <a href="#check">Check a lot</a>
          <a href="#guide">Guide</a>
        </nav>
        {health && (
          <span className={`engine mode-${health.engine.mode}`} title={health.engine.note}>
            <i aria-hidden="true" />
            {BADGE[health.engine.mode]}
          </span>
        )}
      </header>

      <section className="hero" id="top">
        <img className="hero-photo" src={PHOTOS.harvest.src} alt={PHOTOS.harvest.alt} fetchPriority="high" />
        <div className="hero-shade" />
        <div className="hero-inner">
          <p className="eyebrow">For growers and exporters · Morocco → European Union</p>
          <h1>
            Will this harvest pass <em>the EU border?</em>
          </h1>
          <p className="lead">
            Enter what you sprayed. ResidueCheck checks each product against Morocco's official register and the EU residue limit that
            will apply when your fruit arrives, then tells you what to do before you pick.
          </p>
          <div className="hero-cta">
            <a className="btn primary big" href="#check">
              Check my lot
            </a>
            {scenarios[0] && (
              <button type="button" className="btn glass big" onClick={() => loadScenario(scenarios[0])}>
                See a demo lot
              </button>
            )}
          </div>
          <dl className="hero-stats">
            <div>
              <dt>{health?.crops ?? 32}</dt>
              <dd>export crops</dd>
            </div>
            <div>
              <dt>{health ? health.onssa_products.toLocaleString('en') : '1,400+'}</dt>
              <dd>products in Morocco's ONSSA register</dd>
            </div>
            <div>
              <dt>{health ? new Date(health.eu_snapshot + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '—'}</dt>
              <dd>EU Pesticides Database copy</dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="how" id="how">
        <div className="section-head reveal">
          <p className="eyebrow dark">How it works</p>
          <h2>Three steps, about a minute</h2>
          <p>
            A lot is rejected at the EU border when a residue is above the legal limit. Many limits have dropped to the lowest level a lab can
            detect, so a spray that was fine last season can block this one.
          </p>
        </div>
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s.title} className="step reveal" style={{ transitionDelay: `${i * 90}ms` }}>
              <div className="step-photo">
                <img src={s.photo.src} alt={s.photo.alt} loading="lazy" />
                <span className="step-num">{i + 1}</span>
              </div>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="checker" id="check">
        <div className="section-head reveal">
          <p className="eyebrow dark">Check a lot</p>
          <h2>Your spray log against EU limits</h2>
        </div>
        <div className="checker-grid">
          <CheckForm
            crops={crops}
            value={form}
            onChange={(v) => {
              setForm(v)
              setIsExample(false)
            }}
            onSubmit={() => run(form)}
            scenarios={scenarios}
            replay={health?.engine.mode === 'replay'}
            onLoadScenario={loadScenario}
            busy={busy}
          />

          <div className="result-col" ref={resultRef} aria-live="polite">
            {error && (
              <div className="card error" role="alert">
                <strong>Something went wrong.</strong> {error}
              </div>
            )}
            {busy && (
              <div className="card checking">
                <span className="spinner" aria-hidden="true" />
                Checking the register and the EU limits…
              </div>
            )}
            {isExample && result && !busy && (
              <p className="demo-note">Demo lot: the spray records are invented; the register and EU limits they are checked against are real.</p>
            )}
            {result && !busy ? (
              <ResultView key={runId} result={result} onUseSuggestion={useSuggestion} />
            ) : (
              !error &&
              !busy && (
                <div className="card empty">
                  <img src={PHOTOS.tree.src} alt="" loading="lazy" />
                  <div className="empty-body">
                    <h3>Your verdict appears here</h3>
                    <p>Fill in the two steps on the left, or try a demo lot. Each lot gets one of four verdicts:</p>
                    <VerdictLegend compact />
                  </div>
                </div>
              )
            )}
          </div>
        </div>
      </section>

      <Guide />

      <footer className="foot">
        <div className="foot-grid">
          <div>
            <a className="brand" href="#top">
              <Logo />
              <span>ResidueCheck</span>
            </a>
            <p>Decision support for export compliance, not a lab test. Verdicts come from fixed rules applied to official data, each with its source.</p>
            {health && <p className="muted small">{health.engine.note}</p>}
          </div>
          <div>
            <h4>Data</h4>
            <ul>
              <li>
                <a href="https://food.ec.europa.eu/plants/pesticides/eu-pesticides-database_en" target="_blank" rel="noreferrer">
                  EU Pesticides Database
                </a>
                {health && <span className="muted"> · copy of {health.eu_snapshot}</span>}
              </li>
              <li>
                <a href="https://eservice.onssa.gov.ma/IndPesticide.aspx" target="_blank" rel="noreferrer">
                  ONSSA register of pesticides (Morocco)
                </a>
                {health?.onssa_index_updated && <span className="muted"> · updated {health.onssa_index_updated.slice(0, 10)}</span>}
              </li>
              <li>
                <a href="https://github.com/BriceZemba/residuecheck" target="_blank" rel="noreferrer">
                  Source code and evaluation
                </a>
              </li>
            </ul>
          </div>
          <div>
            <h4>Photos</h4>
            <ul className="credits">
              {Object.values(PHOTOS).map((p) => (
                <li key={p.page}>
                  <a href={p.page} target="_blank" rel="noreferrer">
                    {p.alt.split(',')[0]}
                  </a>{' '}
                  · {p.author} ·{' '}
                  <a href={p.licenseUrl} target="_blank" rel="noreferrer">
                    {p.license}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </footer>
    </>
  )
}
