import { clearAuthSession, getAccessToken } from './authSession.js'

export const AUTH_EXPIRED_EVENT = 'resumeai:authentication-expired'

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

function messageFrom(data, status) {
  const detail = data?.detail ?? data?.message

  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === 'string' ? item : item?.msg ?? 'Invalid request'))
      .join(', ')
  }

  return `Request failed with status ${status}`
}

export async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {})
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
    })
  } catch {
    throw new Error(
      `Cannot connect to the backend at ${API_BASE_URL}. Check that FastAPI is running.`
    )
  }

  const text = await response.text()
  let data = {}
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }

  if (!response.ok) {
    if (response.status === 401) {
      clearAuthSession()
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    }

    const error = new Error(messageFrom(data, response.status))
    error.status = response.status
    throw error
  }

  return data
}
