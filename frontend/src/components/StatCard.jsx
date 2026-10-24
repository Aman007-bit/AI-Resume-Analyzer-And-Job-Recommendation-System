/* One number in the dashboard's top row. Optional progress bar (0-100). */
export default function StatCard({ label, value, tone = 'default', progress }) {
  return (
    <div className="stat-card">
      <p className="stat-card__label">{label}</p>
      <p className={`stat-card__value stat-card__value--${tone}`}>{value}</p>
      {typeof progress === 'number' && (
        <div className="progress progress--thin" aria-hidden="true">
          <div className="progress__fill" style={{ width: `${progress}%` }} />
        </div>
      )}
    </div>
  )
}
