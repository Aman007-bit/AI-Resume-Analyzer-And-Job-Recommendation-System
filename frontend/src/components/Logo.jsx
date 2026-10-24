import { Link } from 'react-router-dom'

export default function Logo({ onClick }) {
  return (
    <Link to="/" className="logo" aria-label="ResumeAI home" onClick={onClick}>
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden="true">
        <circle cx="14" cy="14" r="12.5" stroke="#1d4ed8" strokeWidth="1.8" />
        <path
          d="M10.5 8.5h5l2.5 2.5v8a1 1 0 0 1-1 1h-6.5a1 1 0 0 1-1-1v-9.5a1 1 0 0 1 1-1z"
          stroke="#1d4ed8"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <path d="m12 15 1.6 1.6L16.4 13" stroke="#1d4ed8" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span>ResumeAI</span>
    </Link>
  )
}
