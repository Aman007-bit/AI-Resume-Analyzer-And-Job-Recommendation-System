import { useState } from 'react'
import Icon from './Icon.jsx'

/* Labelled input with a leading icon, optional show/hide toggle for passwords,
   and an accessible error message. */
export default function FormField({
  id,
  label,
  type = 'text',
  icon,
  error,
  value,
  onChange,
  placeholder,
  autoComplete,
  disabled = false,
}) {
  const [revealed, setRevealed] = useState(false)
  const isPassword = type === 'password'
  const errorId = `${id}-error`

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <div className={`field__control${error ? ' field__control--error' : ''}`}>
        {icon && <Icon name={icon} size={16} className="field__icon" />}
        <input
          id={id}
          name={id}
          className="field__input"
          type={isPassword && revealed ? 'text' : type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          autoComplete={autoComplete}
          disabled={disabled}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? errorId : undefined}
        />
        {isPassword && (
          <button
            type="button"
            className="field__toggle"
            onClick={() => setRevealed((shown) => !shown)}
            aria-label={revealed ? 'Hide password' : 'Show password'}
            aria-pressed={revealed}
          >
            <Icon name={revealed ? 'eyeOff' : 'eye'} size={16} />
          </button>
        )}
      </div>
      {error && (
        <p id={errorId} className="field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
