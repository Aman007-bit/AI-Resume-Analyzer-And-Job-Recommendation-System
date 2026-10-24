import { mockPlatformStats } from '../data/mockData.js'
import { apiRequest } from './api.js'

const SAVED_KEY = 'resumeai:savedJobs'

function getResumeId() {
  return localStorage.getItem('resumeId')
}

function normalizeSkills(skills) {
  if (!Array.isArray(skills)) return []

  return skills.map((skill) => {
    if (typeof skill === 'string') return skill
    return skill?.name ?? skill?.skill_name ?? ''
  }).filter(Boolean)
}

function mapJob(job) {
  return {
    id: String(job.job_id ?? job.id),
    title: job.title ?? 'Untitled job',
    company: job.company ?? 'Company not specified',
    location: job.location ?? 'Location not specified',
    workMode: job.work_mode ?? 'unknown',
    description: job.description ?? '',
    requirements: normalizeSkills(
      job.required_skills ?? job.skills ?? []
    ),
    sourceUrl: job.source_url ?? '',
    sourceName: job.source_name ?? '',
    applyUrl: job.source_url ?? '',
    matchScore: Number(job.match_score ?? job.score ?? 0),
    requiredSkills: normalizeSkills(
      job.required_skills ?? job.skills ?? []
    ),
    matchedSkills: normalizeSkills(job.matched_skills ?? []),
    missingSkills: normalizeSkills(job.missing_skills ?? []),
  }
}

export async function getRecommendationResult(resumeId = getResumeId()) {
  if (!resumeId) {
    throw new Error('Please upload your resume before viewing recommendations.')
  }

  const data = await apiRequest(
    `/api/recommendations/${encodeURIComponent(resumeId)}`
  )

  if (!Array.isArray(data.recommendations)) {
    throw new Error(
      'The recommendation API returned an unexpected response.'
    )
  }

  return {
    availability: data.availability ?? { status: 'available' },
    recommendations: data.recommendations
      .map(mapJob)
      .filter((job) => job.title && job.id !== 'undefined')
      .sort((a, b) => b.matchScore - a.matchScore),
  }
}

export async function getRecommendedJobs(resumeId = getResumeId()) {
  const result = await getRecommendationResult(resumeId)
  return result.recommendations
}

export async function getJobById(id) {
  // First try recommended jobs
  try {
    const jobs = await getRecommendedJobs()
    const found = jobs.find((job) => String(job.id) === String(id))
    if (found) return found
  } catch {
    // ignore
  }

  // Then try general jobs API
  try {
    const data = await apiRequest(`/api/jobs/${encodeURIComponent(id)}`)
    if (data) return mapJob(data)
  } catch {
    // ignore
  }

  return null
}

export async function getPlatformStats() {
  return [...mockPlatformStats]
}

export async function getMarketInsights(resumeId = getResumeId()) {
  if (!resumeId) {
    throw new Error('Please upload your resume before viewing market insights.')
  }

  return apiRequest(
    `/api/recommendations/${encodeURIComponent(resumeId)}/market-insights`
  )
}

function readSaved() {
  try {
    const saved = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]')
    return Array.isArray(saved) ? saved.map(String) : []
  } catch {
    return []
  }
}

export function isJobSaved(id) {
  return readSaved().includes(String(id))
}

export function toggleSavedJob(id) {
  const saved = readSaved()
  const key = String(id)

  const next = saved.includes(key)
    ? saved.filter((item) => item !== key)
    : [...saved, key]

  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify(next))
  } catch {
    // Browser storage may be unavailable.
  }

  return next.includes(key)
}
