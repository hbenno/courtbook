import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getPreferences, replacePreferences } from '../api/endpoints'
import type { PreferenceIn } from '../types/api'

export function usePreferences() {
  return useQuery({
    queryKey: ['preferences'],
    queryFn: getPreferences,
  })
}

export function useReplacePreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (prefs: PreferenceIn[]) => replacePreferences(prefs),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['preferences'] }),
  })
}
