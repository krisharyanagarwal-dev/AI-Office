import type { RiskAlert } from '@/types'

const alertTitles: Record<string, string> = {
  EXPENSIVE_HIGH_LEVERAGE: 'Expensive valuation with high leverage',
  TIGHT_LIQUIDITY: 'Tight liquidity',
  REGIME_CHANGE_TO_EXPENSIVE: 'Valuation regime changed to expensive',
  UNEXPECTED_NA: 'Metric became unavailable',
}

export function alertTitle(alert: RiskAlert): string {
  return alertTitles[alert.rule] ?? alert.rule
}

export function alertId(alert: RiskAlert, index: number): string {
  return `${alert.rule}-${alert.symbol}-${alert.kind}-${index}-${alert.sourceAnalyzedAt ?? alert.detectedAt}`
}

export function describeAlert(alert: RiskAlert): string {
  const details = Object.entries(alert.details)
    .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${value}`)
    .join(', ')
  const basis = alert.kind === 'active_condition'
    ? 'Active condition in published fundamentals.'
    : 'Flag transition against the previous alert state.'
  return details ? `${details}. ${basis}` : basis
}
