import { Link } from 'react-router-dom'

function Icon({ d, className = 'h-5 w-5' }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  )
}

export default function About() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <div className="mb-12 text-center">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-600">
          <Icon d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" className="h-8 w-8 text-white" />
        </div>
        <h1 className="text-4xl font-bold text-gray-900">About ResumeAI</h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-gray-600">
          An AI-powered platform that analyzes your resume, extracts your skills, and recommends jobs that match your profile — helping you land the right opportunity faster.
        </p>
      </div>

      <div className="mb-8 rounded-xl border border-gray-200 bg-white p-8">
        <h2 className="mb-6 text-xl font-semibold text-gray-900">What it does</h2>
        <div className="grid gap-6 sm:grid-cols-2">
          <div className="flex gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50">
              <Icon d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" className="text-blue-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Resume Analysis</h3>
              <p className="mt-1 text-sm text-gray-600">
                Upload your resume in PDF or DOCX format and get an instant AI-powered analysis with a comprehensive score.
              </p>
            </div>
          </div>
          <div className="flex gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-purple-50">
              <Icon d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" className="text-purple-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Skill Matching</h3>
              <p className="mt-1 text-sm text-gray-600">
                See exactly which skills you have and which ones you're missing for each job opportunity.
              </p>
            </div>
          </div>
          <div className="flex gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-green-50">
              <Icon d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" className="text-green-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Job Recommendations</h3>
              <p className="mt-1 text-sm text-gray-600">
                Get personalized job recommendations based on your extracted skills and match percentage.
              </p>
            </div>
          </div>
          <div className="flex gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-orange-50">
              <Icon d="M13 10V3L4 14h7v7l9-11h-7z" className="text-orange-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Career Insights</h3>
              <p className="mt-1 text-sm text-gray-600">
                Track your profile strength and discover areas to improve for better job matches over time.
              </p>
            </div>
          </div>
        </div>
      </div>


      <div className="grid gap-6 sm:grid-cols-3">
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50">
            <Icon d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" className="text-blue-600" />
          </div>
          <h3 className="text-sm font-semibold text-gray-900">Privacy First</h3>
          <p className="mt-1 text-xs text-gray-600">Your resume data is processed securely.</p>
        </div>
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-purple-50">
            <Icon d="M13 10V3L4 14h7v7l9-11h-7z" className="text-purple-600" />
          </div>
          <h3 className="text-sm font-semibold text-gray-900">Fast & Accurate</h3>
          <p className="mt-1 text-xs text-gray-600">Instant analysis with AI-powered precision.</p>
        </div>
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-green-50">
            <Icon d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" className="text-green-600" />
          </div>
          <h3 className="text-sm font-semibold text-gray-900">Tailored Matches</h3>
          <p className="mt-1 text-xs text-gray-600">Recommendations based on your unique skills.</p>
        </div>
      </div>

      <div className="mt-12 text-center">
        <Link to="/upload" className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-blue-700">
          Get Started
          <Icon d="M14 5l7 7m0 0l-7 7m7-7H3" className="h-4 w-4" />
        </Link>
      </div>
    </div>
  )
}