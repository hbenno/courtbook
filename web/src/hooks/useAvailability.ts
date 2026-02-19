import { useQuery } from '@tanstack/react-query'
import { getAvailability } from '../api/endpoints'

export function useAvailability(siteSlug: string, courtId: number, date: string) {
  return useQuery({
    queryKey: ['availability', siteSlug, courtId, date],
    queryFn: () => getAvailability(siteSlug, courtId, date),
    staleTime: 30 * 1000, // 30 seconds — availability changes frequently
    enabled: !!siteSlug && !!courtId && !!date,
  })
}
