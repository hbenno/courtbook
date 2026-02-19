import { Outlet } from 'react-router-dom'
import { BottomNav } from './BottomNav'
import { Navbar } from './Navbar'

export function AppLayout() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <main className="mx-auto max-w-3xl px-4 py-6 pb-20 sm:pb-6">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  )
}
