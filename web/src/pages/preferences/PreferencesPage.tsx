import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import { usePreferences, useReplacePreferences } from '../../hooks/usePreferences'
import { useSites } from '../../hooks/useSites'
import { useCourts } from '../../hooks/useCourts'
import { dayName } from '../../lib/format'
import type { Preference, PreferenceIn } from '../../types/api'

function PreferenceRow({
  pref,
  index,
  onRemove,
  onMoveUp,
  isFirst,
}: {
  pref: Preference
  index: number
  onRemove: () => void
  onMoveUp: () => void
  isFirst: boolean
}) {
  return (
    <Card className="flex items-center gap-3">
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-green-100 text-xs font-bold text-green-700">
        {index + 1}
      </span>
      <div className="flex-1 text-sm">
        {pref.site_name && <span className="font-medium">{pref.site_name}</span>}
        {pref.resource_name && <span> — {pref.resource_name}</span>}
        {pref.day_of_week != null && <span> — {dayName(pref.day_of_week)}</span>}
        {pref.preferred_start_time && (
          <span> at {pref.preferred_start_time.slice(0, 5)}</span>
        )}
        <span className="text-gray-400"> ({pref.duration_minutes}min)</span>
      </div>
      <div className="flex gap-1">
        {!isFirst && (
          <button onClick={onMoveUp} className="text-gray-400 hover:text-gray-600" title="Move up">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
            </svg>
          </button>
        )}
        <button onClick={onRemove} className="text-red-400 hover:text-red-600" title="Remove">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </Card>
  )
}

function AddPreferenceForm({
  onAdd,
}: {
  onAdd: (pref: PreferenceIn) => void
}) {
  const { data: sites } = useSites()
  const [siteSlug, setSiteSlug] = useState('')
  const { data: courts } = useCourts(siteSlug)

  const [siteId, setSiteId] = useState<number | null>(null)
  const [resourceId, setResourceId] = useState<number | null>(null)
  const [dayOfWeek, setDayOfWeek] = useState<number | null>(null)
  const [startTime, setStartTime] = useState('')
  const [duration, setDuration] = useState(60)

  function handleSiteChange(slug: string) {
    setSiteSlug(slug)
    const site = sites?.find((s) => s.slug === slug)
    setSiteId(site?.id ?? null)
    setResourceId(null)
  }

  function handleSubmit() {
    onAdd({
      site_id: siteId,
      resource_id: resourceId,
      day_of_week: dayOfWeek,
      preferred_start_time: startTime ? startTime + ':00' : null,
      duration_minutes: duration,
    })
    // Reset
    setSiteSlug('')
    setSiteId(null)
    setResourceId(null)
    setDayOfWeek(null)
    setStartTime('')
    setDuration(60)
  }

  return (
    <Card className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-700">Add preference</h3>
      <div className="grid grid-cols-2 gap-2">
        <select
          value={siteSlug}
          onChange={(e) => handleSiteChange(e.target.value)}
          className="rounded-lg border border-gray-300 px-2 py-2 text-sm"
        >
          <option value="">Any park</option>
          {sites?.map((s) => (
            <option key={s.slug} value={s.slug}>{s.name}</option>
          ))}
        </select>
        <select
          value={resourceId ?? ''}
          onChange={(e) => setResourceId(e.target.value ? Number(e.target.value) : null)}
          className="rounded-lg border border-gray-300 px-2 py-2 text-sm"
          disabled={!siteSlug}
        >
          <option value="">Any court</option>
          {courts?.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select
          value={dayOfWeek ?? ''}
          onChange={(e) => setDayOfWeek(e.target.value ? Number(e.target.value) : null)}
          className="rounded-lg border border-gray-300 px-2 py-2 text-sm"
        >
          <option value="">Any day</option>
          {[0, 1, 2, 3, 4, 5, 6].map((d) => (
            <option key={d} value={d}>{dayName(d)}</option>
          ))}
        </select>
        <input
          type="time"
          value={startTime}
          onChange={(e) => setStartTime(e.target.value)}
          className="rounded-lg border border-gray-300 px-2 py-2 text-sm"
          placeholder="Time"
        />
      </div>
      <div className="flex items-center gap-3">
        <select
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
          className="rounded-lg border border-gray-300 px-2 py-2 text-sm"
        >
          <option value={60}>1 hour</option>
          <option value={120}>2 hours</option>
        </select>
        <Button onClick={handleSubmit} className="text-sm">
          Add
        </Button>
      </div>
    </Card>
  )
}

export function PreferencesPage() {
  const { data: prefs, isLoading, error, refetch } = usePreferences()
  const replaceMutation = useReplacePreferences()
  const [localPrefs, setLocalPrefs] = useState<Preference[] | null>(null)
  const [dirty, setDirty] = useState(false)

  // Sync server data → local state
  useEffect(() => {
    if (prefs && !dirty) setLocalPrefs(prefs)
  }, [prefs, dirty])

  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorMessage message="Failed to load preferences" onRetry={() => refetch()} />

  const items = localPrefs ?? prefs ?? []

  function remove(index: number) {
    const next = [...items]
    next.splice(index, 1)
    setLocalPrefs(next)
    setDirty(true)
  }

  function moveUp(index: number) {
    if (index === 0) return
    const next = [...items]
    ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
    setLocalPrefs(next)
    setDirty(true)
  }

  function addPref(pref: PreferenceIn) {
    const newPref: Preference = {
      id: -Date.now(), // temporary ID
      priority: items.length + 1,
      site_id: pref.site_id ?? null,
      site_name: null,
      resource_id: pref.resource_id ?? null,
      resource_name: null,
      day_of_week: pref.day_of_week ?? null,
      preferred_start_time: pref.preferred_start_time ?? null,
      duration_minutes: pref.duration_minutes,
    }
    setLocalPrefs([...items, newPref])
    setDirty(true)
  }

  async function save() {
    const payload: PreferenceIn[] = items.map((p) => ({
      site_id: p.site_id,
      resource_id: p.resource_id,
      day_of_week: p.day_of_week,
      preferred_start_time: p.preferred_start_time,
      duration_minutes: p.duration_minutes,
    }))
    await replaceMutation.mutateAsync(payload)
    setDirty(false)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">Preferences</h1>
        {dirty && (
          <Button onClick={save} loading={replaceMutation.isPending} className="text-sm">
            Save
          </Button>
        )}
      </div>

      <p className="text-sm text-gray-500">
        Order your preferred courts and times. These will be used during the fairness allocation
        window.
      </p>

      {items.length === 0 && (
        <p className="py-4 text-center text-sm text-gray-400">No preferences yet.</p>
      )}

      <div className="space-y-2">
        {items.map((pref, i) => (
          <PreferenceRow
            key={pref.id}
            pref={pref}
            index={i}
            onRemove={() => remove(i)}
            onMoveUp={() => moveUp(i)}
            isFirst={i === 0}
          />
        ))}
      </div>

      <AddPreferenceForm onAdd={addPref} />
    </div>
  )
}
