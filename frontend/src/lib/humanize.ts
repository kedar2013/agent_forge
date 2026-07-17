const ACRONYMS: Record<string, string> = {
  pdf: 'PDF',
  sec: 'SEC',
  sip: 'SIP',
  nav: 'NAV',
  eps: 'EPS',
  esg: 'ESG',
  usd: 'USD',
  inr: 'INR',
}

/** snake_case tool/agent name -> readable label, e.g. "get_crypto_price"
 * -> "Get crypto price", "export_to_pdf" -> "Export to PDF",
 * "analyze_fund_performance_mcp" -> "Analyze fund performance". */
export function humanizeName(raw: string): string {
  const words = raw.split('_').filter((w) => w.toLowerCase() !== 'mcp')
  return words
    .map((word, i) => {
      const acronym = ACRONYMS[word.toLowerCase()]
      if (acronym) return acronym
      return i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word
    })
    .join(' ')
}
