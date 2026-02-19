import { useNavigate, useParams } from 'react-router-dom'
import { Card } from '../../components/ui/Card'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import { useCourts } from '../../hooks/useCourts'

export function CourtListPage() {
  const { siteSlug } = useParams<{ siteSlug: string }>()
  const { data: courts, isLoading, error, refetch } = useCourts(siteSlug!)
  const navigate = useNavigate()

  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorMessage message="Failed to load courts" onRetry={() => refetch()} />

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">Courts</h1>
      <div className="grid gap-3">
        {courts?.map((court) => (
          <Card
            key={court.id}
            onClick={() => navigate(`/parks/${siteSlug}/courts/${court.id}`)}
          >
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-gray-900">{court.name}</h2>
              <div className="flex gap-2">
                {court.has_floodlights && (
                  <span className="rounded-full bg-yellow-100 px-2 py-0.5 text-xs text-yellow-700">
                    Floodlit
                  </span>
                )}
                {court.surface && (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                    {court.surface}
                  </span>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
