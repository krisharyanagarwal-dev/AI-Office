export function currencySymbol(currency: string): string {
  return currency === 'INR' ? '₹' : '$'
}

export function formatMoney(value: number | null, currency: string, showSign = false): string {
  if (value === null) return 'Unavailable'
  const sign = showSign && value > 0 ? '+' : ''
  return `${sign}${currencySymbol(currency)}${value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export function formatNumber(value: number | null, maximumFractionDigits = 2): string {
  if (value === null) return 'Unavailable'
  return value.toLocaleString('en-US', { maximumFractionDigits })
}

export function formatPercent(value: number | null, showSign = false): string {
  if (value === null) return 'Unavailable'
  const sign = showSign && value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

export function formatDateTime(value: string | null): string {
  if (!value) return 'Unavailable'
  return new Date(value).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatAge(minutes: number | null): string {
  if (minutes === null) return 'unknown age'
  if (minutes < 60) return `${minutes}m old`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h old`
  return `${Math.floor(hours / 24)}d old`
}

export function formatSeconds(seconds: number | null): string {
  if (seconds === null) return 'Unavailable'
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}
