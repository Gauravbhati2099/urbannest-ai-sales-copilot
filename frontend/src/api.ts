export const API_ROOT = (import.meta.env.VITE_API_BASE_URL || 'https://urbannest-ai-sales-copilot.onrender.com').replace(/\/+$/, '')
const API_PREFIX = `${API_ROOT}/api/v1`

export type LeadStatus = 'new' | 'contacted' | 'site_visit' | 'negotiation' | 'won' | 'lost'
export type LeadSource = 'website' | '99acres' | 'magicbricks' | 'instagram' | 'whatsapp' | 'walk_in' | 'manual' | 'csv_import' | 'other'
export type UserRole = 'owner' | 'co_owner' | 'manager' | 'agent'
export type TaskStatus = 'open' | 'completed' | 'cancelled'

export interface User {
  id: string
  team_id: string
  full_name: string
  email: string
  phone: string | null
  role: UserRole
  is_superuser: boolean
  can_read: boolean
  can_write: boolean
  can_delete: boolean
  can_manage_users: boolean
  is_active: boolean
  must_change_password: boolean
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface Lead {
  id: string
  team_id: string
  assigned_to: string | null
  created_by: string | null
  full_name: string
  email: string | null
  phone: string | null
  source: LeadSource
  status: LeadStatus
  budget_min_inr: number | null
  budget_max_inr: number | null
  bhk: number | null
  preferred_location: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface Activity {
  id: string
  team_id: string
  lead_id: string
  actor_id: string | null
  type: 'call' | 'note' | 'site_visit' | 'status_change' | 'email' | 'whatsapp' | 'assignment_change' | 'other'
  body: string
  occurred_at: string
}

export interface Task {
  id: string
  team_id: string
  lead_id: string
  assigned_to: string
  assigned_to_name: string
  created_by: string
  title: string
  description: string | null
  due_at: string
  status: TaskStatus
  completed_at: string | null
  created_at: string
  updated_at: string
  lead_name?: string
}

export interface DashboardTask {
  id: string
  lead_id: string
  lead_name: string
  assigned_to_name: string
  lead_status: LeadStatus
  title: string
  due_at: string
  status: TaskStatus
}

export interface Dashboard {
  timezone: string
  total_leads: number
  pipeline_counts: Record<LeadStatus, number>
  open_tasks: number
  due_today_count: number
  overdue_count: number
  due_today: DashboardTask[]
  overdue: DashboardTask[]
}

export interface AuditEvent {
  id: string
  actor_id: string | null
  actor_name: string | null
  lead_id: string | null
  entity_type: string
  entity_id: string | null
  action: string
  summary: string
  changes: Record<string, unknown> | null
  created_at: string
  is_read: boolean
}

export interface CSVImportResult {
  created_count: number
  rejected_count: number
  created_lead_ids: string[]
  errors: { row: number; message: string }[]
}

export interface UserCreateRequest {
  full_name: string
  email: string
  role: UserRole
  can_read?: boolean
  can_write?: boolean
  can_delete?: boolean
  can_manage_users?: boolean
}

export interface UserUpdateRequest {
  full_name?: string
  role?: UserRole
  is_active?: boolean
  can_read?: boolean
  can_write?: boolean
  can_delete?: boolean
  can_manage_users?: boolean
}

export interface ProfileUpdateRequest {
  phone: string | null
}

export interface UserCreatedResponse {
  user: User
  temporary_password: string
}

export interface PasswordResetResponse {
  user_id: string
  temporary_password: string
  must_change_password: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatApiDetail(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (typeof item === 'string') return [item]
      if (!isRecord(item) || typeof item.msg !== 'string') return []
      const location = Array.isArray(item.loc)
        ? item.loc.filter((part): part is string | number => typeof part === 'string' || typeof part === 'number')
          .filter((part) => part !== 'body' && part !== 'query' && part !== 'path')
          .map((part) => String(part).replaceAll('_', ' '))
          .join(' › ')
        : ''
      return [location ? `${location}: ${item.msg}` : item.msg]
    })
    if (messages.length) return messages.join('; ')
  }
  if (isRecord(detail)) {
    for (const key of ['message', 'msg', 'error']) {
      if (typeof detail[key] === 'string') return detail[key]
    }
  }
  return `The server returned an unexpected error (${status}).`
}

export async function api<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(`${API_PREFIX}${path}`, { ...init, headers })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('Can’t reach the API. Check your connection and the API CORS settings.')
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body: unknown = await response.json()
      if (isRecord(body) && 'detail' in body) message = formatApiDetail(body.detail, response.status)
    } catch {
      // Some platform errors return an empty or non-JSON response.
    }
    throw new Error(message)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function downloadAllPasswordResetCsv(token: string): Promise<Blob> {
  let response: Response
  try {
    response = await fetch(`${API_PREFIX}/users/password-reset-all`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ confirmation: 'RESET ALL' }),
      cache: 'no-store',
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('Can’t reach the API. Check your connection and the API CORS settings.')
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body: unknown = await response.json()
      if (isRecord(body) && 'detail' in body) message = formatApiDetail(body.detail, response.status)
    } catch {
      // Some platform errors return an empty or non-JSON response.
    }
    throw new Error(message)
  }

  return response.blob()
}
