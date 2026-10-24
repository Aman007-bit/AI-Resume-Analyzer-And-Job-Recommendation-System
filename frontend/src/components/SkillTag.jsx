/* tone: 'blue' (detected / matched) | 'neutral' | 'orange' (missing) */
export default function SkillTag({ children, tone = 'blue' }) {
  return <span className={`skill-tag skill-tag--${tone}`}>{children}</span>
}
