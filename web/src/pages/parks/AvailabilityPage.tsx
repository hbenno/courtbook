import { format, addDays, parse } from 'date-fns'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import { useSiteAvailability } from '../../hooks/useSiteAvailability'
import { useAuth } from '../../auth/AuthContext'
import type { CourtAvailability, Slot } from '../../types/api'

/** Collect all unique time labels across all courts. */
function allTimeSlots(courts: CourtAvailability[]): string[] {
  const set = new Set<string>()
  for (const court of courts) {
    for (const slot of court.slots) {
      set.add(slot.start_time)
    }
  }
  return [...set].sort()
}

/** Build a quick lookup: court_id → start_time → Slot */
function buildSlotMap(courts: CourtAvailability[]): Map<number, Map<string, Slot>> {
  const map = new Map<number, Map<string, Slot>>()
  for (const court of courts) {
    const inner = new Map<string, Slot>()
    for (const slot of court.slots) {
      inner.set(slot.start_time, slot)
    }
    map.set(court.court_id, inner)
  }
  return map
}

export function AvailabilityPage() {
  const { siteSlug } = useParams<{ siteSlug: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()

  const today = format(new Date(), 'yyyy-MM-dd')
  const [selectedDate, setSelectedDate] = useState(today)
  const [duration, setDuration] = useState(60)

  const { data, isLoading, error, refetch } = useSiteAvailability(siteSlug!, selectedDate)

  const dates = Array.from({ length: 7 }, (_, i) => {
    const d = addDays(new Date(), i)
    return format(d, 'yyyy-MM-dd')
  })

  function canBook(court: CourtAvailability, slotIndex: number): boolean {
    const slots = court.slots
    if (!slots[slotIndex].is_available) return false
    if (duration <= 60) return true
    return slotIndex + 1 < slots.length && slots[slotIndex + 1].is_available
  }

  function handleSlotClick(courtId: number, startTime: string) {
    if (!user) {
      navigate('/login', { state: { from: { pathname: location.pathname } } })
      return
    }
    const params = new URLSearchParams({
      resource_id: String(courtId),
      date: selectedDate,
      start_time: startTime + ':00',
      duration: String(duration),
      site_slug: siteSlug!,
    })
    navigate(`/parks/${siteSlug}/book?${params}`)
  }

  const courts = data?.courts ?? []
  const times = allTimeSlots(courts)
  const slotMap = buildSlotMap(courts)

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">{data?.site_name ?? 'Availability'}</h1>
      </div>

      {/* Date picker */}
      <div className="flex gap-2 overflow-x-auto pb-2">
        {dates.map((d) => {
          const parsed = parse(d, 'yyyy-MM-dd', new Date())
          const isSelected = d === selectedDate
          return (
            <button
              key={d}
              onClick={() => setSelectedDate(d)}
              className={`flex-shrink-0 rounded-lg border px-3 py-2 text-center text-sm transition ${
                isSelected
                  ? 'border-green-600 bg-green-600 text-white'
                  : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
              }`}
            >
              <div className="font-medium">{format(parsed, 'EEE')}</div>
              <div className="text-xs">{format(parsed, 'd MMM')}</div>
            </button>
          )
        })}
      </div>

      {/* Duration toggle */}
      <div className="flex gap-2">
        {[60, 120].map((d) => (
          <button
            key={d}
            onClick={() => setDuration(d)}
            className={`rounded-lg border px-3 py-1.5 text-sm transition ${
              duration === d
                ? 'border-green-600 bg-green-50 text-green-700'
                : 'border-gray-200 text-gray-600 hover:border-gray-300'
            }`}
          >
            {d === 60 ? '1 hour' : '2 hours'}
          </button>
        ))}
      </div>

      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message="Failed to load availability" onRetry={() => refetch()} />}

      {/* Grid */}
      {data && courts.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-gray-50">
                <th className="sticky left-0 z-10 w-16 border-b border-r border-gray-200 bg-gray-50 px-2 py-2 text-left text-xs font-medium text-gray-500">
                  Time
                </th>
                {courts.map((court) => (
                  <th
                    key={court.court_id}
                    className="border-b border-r border-gray-200 px-2 py-2 text-center last:border-r-0"
                  >
                    <div className="font-semibold text-gray-900">{court.court_name}</div>
                    <div className="text-xs font-normal text-gray-400">
                      {[
                        court.surface,
                        court.has_floodlights ? 'Floodlit' : null,
                      ]
                        .filter(Boolean)
                        .join(', ')}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {times.map((time) => (
                <tr key={time} className="border-b border-gray-100 last:border-b-0">
                  <td className="sticky left-0 z-10 border-r border-gray-200 bg-white px-2 py-0 text-xs font-medium text-gray-500">
                    {time}
                  </td>
                  {courts.map((court) => {
                    const slot = slotMap.get(court.court_id)?.get(time)
                    const slotIdx = court.slots.findIndex((s) => s.start_time === time)
                    const bookable = slot && slotIdx >= 0 && canBook(court, slotIdx)

                    // No slot at this time for this court (e.g. closes earlier)
                    if (!slot) {
                      return (
                        <td
                          key={court.court_id}
                          className="border-r border-gray-100 bg-gray-50 last:border-r-0"
                        />
                      )
                    }

                    if (bookable) {
                      return (
                        <td
                          key={court.court_id}
                          className="border-r border-gray-100 p-0.5 last:border-r-0"
                        >
                          <button
                            onClick={() => handleSlotClick(court.court_id, time)}
                            className="h-full w-full rounded bg-green-50 px-1 py-2 text-xs font-medium text-green-700 transition hover:bg-green-100"
                          >
                            Available
                          </button>
                        </td>
                      )
                    }

                    // Unavailable (booked or past)
                    return (
                      <td
                        key={court.court_id}
                        className="border-r border-gray-100 p-0.5 last:border-r-0"
                      >
                        <div className="rounded bg-amber-50 px-1 py-2 text-center text-xs text-amber-600">
                          Booked
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && courts.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-500">No courts at this park.</p>
      )}
    </div>
  )
}
