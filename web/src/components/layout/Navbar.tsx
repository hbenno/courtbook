import { Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'

export function Navbar() {
  const { user, logout } = useAuth()

  return (
    <header className="sticky top-0 z-40 border-b border-gray-200 bg-white">
      <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
        <Link to="/parks" className="text-lg font-bold text-green-700">
          CourtBook
        </Link>

        <nav className="hidden items-center gap-4 sm:flex">
          <Link to="/parks" className="text-sm text-gray-600 hover:text-gray-900">
            Parks
          </Link>
          {user && (
            <>
              <Link to="/bookings" className="text-sm text-gray-600 hover:text-gray-900">
                My Bookings
              </Link>
              <Link to="/preferences" className="text-sm text-gray-600 hover:text-gray-900">
                Preferences
              </Link>
            </>
          )}
        </nav>

        <div className="flex items-center gap-3">
          {user ? (
            <>
              <span className="hidden text-sm text-gray-500 sm:inline">
                {user.first_name}
              </span>
              <button
                onClick={logout}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Log out
              </button>
            </>
          ) : (
            <Link
              to="/login"
              className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
            >
              Log in
            </Link>
          )}
        </div>
      </div>
    </header>
  )
}
