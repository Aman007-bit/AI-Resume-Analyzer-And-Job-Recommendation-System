const TOKEN_KEY = 'resumeai:accessToken'
const LEGACY_SESSION_KEY = 'resumeai:session'

export function getAccessToken() {
  return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY)
}

export function setAccessToken(token, remember = false) {
  clearAuthSession()
  const storage = remember ? localStorage : sessionStorage
  storage.setItem(TOKEN_KEY, token)
  sessionStorage.removeItem(LEGACY_SESSION_KEY)
}

export function clearAuthSession() {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(LEGACY_SESSION_KEY)
  localStorage.removeItem(TOKEN_KEY)
}

export function clearResumeCache() {
  localStorage.removeItem('resumeId')

  const profileKeys = []
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index)
    if (key?.startsWith('resumeProfile:')) profileKeys.push(key)
  }
  profileKeys.forEach((key) => localStorage.removeItem(key))
}
