import { useCallback, useEffect, useMemo, useState } from 'react'
import { AUTH_EXPIRED_EVENT } from '../services/api.js'
import {
  clearAuthSession,
  clearResumeCache,
  getAccessToken,
} from '../services/authSession.js'
import { getCurrentUser } from '../services/userService.js'
import { AuthContext } from './authContext.js'

export function AuthProvider({ children }) {
  const [state, setState] = useState({
    user: null,
    loading: true,
    error: null,
  })

  useEffect(() => {
    let active = true

    function handleAuthenticationExpired() {
      clearResumeCache()
      if (active) setState({ user: null, loading: false, error: null })
    }

    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthenticationExpired)

    Promise.resolve()
      .then(() => getAccessToken())
      .then((token) => (token ? getCurrentUser() : null))
      .then((user) => {
        if (active) setState({ user, loading: false, error: null })
      })
      .catch((error) => {
        if (active && error.status !== 401) {
          setState({ user: null, loading: false, error })
        }
      })

    return () => {
      active = false
      window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthenticationExpired)
    }
  }, [])

  const setUser = useCallback((user) => {
    if (!user) clearAuthSession()
    if (!user || state.user?.id !== user.id) {
      clearResumeCache()
    }
    setState({ user, loading: false, error: null })
  }, [state.user?.id])

  const value = useMemo(
    () => ({ ...state, setUser }),
    [state, setUser]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
