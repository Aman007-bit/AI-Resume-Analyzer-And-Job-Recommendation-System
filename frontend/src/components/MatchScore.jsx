function getTone(score) {
  if (score >= 70) return 'good'
  if (score >= 50) return 'fair'
  return 'low'
}

/* "86% Match" with a progress bar underneath. */
export default function MatchScore({ score, label = 'Match', className = '' }) {
  const value = Math.max(0, Math.min(100, Math.round(score)))
  return (
    <div className={`match-score match-score--${getTone(value)} ${className}`.trim()}>
      <span className="match-score__label">
        <strong>{value}%</strong> {label}
      </span>
      <div
        className="progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        aria-label={`${value}% ${label}`}
      >
        <div className="progress__fill" style={{ width: `${value}%` }} />
      </div>
    </div>
  )
}
