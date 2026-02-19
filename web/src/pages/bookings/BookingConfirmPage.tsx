import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { loadStripe } from '@stripe/stripe-js'
import { Elements, PaymentElement, useElements, useStripe } from '@stripe/react-stripe-js'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { useCreateBooking } from '../../hooks/useBookings'
import { formatDate, formatPence, formatTime } from '../../lib/format'
import { ApiRequestError } from '../../api/client'
import type { Booking } from '../../types/api'

const stripePromise = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY
  ? loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY)
  : null

function PaymentForm({ onSuccess }: { onSuccess: () => void }) {
  const stripe = useStripe()
  const elements = useElements()
  const [paying, setPaying] = useState(false)
  const [payError, setPayError] = useState('')

  async function handlePay() {
    if (!stripe || !elements) return
    setPaying(true)
    setPayError('')
    const { error } = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: window.location.origin + '/bookings' },
      redirect: 'if_required',
    })
    if (error) {
      setPayError(error.message ?? 'Payment failed')
      setPaying(false)
    } else {
      onSuccess()
    }
  }

  return (
    <div className="space-y-4">
      <PaymentElement />
      {payError && (
        <p className="text-sm text-red-600">{payError}</p>
      )}
      <Button onClick={handlePay} loading={paying} className="w-full">
        Pay now
      </Button>
    </div>
  )
}

export function BookingConfirmPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const createBooking = useCreateBooking()

  const resourceId = Number(params.get('resource_id'))
  const date = params.get('date') ?? ''
  const startTime = params.get('start_time') ?? ''
  const duration = Number(params.get('duration') ?? '60')

  const [booking, setBooking] = useState<Booking | null>(null)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)

  async function handleConfirm() {
    setError('')
    setConfirming(true)
    try {
      const result = await createBooking.mutateAsync({
        resource_id: resourceId,
        booking_date: date,
        start_time: startTime,
        duration_minutes: duration,
      })
      setBooking(result)
      // If no payment needed, go to bookings
      if (!result.client_secret) {
        navigate('/bookings', { replace: true })
      }
    } catch (err) {
      if (err instanceof ApiRequestError) {
        const detail = err.detail
        if (Array.isArray(detail)) {
          setError(detail.map((d) => d.message ?? d.msg ?? '').join('. '))
        } else {
          setError(String(detail))
        }
      } else {
        setError('Booking failed')
      }
    } finally {
      setConfirming(false)
    }
  }

  const endHour = startTime
    ? formatTime(
        `${String(Number(startTime.split(':')[0]) + duration / 60).padStart(2, '0')}:${startTime.split(':')[1]}:00`,
      )
    : ''

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">Confirm Booking</h1>

      <Card>
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-gray-500">Date</dt>
            <dd className="font-medium">{date ? formatDate(date) : '-'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Time</dt>
            <dd className="font-medium">
              {formatTime(startTime)} – {endHour}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Duration</dt>
            <dd className="font-medium">{duration === 60 ? '1 hour' : '2 hours'}</dd>
          </div>
        </dl>
      </Card>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Before booking is created: confirm button */}
      {!booking && (
        <Button onClick={handleConfirm} loading={confirming} className="w-full">
          Confirm booking
        </Button>
      )}

      {/* After booking created: show price and payment if needed */}
      {booking && booking.client_secret && stripePromise && (
        <div className="space-y-3">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Amount due: <strong>{formatPence(booking.amount_pence)}</strong>
          </div>
          <Elements
            stripe={stripePromise}
            options={{ clientSecret: booking.client_secret, appearance: { theme: 'stripe' } }}
          >
            <PaymentForm onSuccess={() => navigate('/bookings', { replace: true })} />
          </Elements>
        </div>
      )}

      {booking && !booking.client_secret && (
        <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-center text-sm text-green-700">
          Booking confirmed! Redirecting...
        </div>
      )}
    </div>
  )
}
