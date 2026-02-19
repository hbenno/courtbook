import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-300">404</h1>
        <p className="mt-2 text-gray-500">Page not found</p>
        <Link to="/parks" className="mt-4 inline-block text-sm text-green-600 hover:underline">
          Go to Parks
        </Link>
      </div>
    </div>
  )
}
