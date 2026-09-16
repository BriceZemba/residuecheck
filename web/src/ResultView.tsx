import type { CheckResult, Finding, Level, ResolvedApplication } from './api'

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

function fmtDate(iso: string | null) {
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
    if (u.hostname.includes('onssa')) return 'ONSSA index'
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

function ProductCard({ a, onUseSuggestion }: { a: ResolvedApplication; onUseSuggestion: (from: string, to: string) => void }) {
  return (
    <li className={`product ${a.status}`}>
      <div className="product-top">
        <div>
          <div className="product-name">{a.trade_name ?? a.input}</div>
          <div className="muted small">sprayed {fmtDate(a.applied_on)}</div>
        </div>
        <span className={`chip ${a.status === 'found' ? 'chip-ok' : 'chip-warn'}`}>
          {a.status === 'found' ? 'Found in ONSSA' : a.status === 'not_cached' ? 'Not loaded yet' : 'Not found'}
        </span>
      </div>
      {a.status === 'found' ? (
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
            {a.registration ? REGISTRATION_LABEL[a.registration] ?? a.registration : '—'}
            {a.matched_usages?.length ? <span className="muted"> (label: {a.matched_usages.join(', ')})</span> : null}
          </dd>
          <dt>Days before harvest</dt>
          <dd>{a.dar_days ?? '—'}</dd>
        </dl>
      ) : (
        <p className="small">
          {a.status === 'not_found'
            ? 'No product with this exact name in the ONSSA index. Nothing is guessed.'
            : 'This product exists in the index but its details are not loaded in this preview.'}
          {a.suggestions.length > 0 && (
            <>
              {' '}Did you mean{' '}
              {a.suggestions.map((s, i) => (
                <span key={s}>
                  {i > 0 ? ' or ' : ''}
                  <button type="button" className="linklike" onClick={() => onUseSuggestion(a.input, s)}>
                    {s}
                  </button>
                </span>
              ))}
              ?
            </>
          )}
        </p>
      )}
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
  return (
    <section className="result" aria-live="polite">
      <div className={`verdict v-${result.verdict}`}>
        <div className="verdict-label">{VERDICT_LABEL[result.verdict]}</div>
        <p className="verdict-headline">{result.headline}</p>
        <div className="verdict-meta">
          <span>{result.crop.name}</span>
          <span>harvest {fmtDate(result.harvest_on)}</span>
          <span>EU arrival {fmtDate(result.arrival_on)}</span>
        </div>
        {result.earliest_safe_harvest && (
          <div className="pill">Earliest safe harvest: {fmtDate(result.earliest_safe_harvest)}</div>
        )}
      </div>

      {result.csv_errors && result.csv_errors.length > 0 && (
        <div className="panel notice">Some CSV lines were skipped: {result.csv_errors.join('; ')}</div>
      )}

      <div className="panel">
        <h3>Products</h3>
        <ul className="products">
          {result.applications.map((a, i) => (
            <ProductCard key={`${a.input}-${i}`} a={a} onUseSuggestion={onUseSuggestion} />
          ))}
        </ul>
      </div>

      <div className="panel">
        <h3>
          Findings <span className="muted small">({blocking.length} to act on)</span>
        </h3>
        {blocking.length === 0 ? <p className="muted">Nothing to act on.</p> : <ul className="findings">{blocking.map((f, i) => <FindingItem key={i} f={f} />)}</ul>}
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
          Data: EU Pesticides Database snapshot {fmtDate(result.data.eu_snapshot)} · ONSSA index updated {result.data.onssa_index_updated ?? 'unknown'}.
        </p>
      </div>
    </section>
  )
}
