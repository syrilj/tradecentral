export type InsiderSide = 'buy' | 'sell' | 'other'

export interface InsiderRow {
  who: string
  side: InsiderSide
  typeLabel: string
  detail: string
  date: string | null
  source: 'fintel' | 'sec'
  url: string | null
}

export interface SecFilingRow {
  form: string
  filed: string
  description: string
  url: string | null
  kind: 'insider' | 'event' | 'holder' | 'other'
}

function text(value: unknown): string {
  return String(value ?? '').trim()
}

export function classifyInsiderSide(raw: unknown): InsiderSide {
  const side = text(raw).toLowerCase()
  if (!side) return 'other'
  if (side.includes('buy') || side.includes('purchase') || side === 'p' || side === 'a') return 'buy'
  if (side.includes('sell') || side.includes('sale') || side === 's' || side === 'd') return 'sell'
  return 'other'
}

export type FormBriefId = 'form4' | '8k' | '13dg' | 'other'

export interface FormBrief {
  id: FormBriefId
  form: string
  title: string
  meaning: string
}

/** Short research briefs — what each watched form pertains to. Not 13F. */
export const FORM_BRIEFS: FormBrief[] = [
  {
    id: 'form4',
    form: 'Form 4',
    title: 'Officer / director trades',
    meaning:
      'SEC Form 4 reports when officers, directors, or 10% owners buy or sell the stock. Use it as a tape of insider activity — not a 13F fund book.',
  },
  {
    id: '8k',
    form: '8-K',
    title: 'Material company events',
    meaning:
      'An 8-K is a current report of material events (earnings items, leadership, M&A, financing). It is company news, not an insider trade.',
  },
  {
    id: '13dg',
    form: '13D/G',
    title: 'Large holders',
    meaning:
      'Schedule 13D/G flags a 5%+ beneficial owner. 13D is an activist/active stake; 13G is a passive one. This is not a quarterly 13F holdings dump.',
  },
]

export function classifyFilingKind(form: unknown): SecFilingRow['kind'] {
  const key = text(form).toUpperCase()
  if (key === '4' || key === '4/A' || key.startsWith('4')) return 'insider'
  if (key.startsWith('8-K') || key === '8K') return 'event'
  if (key.includes('13D') || key.includes('13G')) return 'holder'
  return 'other'
}

export function formBrief(form: unknown): FormBrief {
  const kind = classifyFilingKind(form)
  if (kind === 'insider') return FORM_BRIEFS[0]
  if (kind === 'event') return FORM_BRIEFS[1]
  if (kind === 'holder') return FORM_BRIEFS[2]
  const raw = text(form)
  return {
    id: 'other',
    form: raw || '—',
    title: 'Other filing',
    meaning: raw ? `SEC form ${raw}. Not a watched Form 4 / 8-K / 13D/G item.` : '',
  }
}

export function presentFintelInsiders(rows: unknown): InsiderRow[] {
  if (!Array.isArray(rows)) return []
  const out: InsiderRow[] = []
  for (const raw of rows) {
    if (!raw || typeof raw !== 'object') continue
    const row = raw as Record<string, unknown>
    const who = text(row.insider_name || row.name || row.reporting_name || row.owner)
    const typeLabel = text(row.transaction_type || row.type || row.transactionType || row.transaction)
    const date = text(row.transaction_date || row.date || row.filed || row.asof) || null
    const shares = row.shares ?? row.share_count ?? row.quantity
    const price = row.price ?? row.transaction_price
    const bits = [
      shares != null && shares !== '' ? `${shares} sh` : '',
      price != null && price !== '' ? `@ ${price}` : '',
      date || '',
    ].filter(Boolean)
    out.push({
      who: who || 'Unknown insider',
      side: classifyInsiderSide(typeLabel),
      typeLabel: typeLabel || '—',
      detail: bits.join(' · ') || '—',
      date,
      source: 'fintel',
      url: text(row.url || row.link) || null,
    })
  }
  return out
}

export function presentSecFilings(payload: {
  filings?: Array<{
    form?: string
    filed?: string
    description?: string
    url?: string | null
  }>
} | null | undefined): SecFilingRow[] {
  const filings = payload?.filings
  if (!Array.isArray(filings)) return []
  return filings.map((row) => ({
    form: text(row.form) || '—',
    filed: text(row.filed),
    description: text(row.description),
    url: row.url ?? null,
    kind: classifyFilingKind(row.form),
  }))
}

export function insiderLean(rows: InsiderRow[]): {
  buys: number
  sells: number
  label: 'BUY-HEAVY' | 'SELL-HEAVY' | 'MIXED' | 'NONE'
} {
  const buys = rows.filter((row) => row.side === 'buy').length
  const sells = rows.filter((row) => row.side === 'sell').length
  if (!buys && !sells) return { buys, sells, label: 'NONE' }
  if (buys > sells) return { buys, sells, label: 'BUY-HEAVY' }
  if (sells > buys) return { buys, sells, label: 'SELL-HEAVY' }
  return { buys, sells, label: 'MIXED' }
}
