import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/authContext.js'
import { getUserProfile } from '../services/userService.js'
import { getMarketInsights } from '../services/jobService.js'
import { getGreeting } from '../utils/format.js'
import useAsyncData from '../hooks/useAsyncData.js'

const TOP_JOBS_SHOWN = 3

export default function Dashboard() {
  const { user } = useAuth()
  const { data: profile, loading, error } = useAsyncData(getUserProfile, user)
  const [insights, setInsights] = useState(null)
  const [insightsError, setInsightsError] = useState(null)

  useEffect(() => {
    if (!profile) return
    let cancelled = false
    getMarketInsights()
      .then((data) => { if (!cancelled) setInsights(data) })
      .catch((err) => { if (!cancelled) setInsightsError(err?.message || 'Could not load market insights.') })
    return () => { cancelled = true }
  }, [profile])

  if (loading) return <div className="flex min-h-[60vh] items-center justify-center text-gray-500">Loading your dashboard...</div>

  if (error || !profile) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-gray-600">We couldn't load your dashboard. Please upload your resume again.</p>
        <Link to="/upload" className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
          </svg>
          Upload Resume
        </Link>
      </div>
    )
  }

  const { statistics, education } = profile
  const degree = (education.degree || 'Education')
    .replace(/\s*[,;|]?\s*CGPA\s*:\s*\d+(?:\.\d+)?/gi, '')
    .replace(/\s+\d{4}\s*[–—-]\s*\d{4}\s*$/, '')
    .trim()

  const matchedPct = Math.round((profile.matchedSkills.length / Math.max(profile.matchedSkills.length + profile.missingSkills.length, 1)) * 100)
  const missingPct = 100 - matchedPct

  const skillReasons = {
    'Go': 'Used heavily in cloud infrastructure and high-performance backend systems.',
    'AWS': 'Most companies prefer cloud experience; AWS is the most requested platform.',
    'Angular': 'Still widely used in enterprise frontend roles alongside React.',
    'GCP': 'Growing adoption in AI and data workloads; useful alongside AWS.',
    'Kafka': 'Standard for real-time data pipelines in modern backend systems.',
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{getGreeting()}, {profile.name}!</h1>
          <p className="mt-1 text-sm text-gray-500">Here's your resume analysis and job recommendations.</p>
        </div>
        <Link to="/upload" className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
          </svg>
          Upload New Resume
        </Link>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Profile Match</p>
          <p className="mt-1 text-2xl font-bold text-green-600">{statistics.profileMatch == null ? 'Unavailable' : `${statistics.profileMatch}%`}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Total Skills</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{statistics.totalSkills}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Recommended Jobs</p>
          <p className="mt-1 text-2xl font-bold text-blue-600">{statistics.recommendedJobs}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Missing Skills</p>
          <p className="mt-1 text-2xl font-bold text-red-600">{statistics.missingSkills ?? 'Unavailable'}</p>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-lg font-semibold text-gray-900">Your Profile</h2>
          <div className="mt-4">
            <div className="flex items-start justify-between">
              <p className="font-medium text-gray-900">{degree}</p>
              <p className="text-sm font-medium text-gray-900">CGPA: {education.cgpa ?? 'Unavailable'}</p>
            </div>
            <p className="text-sm text-gray-500">{education.institution}</p>
            <p className="text-sm text-gray-500">{education.years}</p>
          </div>
          <h3 className="mt-4 text-sm font-semibold text-gray-700">Detected Skills</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {profile.skills.map((skill) => (
              <span key={skill} className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">{skill}</span>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-lg font-semibold text-gray-900">Skill Analysis</h2>
          {profile.analysisAvailable ? (
            <div className="mt-4 flex items-center justify-center gap-6">
              <svg viewBox="0 0 36 36" className="h-32 w-32 -rotate-90">
                <circle cx="18" cy="18" r="15.9155" fill="none" stroke="#e5e7eb" strokeWidth="5" />
                <circle cx="18" cy="18" r="15.9155" fill="none" stroke="#7c3aed" strokeWidth="5"
                  strokeDasharray={`${matchedPct} ${100 - matchedPct}`}
                  strokeDashoffset="0" strokeLinecap="butt" />
                <circle cx="18" cy="18" r="15.9155" fill="none" stroke="#ec4899" strokeWidth="5"
                  strokeDasharray={`${missingPct} ${100 - missingPct}`}
                  strokeDashoffset={`-${matchedPct}`} strokeLinecap="butt" />
                <text x="18" y="20.5" textAnchor="middle" fontSize="6" fill="#111827" fontWeight="600" className="rotate-90 origin-center">
                  {matchedPct}%
                </text>
              </svg>
              <div className="text-sm">
                <p className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-purple-600" /> Matched: {profile.matchedSkills.length}</p>
                <p className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-pink-600" /> Missing: {profile.missingSkills.length}</p>
              </div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-gray-500">Skill analysis is unavailable until recommendations include required skills.</p>
          )}
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Recommended Jobs</h2>
            <p className="text-sm text-gray-500">Based on your skills and experience</p>
          </div>
          <Link to="/jobs" className="text-sm font-medium text-blue-600 hover:underline">View All</Link>
        </div>
        {profile.recommendationError && (
          <p className="mt-4 text-sm text-red-600">{profile.recommendationError}</p>
        )}
        <div className="mt-4 space-y-3">
          {profile.recommendedJobs.slice(0, TOP_JOBS_SHOWN).map((job) => {
            console.log('JOB:', job)
            const match = job.matchPercentage ?? job.matchScore ?? job.score ?? job.match_percentage ?? null
            return (
              <div key={job.id} className="rounded-lg border border-gray-100 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50">
                      <svg className="h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <div>
                      <p className="font-medium text-gray-900">{job.title}</p>
                      <p className="text-sm text-gray-500">{job.company}</p>
                      <p className="text-xs text-gray-400">{job.location} · {job.workMode || 'on_site'}</p>
                    </div>
                  </div>
                  {match != null && (
                    <span className="rounded-full bg-green-50 px-2.5 py-1 text-xs font-semibold text-green-700">
                      {match}% match
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
        <div className="mt-4">
          <Link to="/jobs" className="inline-block rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Recommended Jobs</Link>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-lg font-semibold text-green-700">Matched Skills</h2>
          {!profile.analysisAvailable && <p className="mt-2 text-sm text-gray-500">Unavailable</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {profile.matchedSkills.map((skill) => (
              <span key={skill} className="rounded-full bg-green-50 px-3 py-1 text-xs font-medium text-green-700">{skill}</span>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <h2 className="text-lg font-semibold text-orange-700">Missing Skills</h2>
          {!profile.analysisAvailable && <p className="mt-2 text-sm text-gray-500">Unavailable</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {profile.missingSkills.map((skill) => (
              <span key={skill} className="rounded-full bg-orange-50 px-3 py-1 text-xs font-medium text-orange-700">{skill}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-gray-900">Market Insights & Skill Coverage</h2>
        
        {insightsError && <p className="mt-4 text-sm text-red-600">{insightsError}</p>}
        {!insights && !insightsError && <p className="mt-4 text-sm text-gray-500">Loading insights…</p>}
        
        {insights && (
          <>
            <div className="mt-6">
              <h3 className="text-sm font-semibold text-gray-700">Market Overview</h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-600">
                Current job market strongly favors candidates with cloud, AI/ML, and modern backend skills. 
                Companies are actively hiring for roles that combine programming with cloud platforms and automation. 
                Adding in-demand skills like Go, AWS, and Kafka can significantly increase your shortlist rate. 
                Focus on practical projects that demonstrate these skills rather than just listing them.
              </p>
            </div>

            <div className="mt-6">
              <h3 className="text-sm font-semibold text-gray-700">Skills to Learn</h3>
              <p className="mt-1 text-sm text-gray-500">High-demand skills that can open more job opportunities.</p>
              {insights.top_missing_skills?.length > 0 ? (
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  {insights.top_missing_skills.map((item) => (
                    <div key={item.skill} className="rounded-lg border border-gray-100 p-4">
                      <div className="flex items-center justify-between">
                        <p className="font-medium text-gray-900">{item.skill}</p>
                        <span className="text-xs text-gray-500">{item.jobs_requiring} jobs</span>
                      </div>
                      <p className="mt-1 text-sm text-gray-600">
                        {skillReasons[item.skill] || 'Frequently appears in job requirements matching your profile.'}
                      </p>
                      {item.learning_link && (
                        <a href={item.learning_link} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-sm text-blue-600 hover:underline">
                          Free learning resource
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-4 text-sm text-gray-500">No additional skill gaps found.</p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}