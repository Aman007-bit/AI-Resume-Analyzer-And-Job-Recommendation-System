import Button from './Button.jsx'

export function LoadingState({ text = 'Loading...' }) {
  return (
    <div className="page-state" role="status" aria-live="polite">
      <span className="spinner spinner--lg" aria-hidden="true" />
      <p>{text}</p>
    </div>
  )
}

export function ErrorState({ title, text, actionLabel, actionTo }) {
  return (
    <div className="page-state" role="alert">
      <h1 className="page-state__title">{title}</h1>
      {text && <p>{text}</p>}
      {actionLabel && actionTo && (
        <Button to={actionTo} variant="outline">
          {actionLabel}
        </Button>
      )}
    </div>
  )
}
