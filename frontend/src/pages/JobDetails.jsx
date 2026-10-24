import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ErrorState, LoadingState } from '../components/PageState.jsx'
import useAsyncData from '../hooks/useAsyncData.js'
import { getJobById, isJobSaved, toggleSavedJob } from '../services/jobService.js'

export default function JobDetails() {
  const { id } = useParams()
  const { data: job, loading, error } = useAsyncData(getJobById, id)

  if (loading) return <LoadingState text="Loading job..." />
  if (error || !job) {
    return (
      <ErrorState
        title="Job not found."
        text="This job may have been removed or the link is incorrect."
        actionLabel="Back to Jobs"
        actionTo="/jobs"
      />
    )
  }

  return <JobDetailsView key={job.id} job={job} />
}

function JobDetailsView({ job }) {
  const [saved, setSaved] = useState(() => isJobSaved(job.id))
  const match = job.matchPercentage ?? job.matchScore ?? job.score ?? null

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <Link to="/jobs" className="inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-900">
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        Back to Jobs
      </Link>

      <div className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50">
              <svg className="h-5 w-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-semibold text-gray-900">{job.title}</h1>
              <p className="text-sm text-gray-500">{job.company}</p>
              <p className="mt-1 text-xs text-gray-400">{job.location} · {job.workMode || 'on_site'}</p>
            </div>
          </div>
          {match != null && (
            <span className="whitespace-nowrap rounded-full bg-green-50 px-3 py-1 text-sm font-semibold text-green-700">
              {match}% Match
            </span>
          )}
        </div>

        <div className="mt-4 flex gap-2">
          {job.applyUrl ? (
            <a href={job.applyUrl} target="_blank" rel="noopener noreferrer" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
              Apply Now
            </a>
          ) : (
            <button disabled className="cursor-not-allowed rounded-lg bg-gray-200 px-4 py-2 text-sm font-semibold text-gray-500">
              Apply Now
            </button>
          )}
          <button
            onClick={() => setSaved(toggleSavedJob(job.id))}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <svg className="h-4 w-4" fill={saved ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
            {saved ? 'Saved' : 'Save Job'}
          </button>
        </div>
        {!job.applyUrl && <p className="mt-2 text-xs text-gray-500">The employer hasn't shared an apply link for this role yet.</p>}
      </div>

      <div className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-gray-900">Skills Match</h2>
        <div className="mt-4 grid gap-6 sm:grid-cols-2">
          <div>
            <h3 className="text-sm font-medium text-gray-700">Matched Skills</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {job.matchedSkills?.length > 0 ? job.matchedSkills.map((skill) => (
                <span key={skill} className="rounded-full bg-green-50 px-3 py-1 text-xs font-medium text-green-700">{skill}</span>
              )) : <p className="text-sm text-gray-500">None</p>}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-medium text-gray-700">Missing Skills</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {job.missingSkills?.length > 0 ? job.missingSkills.map((skill) => (
                <span key={skill} className="rounded-full bg-orange-50 px-3 py-1 text-xs font-medium text-orange-700">{skill}</span>
              )) : <p className="text-sm text-gray-500">You have all the skills listed for this role.</p>}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-base font-semibold text-gray-900">Job Description</h2>
        {job.description && <p className="mt-3 text-sm leading-relaxed text-gray-600">{job.description}</p>}
        {job.requirements?.length > 0 && (
          <>
            <h3 className="mt-4 text-sm font-medium text-gray-700">Requirements</h3>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-600">
              {job.requirements.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}