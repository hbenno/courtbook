import { Card } from '../../components/ui/Card'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import { Button } from '../../components/ui/Button'
import { useCancelBooking, useMyBookings } from '../../hooks/useBookings'
import { useResourceLookup } from '../../hooks/useResourceLookup'
import { formatDate, formatPence, formatTimeRange } from '../../lib/format'
import { useState } from 'react'

export function MyBookingsPage() {
  const { data: bookings, isLoading, error, refetch } = useMyBookings()
  const cancelBooking = useCancelBooking()
  const { resources } = useResourceLookup()
  const [cancellingId, setCancellingId] = useState<number | null>(null)

  async function handleCancel(bookingId: number) {
    if (!confirm('Cancel this booking? You will receive credit for future bookings.')) return
    setCancellingId(bookingId)
    try {
      await cancelBooking.mutateAsync(bookingId)
    } catch {
      alert('Failed to cancel booking. Please try again.')
    } finally {
      setCancellingId(null)
    }
  }

  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorMessage message="Failed to load bookings" onRetry={() => refetch()} />

  const upcoming = bookings?.filter((b) => b.status === 'confirmed') ?? []
  const past = bookings?.filter((b) => b.status !== 'confirmed') ?? []

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-900">My Bookings</h1>

      {upcoming.length === 0 && past.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-500">No bookings yet.</p>
      )}

      {upcoming.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
            Upcoming
          </h2>
          {upcoming.map((b) => {
            const res = resources.get(b.resource_id)
            return (
              <Card key={b.id}>
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-medium text-gray-900">
                      {res ? `${res.name} — ${res.siteName}` : `Court #${b.resource_id}`}
                    </p>
                    <p className="text-sm text-gray-600">{formatDate(b.booking_date)}</p>
                    <p className="text-sm text-gray-600">
                      {formatTimeRange(b.start_time, b.end_time)}
                    </p>
                    {b.amount_pence > 0 && (
                      <p className="mt-1 text-xs text-gray-400">
                        {formatPence(b.amount_pence)} — {b.payment_status}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="danger"
                    onClick={() => handleCancel(b.id)}
                    loading={cancellingId === b.id}
                    className="text-xs"
                  >
                    Cancel
                  </Button>
                </div>
              </Card>
            )
          })}
        </section>
      )}

      {past.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">Past</h2>
          {past.map((b) => {
            const res = resources.get(b.resource_id)
            return (
              <Card key={b.id} className="opacity-60">
                <p className="font-medium text-gray-900">
                  {res ? `${res.name} — ${res.siteName}` : `Court #${b.resource_id}`}
                </p>
                <p className="text-sm text-gray-600">
                  {formatDate(b.booking_date)} — {formatTimeRange(b.start_time, b.end_time)}
                </p>
                <p className="mt-1 text-xs text-gray-400 capitalize">{b.status}</p>
              </Card>
            )
          })}
        </section>
      )}
    </div>
  )
}
