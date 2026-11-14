import { Component, StrictMode, type ErrorInfo, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AppFailureScreen } from './ErrorScreens'

class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Unhandled UrbanNest rendering error', error, errorInfo)
  }

  componentDidMount() {
    window.addEventListener('error', this.handleWindowError)
    window.addEventListener('unhandledrejection', this.handleUnhandledRejection)
  }

  componentWillUnmount() {
    window.removeEventListener('error', this.handleWindowError)
    window.removeEventListener('unhandledrejection', this.handleUnhandledRejection)
  }

  private handleWindowError = (event: ErrorEvent) => {
    if (event.error instanceof Error) {
      this.captureError(event.error)
    } else if (event.message) {
      this.captureError(new Error(event.message))
    }
  }

  private handleUnhandledRejection = (event: PromiseRejectionEvent) => {
    const error = event.reason instanceof Error
      ? event.reason
      : new Error(String(event.reason ?? 'An unexpected request failed.'))
    this.captureError(error)
  }

  private captureError(error: Error) {
    console.error('Unhandled UrbanNest runtime error', error)
    this.setState({ error })
  }

  render() {
    if (this.state.error) {
      return <AppFailureScreen kind="frontend" fullScreen onRetry={() => window.location.reload()} />
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <AppErrorBoundary>
    <StrictMode>
      <App />
    </StrictMode>
  </AppErrorBoundary>,
)
