import { useQuery } from '@tanstack/react-query'
import { getCourts } from '../api/endpoints'

export function useCourts(siteSlug: string) {
  return useQuery({
    queryKey: ['courts', siteSlug],
    queryFn: () => getCourts(siteSlug),
    staleTime: 5 * 60 * 1000,
    enabled: !!siteSlug,
  })
}
