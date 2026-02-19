import { useQuery } from '@tanstack/react-query'
import { getSites } from '../api/endpoints'

export function useSites() {
  return useQuery({
    queryKey: ['sites'],
    queryFn: getSites,
    staleTime: 5 * 60 * 1000,
  })
}
