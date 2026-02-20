import { useQuery } from '@tanstack/react-query'
import { getSiteAvailability } from '../api/endpoints'

export function useSiteAvailability(siteSlug: string, date: string) {
  return useQuery({
    queryKey: ['siteAvailability', siteSlug, date],
    queryFn: () => getSiteAvailability(siteSlug, date),
    staleTime: 30 * 1000,
    enabled: !!siteSlug && !!date,
  })
}
