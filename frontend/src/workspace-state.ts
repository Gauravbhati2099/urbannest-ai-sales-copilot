import type { AuditEvent, CSVImportResult, Dashboard, Lead, Task, User } from './api'

export interface WorkspaceState {
  dashboard: Dashboard | null
  leads: Lead[]
  tasks: Task[]
  completedTasks: Task[]
  teamUsers: User[]
  auditEvents: AuditEvent[]
  unreadCount: number
  loading: boolean
  error: string
  apiConnected: boolean
  importErrors: CSVImportResult['errors']
}

export type WorkspaceAction =
  | { type: 'refresh-started' }
  | { type: 'refresh-succeeded'; dashboard: Dashboard; leads: Lead[]; tasks: Task[]; completedTasks: Task[]; teamUsers: User[]; events: AuditEvent[]; unreadCount: number }
  | { type: 'refresh-failed'; error: string }
  | { type: 'request-failed'; error: string }
  | { type: 'request-succeeded' }
  | { type: 'error-set'; error: string }
  | { type: 'error-cleared' }
  | { type: 'read-marked' }
  | { type: 'import-succeeded'; errors: CSVImportResult['errors'] }
  | { type: 'import-errors-cleared' }
  | { type: 'session-cleared' }

export const initialWorkspaceState: WorkspaceState = {
  dashboard: null,
  leads: [],
  tasks: [],
  completedTasks: [],
  teamUsers: [],
  auditEvents: [],
  unreadCount: 0,
  loading: false,
  error: '',
  apiConnected: false,
  importErrors: [],
}

export function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case 'refresh-started':
      return { ...state, loading: true, error: '' }
    case 'refresh-succeeded':
      return {
        ...state,
        dashboard: action.dashboard,
        leads: action.leads,
        tasks: action.tasks,
        completedTasks: action.completedTasks,
        teamUsers: action.teamUsers,
        auditEvents: action.events,
        unreadCount: action.unreadCount,
        loading: false,
        apiConnected: true,
      }
    case 'refresh-failed':
      return { ...state, error: action.error, loading: false, apiConnected: false }
    case 'request-failed':
      return { ...state, error: action.error, loading: false }
    case 'request-succeeded':
      return { ...state, error: '', apiConnected: true }
    case 'error-set':
      return { ...state, error: action.error }
    case 'error-cleared':
      return { ...state, error: '' }
    case 'read-marked':
      return {
        ...state,
        unreadCount: 0,
        auditEvents: state.auditEvents.map((event) => ({ ...event, is_read: true })),
      }
    case 'import-succeeded':
      return { ...state, importErrors: action.errors }
    case 'import-errors-cleared':
      return { ...state, importErrors: [] }
    case 'session-cleared':
      return initialWorkspaceState
  }
}
