import { useQuery } from '@tanstack/react-query'
import { getCourts, getSites } from '../api/endpoints'
import type { Resource, Site } from '../types/api'

interface ResourceLookup {
  resources: Map<number, Resource & { siteName: string }>
  loading: boolean
}

/**
 * Fetches all sites + courts and builds a resourceId → resource+siteName map.
 * Used to resolve resource_id on bookings to human-readable names.
 */
export function useResourceLookup(): ResourceLookup {
  const { data: sites, isLoading: sitesLoading } = useQuery({
    queryKey: ['sites'],
    queryFn: getSites,
    staleTime: 5 * 60 * 1000,
  })

  const { data: allCourts, isLoading: courtsLoading } = useQuery({
    queryKey: ['allCourts'],
    queryFn: async () => {
      if (!sites) return []
      const results: Array<{ site: Site; courts: Resource[] }> = []
      for (const site of sites) {
        const courts = await getCourts(site.slug)
        results.push({ site, courts })
      }
      return results
    },
    staleTime: 5 * 60 * 1000,
    enabled: !!sites,
  })

  const resources = new Map<number, Resource & { siteName: string }>()
  if (allCourts) {
    for (const { site, courts } of allCourts) {
      for (const court of courts) {
        resources.set(court.id, { ...court, siteName: site.name })
      }
    }
  }

  return { resources, loading: sitesLoading || courtsLoading }
}
