import { CircleAlert, RefreshCw } from 'lucide-react'

export type FailureKind = 'server' | 'frontend'

export function AppFailureScreen({
  kind,
  onRetry,
  fullScreen = false,
}: {
  kind: FailureKind
  onRetry: () => void
  fullScreen?: boolean
}) {
  const isServerFailure = kind === 'server'

  return (
    <section
      className={`app-failure-screen ${fullScreen ? 'app-failure-full' : 'app-failure-inline'}`}
      role="alert"
      aria-live="assertive"
    >
      <div className="app-failure-card">
        <span className="app-failure-icon"><CircleAlert size={22} /></span>
        <p className="eyebrow">{isServerFailure ? 'Service unavailable' : 'Unexpected error'}</p>
        <h1>{isServerFailure ? 'We couldn’t load your workspace' : 'Something went wrong'}</h1>
        <p className="app-failure-description">
          {isServerFailure
            ? 'Check your connection and try again in a moment.'
            : 'The app hit an unexpected error. Reload the workspace to continue.'}
        </p>
        <button className="button button-primary app-failure-retry" onClick={onRetry}>
          <RefreshCw size={16} />
          {isServerFailure ? 'Try again' : 'Reload workspace'}
        </button>
      </div>
    </section>
  )
}
