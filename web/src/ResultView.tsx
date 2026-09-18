import type { Alternatives, CheckResult, Finding, Level, ResolvedApplication, Resolution } from './api'
import { Timeline } from './Timeline'

const VERDICT_LABEL: Record<CheckResult['verdict'], string> = {
  RED: 'Not safe to ship',
  CANNOT_VERIFY: 'Cannot verify',
  AMBER: 'Check before shipping',
  GREEN: 'No red flags',
}

const LEVEL_LABEL: Record<Level, string> = {
  RED: 'Blocking',
  CANNOT_VERIFY: 'Cannot verify',
  AMBER: 'Warning',
  GREEN: 'OK',
  INFO: 'Checked',
}

const REGISTRATION_LABEL: Record<string, string> = {
  registered: 'Registered for this crop',
  registered_narrower: 'Registered for a narrower crop name',
  not_registered: 'Not registered for this crop',
  ambiguous: 'Crop name on the label is ambiguous',
  unknown: 'Registration unknown',
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function sourceLabel(url: string) {
  try {
    const u = new URL(url)
    if (u.hostname.includes('eur-lex') || u.hostname.includes('data.europa.eu')) {
      const m = url.match(/reg\/(\d{4})\/(\d+)/) || url.match(/3(\d{4})R0*(\d+)/)
      return m ? `EU Reg. ${m[1]}/${m[2]}` : 'EUR-Lex'
    }
    if (u.hostname.includes('ec.europa.eu')) return 'EU Pesticides Database'
    if (u.hostname.includes('onssa')) return 'ONSSA register'
    return u.hostname
  } catch {
    return url
  }
}

function Sources({ urls }: { urls: string[] }) {
  if (!urls.length) return null
  return (
    <span className="sources">
      {urls.map((u) => (
        <a key={u} href={u} target="_blank" rel="noreferrer">
          {sourceLabel(u)}
        </a>
      ))}
    </span>
  )
}

interface Step {
  level: Level
  text: string
}

/** Plain-language actions, one per problem, most serious first. */
function nextSteps(result: CheckResult): Step[] {
  const out: Step[] = []
  const seen = new Set<string>()
  const blocked = new Set(result.findings.filter((f) => f.code === 'MRL_AT_LOQ' || f.code === 'MRL_DEFAULT').map((f) => f.substance))
  const planned = new Set(result.applications.filter((a) => a.alternatives?.context === 'planned').map((a) => a.trade_name ?? a.input))
  const add = (key: string, level: Level, text: string) => {
    if (!seen.has(key)) {
      seen.add(key)
      out.push({ level, text })
    }
  }
  for (const f of result.findings) {
    const p = f.product ?? 'this product'
    const s = f.substance ?? 'its active substance'
    switch (f.code) {
      case 'MRL_AT_LOQ':
      case 'MRL_DEFAULT':
        add(
          `loq-${p}`,
          'RED',
          planned.has(p)
            ? `Do not spray ${p}: the EU limit for ${s} on this crop is at the detection level, so any trace would fail. Use one of the safer products listed under it.`
            : `${p}: the EU limit for ${s} on this crop is at the detection level, so any trace fails. Do not ship to the EU without a residue test from an accredited lab, and use a safer product for the next spray (listed under it).`,
        )
        break
      case 'NOT_REGISTERED_FOR_CROP':
        add(`reg-${p}`, 'RED', `${p} is not registered in Morocco for this crop. Stop using it on this crop; the safer options below are registered for it.`)
        break
      case 'PHI_NOT_MET':
        add('phi', 'RED', `Wait before harvesting: pick on or after ${fmtDate(result.earliest_safe_harvest)}, when the waiting time after the last spray is over.`)
        break
      case 'PRODUCT_UNRESOLVED':
        add(`name-${p}`, 'CANNOT_VERIFY', `"${p}" is not a name in the ONSSA register. Tap the right name under the product, or check the spelling on the label.`)
        break
      case 'MRL_RECENTLY_LOWERED':
      case 'MRL_LOWERING_SOON':
        if (blocked.has(s)) break // already covered by the red step for this substance
        add(`chg-${s}`, 'AMBER', `The EU limit for ${s} has changed recently or changes before your fruit arrives. Read the warning below and keep doses at label rates.`)
        break
      case 'NOT_APPROVED_IMPORT_TOLERANCE':
        add(`it-${s}`, 'AMBER', `${s} is allowed only through an EU import tolerance. Legal, but keep the spray record ready for your buyer.`)
        break
      default:
        if (f.level === 'CANNOT_VERIFY') add(`cv-${f.code}-${p}`, 'CANNOT_VERIFY', f.message)
    }
  }
  const order: Level[] = ['RED', 'CANNOT_VERIFY', 'AMBER', 'GREEN', 'INFO']
  out.sort((a, b) => order.indexOf(a.level) - order.indexOf(b.level))
  if (!out.length) out.push({ level: 'GREEN', text: 'Nothing to fix. Keep this spray log with the lot; buyers and inspectors may ask for it.' })
  return out
}

function HowRead({ r }: { r: Resolution }) {
  if (r.method === 'exact') return null
  return (
    <div className="how-read">
      {r.method === 'agent' ? (
        <>
          <span className="tag ai">{r.replayed ? 'AI reading · recorded run' : 'AI reading'}</span> <span className="small">{r.reason}</span>
          {r.evidence && r.evidence.length > 0 && (
            <div className="small">
              Evidence:{' '}
              {r.evidence.map((e) => (
                <a key={e.url} href={e.url} target="_blank" rel="noreferrer" title={e.excerpt}>
                  {sourceLabel(e.url)}
                </a>
              ))}
            </div>
          )}
          {r.rejected && r.rejected.length > 0 && <div className="small muted">Refused by the checks: {r.rejected.join('; ')}</div>}
          {r.tools_used && r.tools_used.length > 0 && <div className="small muted">Tools used: {r.tools_used.join(', ')}</div>}
        </>
      ) : null}
      {r.note && <div className="small warn-text">{r.note}</div>}
    </div>
  )
}

function SaferOptions({ alt }: { alt: Alternatives }) {
  return (
    <div className={`safer ${alt.context}`}>
      <div className="safer-head">
        <span>{alt.context === 'planned' ? 'Use one of these instead' : 'For the next spray against the same pest'}</span>
        {alt.method === 'agent' && <span className="tag ai">{alt.replayed ? 'AI proposals · recorded run' : 'AI proposals'}, checked by rules</span>}
      </div>
      <p className="small">{alt.note}</p>
      {alt.fallback_note && <p className="small warn-text">{alt.fallback_note}</p>}
      {alt.options.length === 0 ? (
        <p className="small muted">No registered product passes the rules for this lot and date. {alt.reason}.</p>
      ) : (
        <ul className="options">
          {alt.options.map((o, i) => (
            <li key={o.product} style={{ animationDelay: `${300 + i * 80}ms` }}>
              <div className="option-top">
                <strong>{o.product}</strong>
                <span className="tag ok">passes EU rules</span>
              </div>
              <div className="small">
                {o.substances.join(' + ')} · wait {o.dar_days} days before harvest · spray by {fmtDate(o.latest_spray)}
              </div>
              <div className="small muted">Registered in Morocco against {o.pests.join(', ')}</div>
            </li>
          ))}
        </ul>
      )}
      {alt.options.length > 0 && <p className="small muted">{alt.reason}. Confirm the dose and the label before use.</p>}
      {alt.rejected.length > 0 && (
        <details className="small">
          <summary>{alt.rejected.length} AI proposal(s) refused by the checks</summary>
          <ul>
            {alt.rejected.map((r, i) => (
              <li key={i}>
                {r.product ?? 'unnamed'}: {r.why}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function ProductCard({ a, i, onUseSuggestion }: { a: ResolvedApplication; i: number; onUseSuggestion: (from: string, to: string) => void }) {
  const found = a.status === 'found'
  return (
    <li className={`product ${a.status}`} style={{ animationDelay: `${150 + i * 70}ms` }}>
      <div className="product-top">
        <div>
          <div className="product-name">{a.trade_name ?? a.input}</div>
          <div className="muted small">sprayed {fmtDate(a.applied_on)}</div>
        </div>
        <span className={`tag ${found ? 'ok' : 'warn'}`}>{found ? 'In the ONSSA register' : a.status === 'not_cached' ? 'Not loaded yet' : 'Name not found'}</span>
      </div>
      {found ? (
        <dl className="facts">
          <dt>Active substances</dt>
          <dd>
            {a.substances.map((s) => (
              <span key={s.name} className="subst">
                {s.name} <span className="muted">{s.content}</span>
                {s.eu_name && s.eu_name.toLowerCase() !== s.name.toLowerCase() ? <span className="muted"> · EU: {s.eu_name}</span> : null}
                {!s.eu_name ? <span className="warn-text"> · no EU name match</span> : null}
              </span>
            ))}
          </dd>
          <dt>Registration</dt>
          <dd>
            {a.registration ? (REGISTRATION_LABEL[a.registration] ?? a.registration) : '—'}
            {a.matched_usages?.length ? <span className="muted"> (label: {a.matched_usages.join(', ')})</span> : null}
          </dd>
          <dt>Wait before harvest</dt>
          <dd>{a.dar_days != null ? `${a.dar_days} days` : '—'}</dd>
        </dl>
      ) : (
        <div className="suggest">
          <p className="small">
            {a.status === 'not_found'
              ? 'No product with this exact name in the ONSSA register, so nothing is guessed.'
              : 'This product is in the register but its details are not loaded in this demo.'}
          </p>
          {a.suggestions.length > 0 && (
            <div className="suggest-list">
              <span className="small muted">Did you mean</span>
              {a.suggestions.map((s) => (
                <button key={s} type="button" className="chip" onClick={() => onUseSuggestion(a.input, s)}>
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {a.resolution && <HowRead r={a.resolution} />}
      {a.alternatives && <SaferOptions alt={a.alternatives} />}
    </li>
  )
}

function FindingItem({ f }: { f: Finding }) {
  return (
    <li className={`finding lvl-${f.level}`}>
      <div className="finding-top">
        <span className={`badge lvl-${f.level}`}>{LEVEL_LABEL[f.level]}</span>
        {f.product ? <span className="muted small">{f.product}</span> : null}
      </div>
      <p>{f.message}</p>
      <Sources urls={f.sources} />
    </li>
  )
}

export function ResultView({ result, onUseSuggestion }: { result: CheckResult; onUseSuggestion: (from: string, to: string) => void }) {
  const blocking = result.findings.filter((f) => f.level !== 'INFO')
  const checked = result.findings.filter((f) => f.level === 'INFO')
  const steps = nextSteps(result)
  return (
    <section className="result">
      <div className={`verdict v-${result.verdict}`}>
        <div className="stamp" aria-hidden="true">
          <span>{VERDICT_LABEL[result.verdict]}</span>
        </div>
        <h3 className="verdict-label">{VERDICT_LABEL[result.verdict]}</h3>
        <p className="verdict-headline">{result.headline}</p>
        <div className="verdict-meta">
          <span>{result.crop.name}</span>
          <span>harvest {fmtDate(result.harvest_on)}</span>
          <span>EU arrival {fmtDate(result.arrival_on)}</span>
        </div>
        {result.earliest_safe_harvest && <div className="pill">Earliest safe harvest: {fmtDate(result.earliest_safe_harvest)}</div>}
      </div>

      <div className="card next">
        <h4>What to do</h4>
        <ol>
          {steps.map((s, i) => (
            <li key={i} className={`lvl-${s.level}`} style={{ animationDelay: `${250 + i * 90}ms` }}>
              {s.text}
            </li>
          ))}
        </ol>
      </div>

      <Timeline result={result} />

      <div className="card">
        <h4>Products</h4>
        <ul className="products">
          {result.applications.map((a, i) => (
            <ProductCard key={`${a.input}-${i}`} a={a} i={i} onUseSuggestion={onUseSuggestion} />
          ))}
        </ul>
      </div>

      <div className="card">
        <h4>
          Findings <span className="muted small">({blocking.length} to act on)</span>
        </h4>
        {blocking.length === 0 ? (
          <p className="muted">Nothing to act on.</p>
        ) : (
          <ul className="findings">
            {blocking.map((f, i) => (
              <FindingItem key={i} f={f} />
            ))}
          </ul>
        )}
        {checked.length > 0 && (
          <details className="checked">
            <summary>What was checked ({checked.length})</summary>
            <ul className="findings">
              {checked.map((f, i) => (
                <FindingItem key={i} f={f} />
              ))}
            </ul>
          </details>
        )}
      </div>

      <div className="fineprint">
        <p>
          <strong>Engine:</strong> {result.engine.name}. {result.engine.note}
        </p>
        <ul>
          {result.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
        <p>
          Data: EU Pesticides Database copy of {fmtDate(result.data.eu_snapshot)} · ONSSA register updated {result.data.onssa_index_updated ?? 'unknown'}.
        </p>
      </div>
    </section>
  )
}
