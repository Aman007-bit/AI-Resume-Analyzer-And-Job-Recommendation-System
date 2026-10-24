import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { ErrorState, LoadingState } from '../components/PageState.jsx'
import { useAuth } from '../context/authContext.js'

export default function ProtectedRoute() {
  const { user, loading, error } = useAuth()
  const location = useLocation()

  if (loading) return <LoadingState text="Checking your account..." />

  if (error) {
    return (
      <ErrorState
        title="We couldn't verify your account."
        text="Check the backend connection and try again."
        actionLabel="Go to Login"
        actionTo="/login"
      />
    )
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}
