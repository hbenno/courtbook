import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { cancelBooking, createBooking, getMyBookings } from '../api/endpoints'
import type { BookingCreate } from '../types/api'

export function useMyBookings() {
  return useQuery({
    queryKey: ['myBookings'],
    queryFn: getMyBookings,
  })
}

export function useCreateBooking() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BookingCreate) => createBooking(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['myBookings'] })
      qc.invalidateQueries({ queryKey: ['availability'] })
    },
  })
}

export function useCancelBooking() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (bookingId: number) => cancelBooking(bookingId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['myBookings'] })
      qc.invalidateQueries({ queryKey: ['availability'] })
    },
  })
}
