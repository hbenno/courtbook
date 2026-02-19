import { useNavigate } from 'react-router-dom'
import { Card } from '../../components/ui/Card'
import { ErrorMessage } from '../../components/ui/ErrorMessage'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import { useSites } from '../../hooks/useSites'

export function ParkListPage() {
  const { data: sites, isLoading, error, refetch } = useSites()
  const navigate = useNavigate()

  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorMessage message="Failed to load parks" onRetry={() => refetch()} />

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-gray-900">Parks</h1>
      <div className="grid gap-3">
        {sites?.map((site) => (
          <Card key={site.id} onClick={() => navigate(`/parks/${site.slug}`)}>
            <h2 className="font-semibold text-gray-900">{site.name}</h2>
            {site.postcode && (
              <p className="mt-0.5 text-sm text-gray-500">{site.postcode}</p>
            )}
          </Card>
        ))}
      </div>
    </div>
  )
}
