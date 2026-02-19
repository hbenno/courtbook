import { format, parse } from 'date-fns'

/** Format pence as £X.XX */
export function formatPence(pence: number): string {
  return `£${(pence / 100).toFixed(2)}`
}

/** Format "YYYY-MM-DD" as "Mon 19 Feb 2026" */
export function formatDate(dateStr: string): string {
  const d = parse(dateStr, 'yyyy-MM-dd', new Date())
  return format(d, 'EEE d MMM yyyy')
}

/** Format "HH:MM:SS" to "HH:MM" for display */
export function formatTime(timeStr: string): string {
  return timeStr.slice(0, 5)
}

/** Format "09:00" – "10:00" range */
export function formatTimeRange(start: string, end: string): string {
  return `${formatTime(start)} – ${formatTime(end)}`
}

/** Day of week number (0=Mon) to name */
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
export function dayName(dow: number): string {
  return DAYS[dow] ?? `Day ${dow}`
}
