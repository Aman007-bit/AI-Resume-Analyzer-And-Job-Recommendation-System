import { useEffect, useState } from 'react'
import { apiRequest } from '../services/api.js'
import JobCard from '../components/JobCard.jsx'
import { LoadingState, ErrorState } from '../components/PageState.jsx'

const CATEGORIES = [
  { id: 'all', label: 'All' },
  { id: 'tech', label: 'Tech' },
  { id: 'business', label: 'Business' },
  { id: 'design', label: 'Design' },
  { id: 'marketing', label: 'Marketing' },
  { id: 'other', label: 'Other' },
]

export default function AllJobs() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [category, setCategory] = useState('all')
  const [search, setSearch] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const params = new URLSearchParams({
      page: String(page),
      limit: '20',
      category,
      search,
    })
    apiRequest(`/api/jobs?${params}`)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load jobs')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [page, category, search])

  if (loading) return <LoadingState text="Loading all jobs..." />
  if (error) return <ErrorState title="Could not load jobs" text={error} />

  const { jobs = [], pages = 1, total = 0 } = data || {}

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900">All Jobs</h1>
      <p className="mt-1 text-sm text-gray-500">{total} jobs in database</p>

      <div className="mt-4 flex flex-wrap gap-2">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            onClick={() => { setCategory(c.id); setPage(1) }}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
              category === c.id
                ? 'bg-blue-600 text-white'
                : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      <div className="relative mt-4 max-w-md">
        <svg className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="search"
          placeholder="Search title or company..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>

      <ul className="mt-6 space-y-3">
        {jobs.map((job) => (
          <li key={job.id}>
            <JobCard job={{
              id: String(job.id),
              title: job.title,
              company: job.company,
              location: job.location,
              workMode: job.work_mode,
              description: job.description,
              requirements: job.skills || [],
              sourceUrl: job.source_url,
              sourceName: job.source_name,
            }} />
          </li>
        ))}
      </ul>

      {pages > 1 && (
        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-sm text-gray-600">Page {page} of {pages}</span>
          <button
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}