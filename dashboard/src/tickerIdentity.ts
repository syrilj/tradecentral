/** Expand a ticker to symbol + company name when the name is known. */

const KNOWN: Record<string, string> = {
  AAPL: 'Apple Inc.',
  MSFT: 'Microsoft Corp.',
  NVDA: 'NVIDIA Corp.',
  AMZN: 'Amazon.com Inc.',
  META: 'Meta Platforms Inc.',
  GOOGL: 'Alphabet Inc.',
  GOOG: 'Alphabet Inc.',
  TSLA: 'Tesla Inc.',
  AMD: 'Advanced Micro Devices',
  NFLX: 'Netflix Inc.',
  AVGO: 'Broadcom Inc.',
  JPM: 'JPMorgan Chase',
  XOM: 'Exxon Mobil',
  JNJ: 'Johnson & Johnson',
  UNH: 'UnitedHealth Group',
  V: 'Visa Inc.',
  MA: 'Mastercard Inc.',
  COST: 'Costco Wholesale',
  HD: 'Home Depot',
  PG: 'Procter & Gamble',
  SPY: 'SPDR S&P 500 ETF',
  QQQ: 'Invesco QQQ Trust',
  IWM: 'iShares Russell 2000',
  DIA: 'SPDR Dow Jones',
  XLE: 'Energy Select Sector SPDR',
  XLK: 'Technology Select Sector SPDR',
  XLF: 'Financial Select Sector SPDR',
  GLD: 'SPDR Gold Trust',
  TLT: 'iShares 20+ Year Treasury',
}

export function cleanTickerSymbol(raw: string): string {
  return raw.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '').slice(0, 10)
}

export function tickerCompanyName(symbol: string, known?: string | null): string | null {
  const clean = cleanTickerSymbol(symbol)
  const fromKnown = String(known ?? '').trim()
  if (fromKnown && fromKnown.toUpperCase() !== clean) return fromKnown
  return KNOWN[clean] ?? null
}

export function tickerIdentity(
  symbol: string,
  known?: string | null,
): { symbol: string; name: string | null; label: string } {
  const clean = cleanTickerSymbol(symbol) || symbol.trim().toUpperCase()
  const name = tickerCompanyName(clean, known)
  return {
    symbol: clean,
    name,
    label: name ? `${clean} · ${name}` : clean,
  }
}
