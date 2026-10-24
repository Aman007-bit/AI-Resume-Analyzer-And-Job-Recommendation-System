/* Donut chart for the Skill Analysis card. Segments come from props. */
const RADIUS = 52
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export default function SkillDonut({ matched, missing, other, centerValue }) {
  const total = matched + missing + other || 1
  const segments = [
    { key: 'matched', value: matched, color: 'var(--color-success)' },
    { key: 'missing', value: missing, color: 'var(--color-warning)' },
    { key: 'other', value: other, color: 'var(--color-border-strong)' },
  ]

  let offset = 0
  return (
    <div className="donut">
      <svg viewBox="0 0 140 140" width="140" height="140" role="img" aria-label={`${centerValue}% profile match`}>
        <g transform="rotate(-90 70 70)">
          <circle cx="70" cy="70" r={RADIUS} fill="none" stroke="var(--color-border)" strokeWidth="14" />
          {segments.map((segment) => {
            const length = (segment.value / total) * CIRCUMFERENCE
            const circle = (
              <circle
                key={segment.key}
                cx="70"
                cy="70"
                r={RADIUS}
                fill="none"
                stroke={segment.color}
                strokeWidth="14"
                strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
                strokeDashoffset={-offset}
              />
            )
            offset += length
            return circle
          })}
        </g>
      </svg>
      <div className="donut__center">
        <strong>{centerValue}%</strong>
        <span>Match</span>
      </div>
    </div>
  )
}
