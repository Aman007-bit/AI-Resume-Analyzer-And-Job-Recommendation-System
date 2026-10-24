import { useMemo, useState } from 'react'
import Button from '../components/Button.jsx'
import JobCard from '../components/JobCard.jsx'
import { ErrorState, LoadingState } from '../components/PageState.jsx'
import useAsyncData from '../hooks/useAsyncData.js'
import { getRecommendationResult } from '../services/jobService.js'

const ALL = 'all'

function SelectFilter({ id, label, value, onChange, options }) {
  return (
    <div className="relative">
      <label htmlFor={id} className="sr-only">{label}</label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full appearance-none rounded-lg border border-gray-300 bg-white px-3 py-2 pr-8 text-sm text-gray-700 focus:border-blue-500 focus:outline-none"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
      </svg>
    </div>
  )
}

export default function RecommendedJobs() {
  const { data: recommendationResult, loading, error } = useAsyncData(getRecommendationResult)
  const jobs = recommendationResult?.recommendations
  const availability = recommendationResult?.availability
  const [query, setQuery] = useState('')
  const [location, setLocation] = useState(ALL)
  const [workMode, setWorkMode] = useState(ALL)

  const locationOptions = useMemo(() => {
    const names = [...new Set((jobs ?? []).map((job) => job.location))].sort()
    return [{ value: ALL, label: 'All Locations' }, ...names.map((name) => ({ value: name, label: name }))]
  }, [jobs])

  const workModeOptions = [
    { value: ALL, label: 'Work mode' },
    { value: 'remote', label: 'Remote' },
    { value: 'on_site', label: 'On site' },
    { value: 'hybrid', label: 'Hybrid' },
    { value: 'unknown', label: 'Not specified' },
  ]

  const visibleJobs = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (jobs ?? []).filter((job) => {
      if (location !== ALL && job.location !== location) return false
      if (workMode !== ALL && job.workMode !== workMode) return false
      if (!needle) return true
      return [job.title, job.company, job.location, ...job.matchedSkills]
        .join(' ')
        .toLowerCase()
        .includes(needle)
    })
  }, [jobs, query, location, workMode])

  const filtersActive = query || location !== ALL || workMode !== ALL

  function clearFilters() {
    setQuery('')
    setLocation(ALL)
    setWorkMode(ALL)
  }

  if (loading) return <LoadingState text="Finding jobs for you..." />
  if (error || !jobs) {
    return (
      <ErrorState
        title="We couldn't load your jobs."
        text="Please try again in a moment."
        actionLabel="Back to Dashboard"
        actionTo="/dashboard"
      />
    )
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900">Recommended Jobs</h1>
      <p className="mt-1 text-sm text-gray-500">Jobs that match your skills and experience</p>

      <div className="mt-6 rounded-xl border border-gray-200 bg-white p-4">
        <div className="relative">
          <svg className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <label htmlFor="job-search" className="sr-only">Search jobs and companies</label>
          <input
            id="job-search"
            type="search"
            placeholder="Search jobs, companies..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <SelectFilter id="filter-location" label="Location" value={location} onChange={setLocation} options={locationOptions} />
          <SelectFilter id="filter-work-mode" label="Work mode" value={workMode} onChange={setWorkMode} options={workModeOptions} />
        </div>
      </div>

      <p className="mt-4 text-sm text-gray-600">
        {visibleJobs.length} {visibleJobs.length === 1 ? 'job' : 'jobs'} found
      </p>

      {visibleJobs.length > 0 ? (
        <ul className="mt-4 space-y-3">
          {visibleJobs.map((job) => (
            <li key={job.id}>
              <JobCard job={job} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-4 rounded-xl border border-gray-200 bg-white p-6 text-center">
          <p className="text-sm text-gray-600">
            {filtersActive
              ? 'No jobs match your search.'
              : availability?.status === 'provider_authorization_required'
                ? 'Job listings are stored, but recommendations are disabled while provider data-use authorization is pending.'
                : availability?.status === 'no_jobs_available'
                  ? 'No job listings are currently available.'
                  : availability?.status === 'no_relevant_matches'
                    ? 'No relevant matches were found for this resume.'
                    : 'No recommendations are currently available.'}
          </p>
          {filtersActive && (
            <Button variant="outline" size="sm" onClick={clearFilters} className="mt-3">
              Clear filters
            </Button>
          )}
        </div>
      )}
    </div>
  )
}