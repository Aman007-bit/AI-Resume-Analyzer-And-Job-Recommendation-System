import { apiRequest } from './api.js'
import { getAccessToken, setAccessToken } from './authSession.js'
import { getRecommendedJobs } from './jobService.js'

function parseEducation(educationText, fallbackEducation = {}) {
  const text = (educationText || '').replace(/\s+/g, ' ').trim()

  if (!text) {
    return {
      ...fallbackEducation,
      years: 'Not detected in resume',
    }
  }

  const rangeMatch = text.match(
    /\b(19\d{2}|20\d{2})\s*(?:-|–|—|to)\s*(19\d{2}|20\d{2})\b/i
  )

  const years = rangeMatch
    ? `${rangeMatch[1]}–${rangeMatch[2]}`
    : (text.match(/\b(?:19|20)\d{2}\b/g) || []).join(', ') ||
      'Not detected in resume'

  const lines = (educationText || '')
    .split(/\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  const degreeLine =
    lines.find((line) =>
      /\b(bachelor|b\.?tech|btech|b\.?e\.?|bsc|b\.?sc|bca|master|m\.?tech|mca|mba|degree|diploma|graduation)\b/i.test(line)
    ) || lines[0] || 'Education'

  const institutionLine =
    lines.find((line) =>
      /\b(university|college|institute|school)\b/i.test(line)
    ) || fallbackEducation.institution || 'Institution not detected'

  const cgpaMatch = text.match(/\b(?:cgpa|gpa)\s*[:-]?\s*(\d+(?:\.\d+)?)(?:\s*\/\s*\d+(?:\.\d+)?)?/i)
  const cgpa = cgpaMatch ? cgpaMatch[1] : null

  return {
    degree: degreeLine,
    institution: institutionLine,
    years,
    cgpa,
  }
}

function getUploadedProfile() {
  const resumeId = localStorage.getItem('resumeId')

  if (!resumeId) {
    return { resumeId: null, profile: null }
  }

  try {
    const cached = localStorage.getItem(`resumeProfile:${resumeId}`)

    return {
      resumeId,
      profile: cached ? JSON.parse(cached) : null,
    }
  } catch {
    return { resumeId, profile: null }
  }
}

export async function getUserProfile(user) {
  const { resumeId, profile: uploadedProfile } = getUploadedProfile()

  let recommendedJobs = []
  let recommendationError = null
  if (resumeId) {
    try {
      recommendedJobs = await getRecommendedJobs(resumeId)
    } catch (error) {
      if (error?.status === 401) throw error
      recommendationError =
        error?.message ?? 'Could not load recommendations right now.'
    }
  }

  const education = parseEducation(uploadedProfile?.education, {
    degree: 'Education unavailable',
    institution: 'Institution not detected',
  })
  const skills = Array.isArray(uploadedProfile?.skills) ? uploadedProfile.skills : []
  const matchedSkills = [...new Set(recommendedJobs.flatMap((job) => job.matchedSkills))]
  const missingSkills = [...new Set(recommendedJobs.flatMap((job) => job.missingSkills))]
  const analysisAvailable = recommendedJobs.some((job) => job.requiredSkills.length > 0)

  const scoredJobs = recommendedJobs.filter((job) => Number.isFinite(job.matchScore))
  const profileMatch = scoredJobs.length
    ? Math.round(scoredJobs.reduce((sum, job) => sum + job.matchScore, 0) / scoredJobs.length)
    : null

  return {
    name: user?.name || uploadedProfile?.name || 'Candidate',
    email: user?.email || '',
    phone: uploadedProfile?.phone || '',
    education,
    skills,
    matchedSkills,
    missingSkills,
    analysisAvailable,
    suggestions: [],
    recommendedJobs,
    recommendationError,
    statistics: {
      profileMatch,
      totalSkills: skills.length,
      recommendedJobs: recommendedJobs.length,
      missingSkills: analysisAvailable ? missingSkills.length : null,
    },
  }
}

export async function login({ email, password }, remember = false) {
  const data = await apiRequest('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!data.access_token || !data.user) {
    throw new Error('The login API returned an unexpected response.')
  }
  setAccessToken(data.access_token, remember)
  return data.user
}

export async function signup({ fullName, email, password }) {
  const data = await apiRequest('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: fullName, email, password }),
  })
  if (!data.access_token || !data.user) {
    throw new Error('The registration API returned an unexpected response.')
  }
  setAccessToken(data.access_token)
  return data.user
}

export async function getCurrentUser() {
  if (!getAccessToken()) return null
  return apiRequest('/api/auth/me')
}