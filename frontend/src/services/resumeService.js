
import { getRecommendedJobs } from './jobService.js'
import { apiRequest } from './api.js'

export const MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024

export function validateResumeFile(file) {
  if (!file) return 'Please select a PDF resume first.'

  if (!/\.pdf$/i.test(file.name)) {
    return 'Only PDF files are supported.'
  }

  if (file.size === 0) {
    return 'This file is empty. Please choose another PDF.'
  }

  if (file.size > MAX_RESUME_SIZE_BYTES) {
    return 'Resume must be smaller than 10 MB.'
  }

  return null
}

export async function analyzeResume(file) {
  const validationError = validateResumeFile(file)

  if (validationError) {
    throw new Error(validationError)
  }

  const formData = new FormData()
  formData.append('file', file)

  const data = await apiRequest('/api/resumes/upload', {
    method: 'POST',
    body: formData,
  })

  const resumeId = data.resume_id ?? data.resumeId

  if (resumeId == null) {
    throw new Error('Upload response did not contain a resume ID.')
  }

  const profile = data.profile ?? {}
  const skills = Array.isArray(data.skills_found)
    ? data.skills_found
    : []

  const cachedProfile = {
    name: profile.name ?? '',
    email: profile.email ?? '',
    phone: profile.phone ?? '',
    education: profile.education ?? '',
    skills,
    fileName: data.file_name ?? file.name,
  }

  try {
    localStorage.setItem('resumeId', String(resumeId))
    localStorage.setItem(
      `resumeProfile:${resumeId}`,
      JSON.stringify(cachedProfile)
    )
  } catch {
    throw new Error(
      'Resume uploaded, but the browser could not save the extracted profile.'
    )
  }

  // Try loading recommendations immediately for the newly uploaded resume.
  // The backend's existing recommendation endpoint handles recommendation
  // generation/retrieval; no additional endpoint is introduced.
  let recommendations = []
  let recommendationError = null

  if (data.recommendations_generated === false) {
    recommendationError =
      data.recommendation_error ?? 'Could not generate recommendations right now.'
  } else {
    try {
      recommendations = await getRecommendedJobs(String(resumeId))
    } catch (error) {
      recommendationError =
        error?.message ?? 'Could not load recommendations yet.'
    }
  }

  return {
    ...data,
    resume_id: resumeId,
    resumeId,
    fileName: data.file_name ?? file.name,
    size: file.size,
    profile,
    skills,
    recommendations,
    recommendationError,
  }
}
