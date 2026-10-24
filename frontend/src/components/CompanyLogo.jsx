 import { getCompanyColor } from '../utils/format.js'

/* Letter tile used in place of company logos until real logo URLs exist. */
export default function CompanyLogo({ company, size = 'md' }) {
  return (
    <div
      className={`company-logo company-logo--${size}`}
      style={{ backgroundColor: getCompanyColor(company) }}
      aria-hidden="true"
    >
      {company.slice(0, 1).toUpperCase()}
    </div>
  )
}
