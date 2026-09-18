export type Level = 'RED' | 'CANNOT_VERIFY' | 'AMBER' | 'GREEN' | 'INFO'

export interface Crop {
  code: string
  name: string
  name_fr: string | null
}

export interface EngineInfo {
  name: string
  mode: 'live' | 'replay' | 'rules'
  model: string | null
  note: string
  search?: string | null
  recordings?: { session: string; recorded_at: string; model: string | null; scenarios: string[] }[]
}

export interface Resolution {
  method: 'exact' | 'rules' | 'agent'
  status: string
  reason: string
  note?: string
  replayed?: boolean
  evidence?: { url: string; excerpt: string }[]
  rejected?: string[]
  tools_used?: string[]
  model_calls?: number
  cost_usd?: number
}

export interface Scenario {
  id: string
  title: string
  blurb: string
  recorded: boolean
  request: { crop_code: string; harvest_on: string; today: string; applications: SprayRow[] }
}

export interface Health {
  status: string
  engine: EngineInfo
  eu_snapshot: string
  onssa_index_updated: string | null
  onssa_products: number
  crops: number
}

export interface Finding {
  level: Level
  code: string
  message: string
  product: string | null
  substance: string | null
  sources: string[]
}

export interface SaferOption {
  product: string
  substances: string[]
  pests: string[]
  dar_days: number | null
  spray_on: string | null
  latest_spray: string | null
  why: string
  source: string | null
}

export interface Alternatives {
  method: 'agent' | 'rules'
  replayed: boolean
  fallback_note: string | null
  rejected: { product: string | null; why: string | null }[]
  context: 'planned' | 'applied'
  note: string
  not_before: string
  status: string
  reason: string
  options: SaferOption[]
}

export interface ResolvedApplication {
  input: string
  applied_on: string
  status: 'found' | 'not_found' | 'not_cached'
  suggestions: string[]
  trade_name: string | null
  registration_no?: string | null
  substances: { name: string; content: string; eu_name: string | null }[]
  registration: string | null
  registration_note?: string | null
  matched_usages?: string[]
  dar_days: number | null
  source: string | null
  alternatives?: Alternatives | null
  resolution: Resolution
}

export interface CheckResult {
  verdict: Exclude<Level, 'INFO'>
  headline: string
  earliest_safe_harvest: string | null
  crop: { code: string; name: string }
  harvest_on: string
  arrival_on: string
  today: string
  applications: ResolvedApplication[]
  findings: Finding[]
  counts: Record<Level, number>
  assumptions: string[]
  engine: EngineInfo
  data: { eu_snapshot: string; onssa_index_updated: string | null }
  csv_errors?: string[]
}

export interface SprayRow {
  product: string
  applied_on: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail))
        // FastAPI validation errors: [{loc: [..., field], msg}]
        detail = body.detail.map((d: { loc?: unknown[]; msg?: string }) => `${String(d.loc?.at(-1) ?? 'input')}: ${d.msg}`).join('; ')
      else if (body.detail?.message) detail = [body.detail.message, ...(body.detail.errors ?? [])].join(' — ')
      else detail = JSON.stringify(body.detail)
    } catch {
      /* keep the status text */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<Health>('/api/health'),
  crops: () => request<Crop[]>('/api/crops'),
  products: (q: string) => request<{ products: string[] }>(`/api/products?q=${encodeURIComponent(q)}&limit=12`),
  scenarios: () => request<Scenario[]>('/api/scenarios'),
  check: (body: { crop_code: string; harvest_on: string; today?: string; applications: SprayRow[] }) =>
    request<CheckResult>('/api/check', { method: 'POST', body: JSON.stringify(body) }),
  checkCsv: (body: { crop_code: string; harvest_on: string; csv_text: string }) =>
    request<CheckResult>('/api/check/csv', { method: 'POST', body: JSON.stringify(body) }),
}
