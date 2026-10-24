import { Link } from 'react-router-dom'

export default function JobCard({ job }) {
  const match = job.matchPercentage ?? job.matchScore ?? job.score ?? job.match_percentage ?? null
  const workMode = job.workMode || 'on_site'

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-4">
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
            <p className="text-xs text-gray-400">{job.location} · {workMode}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {match != null && (
            <span className="rounded-full bg-green-50 px-2.5 py-1 text-xs font-semibold text-green-700">
              {match}% match
            </span>
          )}
          <Link
            to={`/jobs/${job.id}`}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            View Details
          </Link>
        </div>
      </div>
    </div>
  )
}