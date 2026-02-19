import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { ParkListPage } from './pages/parks/ParkListPage'
import { CourtListPage } from './pages/parks/CourtListPage'
import { AvailabilityPage } from './pages/parks/AvailabilityPage'
import { BookingConfirmPage } from './pages/bookings/BookingConfirmPage'
import { MyBookingsPage } from './pages/bookings/MyBookingsPage'
import { PreferencesPage } from './pages/preferences/PreferencesPage'
import { NotFoundPage } from './pages/NotFoundPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public (outside AppLayout) */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />

            {/* App shell */}
            <Route element={<AppLayout />}>
              <Route path="/" element={<Navigate to="/parks" replace />} />
              <Route path="/parks" element={<ParkListPage />} />
              <Route path="/parks/:siteSlug" element={<CourtListPage />} />
              <Route path="/parks/:siteSlug/courts/:courtId" element={<AvailabilityPage />} />

              {/* Protected */}
              <Route
                path="/parks/:siteSlug/courts/:courtId/book"
                element={
                  <ProtectedRoute>
                    <BookingConfirmPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/bookings"
                element={
                  <ProtectedRoute>
                    <MyBookingsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/preferences"
                element={
                  <ProtectedRoute>
                    <PreferencesPage />
                  </ProtectedRoute>
                }
              />

              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
