import { format, addDays, parse } from 'date-fns'
import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import { useAvailability } from '../../hooks/useAvailability'
import { useAuth } from '../../auth/AuthContext'

export function AvailabilityPage() {
  const { siteSlug, courtId } = useParams<{ siteSlug: string; courtId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()

  const today = format(new Date(), 'yyyy-MM-dd')
  const [selectedDate, setSelectedDate] = useState(searchParams.get('date') ?? today)
  const [duration, setDuration] = useState(60)

  const { data: availability, isLoading, error, refetch } = useAvailability(
    siteSlug!,
    Number(courtId),
    selectedDate,
  )

  // Generate next 7 days for the date picker
  const dates = Array.from({ length: 7 }, (_, i) => {
    const d = addDays(new Date(), i)
    return format(d, 'yyyy-MM-dd')
  })

  function handleSlotClick(startTime: string) {
    if (!user) {
      navigate('/login', { state: { from: { pathname: location.pathname } } })
      return
    }
    const params = new URLSearchParams({
      resource_id: courtId!,
      date: selectedDate,
      start_time: startTime,
      duration: String(duration),
      site_slug: siteSlug!,
    })
    navigate(`/parks/${siteSlug}/courts/${courtId}/book?${params}`)
  }

  /**
   * Check if a slot can start a booking of the selected duration.
   * For 2-hour bookings, the slot and the next slot must both be available.
   */
  function canBook(slotIndex: number): boolean {
    if (!availability) return false
    const slots = availability.slots
    if (!slots[slotIndex].is_available) return false
    if (duration <= 60) return true
    // 2-hour: need next slot too
    return slotIndex + 1 < slots.length && slots[slotIndex + 1].is_available
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">
        {availability?.court_name ?? 'Availability'}
      </h1>

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

      {/* Slots grid */}
      {isLoading && <LoadingSpinner />}
      {error && <ErrorMessage message="Failed to load availability" onRetry={() => refetch()} />}

      {availability && (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {availability.slots.map((slot, i) => {
            const bookable = canBook(i)
            return (
              <button
                key={slot.start_time}
                onClick={() => bookable && handleSlotClick(slot.start_time + ':00')}
                disabled={!bookable}
                className={`rounded-lg border px-3 py-2.5 text-sm font-medium transition ${
                  bookable
                    ? 'border-green-200 bg-green-50 text-green-700 hover:bg-green-100'
                    : 'border-gray-100 bg-gray-50 text-gray-400 cursor-not-allowed'
                }`}
              >
                {slot.start_time}
              </button>
            )
          })}
        </div>
      )}

      {availability && availability.slots.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-500">No slots available on this date.</p>
      )}
    </div>
  )
}
