/**
 * Date/time utilities for consistent timestamp handling.
 */

export function utcNow(): Date {
  return new Date();
}

export function isoNow(): string {
  return new Date().toISOString();
}

export function parseISODateTime(value: string): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(date: Date, format: string = 'YYYY-MM-DD HH:mm:ss UTC'): string {
  const pad = (n: number) => n.toString().padStart(2, '0');
  
  return format
    .replace('YYYY', date.getUTCFullYear().toString())
    .replace('MM', pad(date.getUTCMonth() + 1))
    .replace('DD', pad(date.getUTCDate()))
    .replace('HH', pad(date.getUTCHours()))
    .replace('mm', pad(date.getUTCMinutes()))
    .replace('ss', pad(date.getUTCSeconds()));
}

export function toTimestamp(date: Date): number {
  return date.getTime();
}

export function fromTimestamp(timestamp: number): Date {
  return new Date(timestamp);
}

export function isExpired(date: Date, ttlSeconds: number): boolean {
  return (utcNow().getTime() - date.getTime()) / 1000 > ttlSeconds;
}

export function timeUntil(date: Date): number | null {
  const diff = (date.getTime() - utcNow().getTime()) / 1000;
  return diff > 0 ? diff : null;
}

export function parseDuration(text: string): number | null {
  // Parse strings like "1h30m", "5m", "2h", "30s"
  const pattern = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/i;
  const match = text.trim().toLowerCase().match(pattern);
  
  if (!match) return null;
  
  const hours = parseInt(match[1] || '0', 10);
  const minutes = parseInt(match[2] || '0', 10);
  const seconds = parseInt(match[3] || '0', 10);
  
  if (hours === 0 && minutes === 0 && seconds === 0) return null;
  
  return hours * 3600 + minutes * 60 + seconds;
}

export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  
  const parts: string[] = [];
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (secs || parts.length === 0) parts.push(`${secs}s`);
  
  return parts.join('');
}