import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type FormEvent } from 'react'
import {
  Activity as ActivityIcon,
  ArrowUpRight,
  Bell,
  CalendarDays,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  Eye,
  EyeOff,
  LayoutDashboard,
  Network,
  KeyRound,
  LogOut,
  MapPin,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RotateCcw,
  RefreshCw,
  Search,
  Sun,
  Upload,
  UserPlus,
  Users,
  UserRound,
  X,
} from 'lucide-react'
import {
  ApiError,
  api,
  downloadAllPasswordResetCsv,
  type Activity,
  type AuditEvent,
  type Dashboard,
  type CSVImportResult,
  type Lead,
  type LeadAssignee,
  type LeadCreateRequest,
  type LeadDuplicateCheck,
  type LeadSource,
  type LeadStatus,
  type LocationSelection,
  type LoginResponse,
  type OrgChartMember,
  type PasswordResetResponse,
  type Task,
  type User,
  type UserCreateRequest,
  type UserCreatedResponse,
  type ProfileUpdateRequest,
  type UserRole,
  type UserUpdateRequest,
} from './api'
import { LocationAutocomplete } from './LocationAutocomplete'
import { PhoneNumberInput } from './PhoneNumberInput'
import { normalizeEmail, normalizeName, normalizePhone, splitStoredPhone, validateEmail, validateName } from './form-normalization'
import { initialWorkspaceState, workspaceReducer } from './workspace-state'
import { AppFailureScreen } from './ErrorScreens'
import { CookieConsentBanner, PrivacyPolicyPage, StoragePreferencesPage, type LegalPageKind, type StorageConsent } from './PrivacyPages'
import { inspectLeadImportFile, LEAD_IMPORT_COLUMNS, type LeadImportPreflight } from './lead-import'
import './App.css'

type Page = 'overview' | 'leads' | 'tasks' | 'activity' | 'team' | 'org-chart' | 'profile'
type Theme = 'light' | 'dark'
type LeadSortKey = 'name' | 'contact' | 'requirement' | 'source' | 'stage' | 'added'
type SortDirection = 'ascending' | 'descending'

const STORAGE_CONSENT_KEY = 'urbannest_storage_consent'
const THEME_COOKIE = 'urbannest_theme'
const SIDEBAR_COOKIE = 'urbannest_sidebar_collapsed'
const WORKSPACE_PAGE_KEY = 'urbannest_current_page'

function readCookie(name: string) {
  const prefix = `${name}=`
  return document.cookie
    .split(';')
    .map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith(prefix))
    ?.slice(prefix.length) ?? null
}

function writePreferenceCookie(name: string, value: string) {
  const secure = window.location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${name}=${value}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`
}

function clearPreferenceCookie(name: string) {
  const secure = window.location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax${secure}`
}

function readStorageConsent(): StorageConsent | null {
  const consent = readCookie(STORAGE_CONSENT_KEY) ?? localStorage.getItem(STORAGE_CONSENT_KEY)
  return consent === 'all' || consent === 'essential' ? consent : null
}

function readWorkspacePage(): Page {
  const page = sessionStorage.getItem(WORKSPACE_PAGE_KEY)
  switch (page) {
    case 'overview':
    case 'leads':
    case 'tasks':
    case 'activity':
    case 'team':
    case 'org-chart':
    case 'profile':
      return page
    default:
      return 'overview'
  }
}

function readLegalPage(): LegalPageKind | null {
  if (window.location.hash === '#privacy-policy') return 'privacy'
  if (window.location.hash === '#cookie-settings') return 'cookies'
  return null
}

type ConfirmationRequest = {
  title: string
  message: string
  confirmLabel: string
  onConfirm: () => void | Promise<void>
}

const stages: { value: LeadStatus; label: string; tone: string }[] = [
  { value: 'new', label: 'New', tone: 'slate' },
  { value: 'contacted', label: 'Contacted', tone: 'blue' },
  { value: 'site_visit', label: 'Site visit', tone: 'violet' },
  { value: 'negotiation', label: 'Negotiation', tone: 'amber' },
  { value: 'won', label: 'Won', tone: 'green' },
  { value: 'lost', label: 'Lost', tone: 'rose' },
]

const sourceLabels: Record<LeadSource, string> = {
  website: 'Website',
  '99acres': '99acres',
  magicbricks: 'MagicBricks',
  instagram: 'Instagram',
  whatsapp: 'WhatsApp',
  walk_in: 'Walk-in',
  manual: 'Manual',
  csv_import: 'CSV import',
  other: 'Other',
}
const CURRENT_YEAR = new Date().getFullYear()

function initials(name: string | null | undefined) {
  return (name ?? '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0] ?? '')
    .join('')
    .toUpperCase()
}

function taskAssigneeName(
  task: Pick<Task, 'assigned_to' | 'assigned_to_name'>,
  users: User[],
  currentUser: User,
) {
  return task.assigned_to_name
    || users.find((user) => user.id === task.assigned_to)?.full_name
    || (task.assigned_to === currentUser.id ? currentUser.full_name : 'Team member')
}

function formatCurrency(value: number | null | undefined) {
  if (value == null) return '—'
  if (value >= 10_000_000) return `₹${(value / 10_000_000).toFixed(value % 10_000_000 ? 1 : 0)}Cr`
  if (value >= 100_000) return `₹${(value / 100_000).toFixed(value % 100_000 ? 1 : 0)}L`
  return `₹${new Intl.NumberFormat('en-IN').format(value)}`
}

function budgetRange(lead: Lead) {
  if (lead.budget_min_inr == null && lead.budget_max_inr == null) return 'Budget not set'
  if (lead.budget_min_inr != null && lead.budget_max_inr != null) {
    return `${formatCurrency(lead.budget_min_inr)} – ${formatCurrency(lead.budget_max_inr)}`
  }
  return formatCurrency(lead.budget_min_inr ?? lead.budget_max_inr)
}

function formatDate(value: string, options?: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat('en-IN', options ?? { day: 'numeric', month: 'short' }).format(
    new Date(value),
  )
}

function relativeDate(value: string) {
  const date = new Date(value)
  const today = new Date()
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const days = Math.round((startDate - startToday) / 86_400_000)
  if (days === 0) return `Today, ${formatDate(value, { hour: 'numeric', minute: '2-digit' })}`
  if (days === -1) return 'Yesterday'
  return formatDate(value, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

function stageFor(status: LeadStatus) {
  return stages.find((stage) => stage.value === status) ?? stages[0]
}

function compareLeads(left: Lead, right: Lead, sortKey: LeadSortKey) {
  switch (sortKey) {
    case 'name':
      return left.full_name.localeCompare(right.full_name, undefined, { sensitivity: 'base' })
    case 'contact':
      return `${left.email ?? ''} ${left.phone ?? ''}`.localeCompare(`${right.email ?? ''} ${right.phone ?? ''}`, undefined, { sensitivity: 'base' })
    case 'requirement':
      return (left.bhk ?? 0) - (right.bhk ?? 0) || (left.budget_min_inr ?? 0) - (right.budget_min_inr ?? 0)
    case 'source':
      return sourceLabels[left.source].localeCompare(sourceLabels[right.source], undefined, { sensitivity: 'base' })
    case 'stage':
      return stages.findIndex((stage) => stage.value === left.status) - stages.findIndex((stage) => stage.value === right.status)
    case 'added':
      return Date.parse(left.created_at) - Date.parse(right.created_at)
  }
}

function taskIsOverdue(dueAt: string, now: number) {
  return new Date(dueAt).getTime() < now
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('urbannest_token') ?? '')
  const [renderTime] = useState(() => new Date())
  const [storageConsent, setStorageConsent] = useState<StorageConsent | null>(readStorageConsent)
  const [theme, setTheme] = useState<Theme>(() => storageConsent === 'all'
    && (readCookie(THEME_COOKIE) ?? localStorage.getItem(THEME_COOKIE)) === 'dark' ? 'dark' : 'light')
  const leadSearchRef = useRef<HTMLInputElement>(null)
  const refreshControllerRef = useRef<AbortController | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [authReady, setAuthReady] = useState(() => !sessionStorage.getItem('urbannest_token'))
  const [authError, setAuthError] = useState(false)
  const [authRetryCount, setAuthRetryCount] = useState(0)
  const [legalPage, setLegalPage] = useState<LegalPageKind | null>(readLegalPage)
  const [page, setPage] = useState<Page>(readWorkspacePage)
  const [orgChartMembers, setOrgChartMembers] = useState<OrgChartMember[]>([])
  const [workspace, dispatch] = useReducer(workspaceReducer, initialWorkspaceState)
  const { dashboard, leads, tasks, completedTasks, teamUsers, auditEvents, unreadCount, loading, error, apiConnected, importErrors } = workspace
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => storageConsent === 'all'
    && (readCookie(SIDEBAR_COOKIE) ?? localStorage.getItem(SIDEBAR_COOKIE)) === 'true')
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [taskFilter, setTaskFilter] = useState<'all' | 'today' | 'overdue' | 'completed'>('all')
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null)
  const [showCreateLead, setShowCreateLead] = useState(false)
  const [showNotifications, setShowNotifications] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)
  const [confirmation, setConfirmation] = useState<ConfirmationRequest | null>(null)
  const [notice, setNotice] = useState('')
  const [temporaryPassword, setTemporaryPassword] = useState<{ email: string; password: string } | null>(null)
  const setError = useCallback((message: string) => {
    dispatch(message ? { type: 'error-set', error: message } : { type: 'error-cleared' })
  }, [])

  const openLegalPage = (nextPage: LegalPageKind) => {
    window.location.hash = nextPage === 'privacy' ? 'privacy-policy' : 'cookie-settings'
    setLegalPage(nextPage)
  }

  const closeLegalPage = () => {
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
    setLegalPage(null)
  }

  const chooseStorageConsent = (choice: StorageConsent) => {
    writePreferenceCookie(STORAGE_CONSENT_KEY, choice)
    localStorage.removeItem(STORAGE_CONSENT_KEY)
    if (choice === 'essential') {
      clearPreferenceCookie(THEME_COOKIE)
      clearPreferenceCookie(SIDEBAR_COOKIE)
      localStorage.removeItem(THEME_COOKIE)
      localStorage.removeItem(SIDEBAR_COOKIE)
    }
    setStorageConsent(choice)
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    if (storageConsent === 'all') writePreferenceCookie(THEME_COOKIE, theme)
    localStorage.removeItem(THEME_COOKIE)
  }, [storageConsent, theme])

  useEffect(() => {
    if (storageConsent === 'all') writePreferenceCookie(SIDEBAR_COOKIE, String(sidebarCollapsed))
    localStorage.removeItem(SIDEBAR_COOKIE)
  }, [sidebarCollapsed, storageConsent])

  useEffect(() => {
    if (storageConsent !== null) writePreferenceCookie(STORAGE_CONSENT_KEY, storageConsent)
    localStorage.removeItem(STORAGE_CONSENT_KEY)
  }, [storageConsent])

  useEffect(() => {
    if (token && user) sessionStorage.setItem(WORKSPACE_PAGE_KEY, page)
  }, [page, token, user])

  useEffect(() => {
    if (!showUserMenu) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShowUserMenu(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [showUserMenu])

  useEffect(() => {
    const syncLegalPage = () => setLegalPage(readLegalPage())
    window.addEventListener('hashchange', syncLegalPage)
    return () => window.removeEventListener('hashchange', syncLegalPage)
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => () => refreshControllerRef.current?.abort(), [])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSelectedLead(null)
        setShowCreateLead(false)
        setShowNotifications(false)
        setMobileNavOpen(false)
      }

      const target = event.target
      const isEditing = target instanceof HTMLElement
        && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
      if (event.key === '/' && page === 'leads' && !isEditing) {
        event.preventDefault()
        leadSearchRef.current?.focus()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [page])

  const setSession = useCallback((response: LoginResponse) => {
    sessionStorage.setItem('urbannest_token', response.access_token)
    setToken(response.access_token)
    setUser(response.user)
    setAuthError(false)
  }, [])

  const signOut = useCallback(() => {
    sessionStorage.removeItem('urbannest_token')
    setToken('')
    setUser(null)
    setTemporaryPassword(null)
    setAuthReady(true)
    setAuthError(false)
    refreshControllerRef.current?.abort()
    dispatch({ type: 'session-cleared' })
    sessionStorage.removeItem(WORKSPACE_PAGE_KEY)
    setPage('overview')
  }, [])

  useEffect(() => {
    if (!token) {
      return
    }
    let active = true
    api<User>('/auth/me', token)
      .then((currentUser) => {
        if (active) {
          setUser(currentUser)
          setAuthError(false)
        }
      })
      .catch((requestError: unknown) => {
        if (!active) return
        if (requestError instanceof ApiError && requestError.status === 401) {
          signOut()
          return
        }
        console.error('Could not restore the UrbanNest session', requestError)
        setAuthError(true)
      })
      .finally(() => {
        if (active) setAuthReady(true)
      })
    return () => {
      active = false
    }
  }, [authRetryCount, signOut, token])

  const canReadWorkspace = !user
    || user.is_superuser
    || user.role !== 'co_owner'
    || user.can_read
  const canWriteWorkspace = !user
    || user.is_superuser
    || user.role !== 'co_owner'
    || user.can_write
  const canManageTeam = Boolean(user && (
    user.is_superuser
    || user.role === 'owner'
    || user.role === 'manager'
    || (user.role === 'co_owner' && user.can_manage_users)
  ))
  const activePage = !canReadWorkspace && page !== 'team' && page !== 'org-chart' && page !== 'profile'
    ? canManageTeam ? 'team' : 'profile'
    : page

  const refresh = useCallback(async () => {
    if (!token) return
    refreshControllerRef.current?.abort()
    const controller = new AbortController()
    refreshControllerRef.current = controller
    dispatch({ type: 'refresh-started' })
    try {
      if (!canReadWorkspace) {
        const [users, orgChart] = await Promise.all([
          canManageTeam
            ? api<User[]>('/users?limit=100', token, { signal: controller.signal })
            : Promise.resolve([]),
          page === 'org-chart'
            ? api<OrgChartMember[]>('/users/org-chart', token, { signal: controller.signal })
            : Promise.resolve(null),
        ])
        if (orgChart) setOrgChartMembers(orgChart)
        dispatch({
          type: 'refresh-succeeded',
          dashboard: null,
          leads: [],
          tasks: [],
          completedTasks: [],
          teamUsers: users,
          events: [],
          unreadCount: 0,
        })
        return
      }
      const params = new URLSearchParams({ limit: '100' })
      if (debouncedQuery) params.set('q', debouncedQuery)
      if (statusFilter) params.set('status', statusFilter)
      const requestOptions = { signal: controller.signal }
      const usersRequest = canManageTeam
        ? api<User[]>('/users?limit=100', token, requestOptions)
        : Promise.resolve([])
      const orgChartRequest = page === 'org-chart'
        ? api<OrgChartMember[]>('/users/org-chart', token, requestOptions)
        : Promise.resolve(null)
      const [summary, leadRows, taskRows, completedTaskRows, feed, users, orgChart] = await Promise.all([
        api<Dashboard>('/dashboard/summary', token, requestOptions),
        api<Lead[]>(`/leads?${params.toString()}`, token, requestOptions),
        api<Task[]>('/tasks?limit=100', token, requestOptions),
        api<Task[]>('/tasks?status=completed&limit=100', token, requestOptions),
        api<{ events: AuditEvent[]; unread_count: number }>('/audit/events?limit=8', token, requestOptions),
        usersRequest,
        orgChartRequest,
      ])
      if (orgChart) setOrgChartMembers(orgChart)
      dispatch({
        type: 'refresh-succeeded',
        dashboard: summary,
        leads: leadRows,
        tasks: taskRows,
        completedTasks: completedTaskRows,
        teamUsers: users,
        events: feed.events,
        unreadCount: feed.unread_count,
      })
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === 'AbortError') return
      if (requestError instanceof ApiError && requestError.status === 401) {
        signOut()
        return
      }
      console.error('Could not refresh the UrbanNest workspace', requestError)
      dispatch({ type: 'refresh-failed', error: getErrorMessage(requestError) })
    } finally {
      if (refreshControllerRef.current === controller) refreshControllerRef.current = null
    }
  }, [canManageTeam, canReadWorkspace, debouncedQuery, page, signOut, statusFilter, token])

  useEffect(() => {
    // eslint-disable-next-line react/set-state-in-effect -- Synchronizes server data with auth and search filters.
    if (user && !user.must_change_password) void refresh()
  }, [refresh, user])

  const pageTitle = {
    overview: 'Overview',
    leads: 'Leads',
    tasks: 'Follow-ups',
    activity: 'Activity',
    team: 'Team',
    'org-chart': 'Org chart explorer',
    profile: 'My profile',
  }[activePage]

  const visibleTasks = useMemo(() => {
    if (taskFilter === 'completed') return completedTasks
    if (taskFilter === 'today') return dashboard?.due_today ?? []
    if (taskFilter === 'overdue') return dashboard?.overdue ?? []
    return tasks
  }, [completedTasks, dashboard, taskFilter, tasks])

  const updateLeadStatus = async (lead: Lead, status: LeadStatus) => {
    const updated = await api<Lead>(`/leads/${lead.id}`, token, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    })
    setNotice(`${lead.full_name} moved to ${stageFor(status).label.toLowerCase()}.`)
    await refresh()
    if (selectedLead?.id === lead.id) setSelectedLead(updated)
  }

  const requestLeadStatusUpdate = (lead: Lead, status: LeadStatus) => {
    setConfirmation({
      title: `Move ${lead.full_name} to ${stageFor(status).label.toLowerCase()}?`,
      message: `This updates the lead’s pipeline stage from ${stageFor(lead.status).label.toLowerCase()} to ${stageFor(status).label.toLowerCase()}.`,
      confirmLabel: 'Update stage',
      onConfirm: () => updateLeadStatus(lead, status),
    })
  }

  const completeTask = async (task: Pick<Task, 'id'>) => {
    await api<Task>(`/tasks/${task.id}`, token, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'completed' }),
    })
    setNotice('Follow-up marked complete.')
    dispatch({ type: 'request-succeeded' })
    await refresh()
  }

  const requestCompleteTask = (task: Pick<Task, 'id' | 'title'>) => {
    setConfirmation({
      title: 'Mark follow-up complete?',
      message: `“${task.title}” will move to your completed follow-ups.`,
      confirmLabel: 'Mark complete',
      onConfirm: () => completeTask(task),
    })
  }

  const openLeadById = async (leadId: string) => {
    const existing = leads.find((lead) => lead.id === leadId)
    if (existing) {
      setSelectedLead(existing)
      return
    }
    try {
      setSelectedLead(await api<Lead>(`/leads/${leadId}`, token))
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    }
  }

  const importCsv = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const result = await api<CSVImportResult>('/leads/import', token, { method: 'POST', body: formData })
      dispatch({ type: 'import-succeeded', errors: result.errors })
      setNotice(`Imported ${result.created_count} lead${result.created_count === 1 ? '' : 's'}${result.rejected_count ? `; ${result.rejected_count} row${result.rejected_count === 1 ? '' : 's'} need attention` : ''}.`)
      await refresh()
    } catch (requestError) {
      throw new Error(getErrorMessage(requestError))
    }
  }

  const markRead = async () => {
    try {
      await api('/audit/read', token, { method: 'POST' })
      dispatch({ type: 'read-marked' })
    } catch (requestError) {
      setError(getErrorMessage(requestError))
      throw requestError
    }
  }

  const requestMarkRead = () => {
    setConfirmation({
      title: 'Mark all activity as read?',
      message: 'Unread activity indicators will be cleared for your account.',
      confirmLabel: 'Mark as read',
      onConfirm: markRead,
    })
  }

  const createTeamUser = async (payload: UserCreateRequest) => {
    try {
      const created = await api<UserCreatedResponse>('/users', token, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setTemporaryPassword({ email: created.user.email, password: created.temporary_password })
      setNotice(`Created an account for ${created.user.full_name}. Share the temporary password securely.`)
      await refresh()
    } catch (requestError) {
      setError(getErrorMessage(requestError))
      throw requestError
    }
  }

  const updateTeamUser = async (memberId: string, changes: UserUpdateRequest) => {
    try {
      await api<User>(`/users/${memberId}`, token, {
        method: 'PATCH',
        body: JSON.stringify(changes),
      })
      setNotice('Team member updated.')
      await refresh()
    } catch (requestError) {
      setError(getErrorMessage(requestError))
      throw requestError
    }
  }

  const resetTeamUserPassword = async (member: User) => {
    try {
      const result = await api<PasswordResetResponse>(`/users/${member.id}/password-reset`, token, { method: 'POST' })
      setTemporaryPassword({ email: member.email, password: result.temporary_password })
      setNotice(`Temporary password created for ${member.full_name}. Share it securely.`)
      await refresh()
    } catch (requestError) {
      setError(getErrorMessage(requestError))
      throw requestError
    }
  }

  const resetAllUserPasswords = async () => {
    const csv = await downloadAllPasswordResetCsv(token)
    const downloadUrl = URL.createObjectURL(csv)
    const downloadLink = document.createElement('a')
    downloadLink.href = downloadUrl
    downloadLink.download = 'urbannest-password-resets.csv'
    document.body.append(downloadLink)
    downloadLink.click()
    downloadLink.remove()
    window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000)
    signOut()
  }

  const updateOwnProfile = async (changes: ProfileUpdateRequest) => {
    try {
      const updated = await api<User>('/auth/me/profile', token, {
        method: 'PATCH',
        body: JSON.stringify(changes),
      })
      setUser(updated)
      setNotice('Your profile was updated.')
      return true
    } catch (requestError) {
      setError(getErrorMessage(requestError))
      return false
    }
  }

  const changeOwnPassword = async (currentPassword: string, newPassword: string) => {
    try {
      const response = await api<LoginResponse>('/auth/change-password', token, {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      setSession(response)
      setNotice('Your password has been updated.')
      return true
    } catch (requestError) {
      setError(getErrorMessage(requestError))
      return false
    }
  }

  const openAuditEvent = async (event: AuditEvent) => {
    setShowNotifications(false)
    if (event.lead_id) {
      setPage('leads')
      await openLeadById(event.lead_id)
      return
    }
    if (event.entity_type === 'task' && event.entity_id) {
      try {
        const task = await api<Task>(`/tasks/${event.entity_id}`, token)
        setPage('leads')
        await openLeadById(task.lead_id)
      } catch (requestError) {
        setError(getErrorMessage(requestError))
      }
      return
    }
    setPage(event.entity_type === 'user' ? canManageTeam ? 'team' : 'profile' : 'activity')
  }

  const handleLogin = (response: LoginResponse) => {
    setSession(response)
    setError('')
  }

  const retryAuthentication = () => {
    setAuthError(false)
    setAuthReady(false)
    setAuthRetryCount((count) => count + 1)
  }

  if (legalPage === 'privacy') {
    return <>
      <PrivacyPolicyPage onBack={closeLegalPage} onOpenCookies={() => openLegalPage('cookies')} />
      <CookieConsentBanner consent={storageConsent} onChoose={chooseStorageConsent} onManage={() => openLegalPage('cookies')} />
    </>
  }

  if (!authReady) {
    return <div className="boot-screen"><span className="brand-mark">U</span><span className="spinner" /></div>
  }

  if (legalPage === 'cookies') {
    return <StoragePreferencesPage consent={storageConsent} onBack={closeLegalPage} onChoose={chooseStorageConsent} />
  }

  if (authError) {
    return <>
      <AppFailureScreen kind="server" fullScreen onRetry={retryAuthentication} />
      <CookieConsentBanner consent={storageConsent} onChoose={chooseStorageConsent} onManage={() => openLegalPage('cookies')} />
    </>
  }

  if (!token || !user) {
    return <>
      <LoginScreen onLogin={handleLogin} error={error} setError={setError} theme={theme} onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')} onOpenPrivacy={() => openLegalPage('privacy')} onOpenCookieSettings={() => openLegalPage('cookies')} />
      <CookieConsentBanner consent={storageConsent} onChoose={chooseStorageConsent} onManage={() => openLegalPage('cookies')} />
    </>
  }

  if (user.must_change_password) {
    return <>
      <PasswordScreen token={token} onComplete={setSession} onSignOut={signOut} theme={theme} onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')} />
      <CookieConsentBanner consent={storageConsent} onChoose={chooseStorageConsent} onManage={() => openLegalPage('cookies')} />
    </>
  }

  const sidebarIsCollapsed = sidebarCollapsed && !mobileNavOpen

  return (
    <div className={`app-shell ${sidebarIsCollapsed ? 'app-shell-collapsed' : ''}`}>
      {mobileNavOpen && <button className="mobile-backdrop" aria-label="Close menu" onClick={() => setMobileNavOpen(false)} />}
      <aside className={`sidebar ${sidebarIsCollapsed ? 'sidebar-collapsed' : ''} ${mobileNavOpen ? 'sidebar-open' : ''}`}>
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setPage('overview') }}>
          <span className="brand-mark">U</span>
          <span className="brand-copy"><strong>urbannest</strong><small>Realty CRM</small></span>
        </a>
        {mobileNavOpen && <button className="mobile-sidebar-close icon-button" aria-label="Close navigation" title="Close navigation" onClick={() => { setMobileNavOpen(false); setShowUserMenu(false) }}><X size={18} /></button>}
        {canReadWorkspace && canWriteWorkspace && <button className="sidebar-create-button" aria-label="Add lead" title="Add lead" onClick={() => { setShowCreateLead(true); setMobileNavOpen(false) }}><Plus size={18} /><span>Add lead</span></button>}

        <div className="nav-caption">Workspace</div>
        <nav className="primary-nav" aria-label="Main navigation">
          {canReadWorkspace && <>
            <NavButton label="Overview" icon={<LayoutDashboard size={18} />} active={activePage === 'overview'} onClick={() => { setPage('overview'); setMobileNavOpen(false) }}>Overview</NavButton>
            <NavButton label="Leads" icon={<Users size={18} />} active={activePage === 'leads'} onClick={() => { setPage('leads'); setMobileNavOpen(false) }}>Leads<span className="nav-count">{dashboard?.total_leads ?? '—'}</span></NavButton>
            <NavButton label="Follow-ups" icon={<CalendarDays size={18} />} active={activePage === 'tasks'} onClick={() => { setPage('tasks'); setMobileNavOpen(false) }}>Follow-ups</NavButton>
            <NavButton label="Activity" icon={<ActivityIcon size={18} />} active={activePage === 'activity'} onClick={() => { setPage('activity'); setMobileNavOpen(false) }}>Activity{unreadCount > 0 && <span className="nav-count">{unreadCount > 9 ? '9+' : unreadCount}</span>}</NavButton>
          </>}
          {canManageTeam && <NavButton label="Team" icon={<UserRound size={18} />} active={activePage === 'team'} onClick={() => { setPage('team'); setMobileNavOpen(false) }}>Team</NavButton>}
          <NavButton label="Org chart" icon={<Network size={18} />} active={activePage === 'org-chart'} onClick={() => { setPage('org-chart'); setMobileNavOpen(false) }}>Org chart</NavButton>
        </nav>

        <div className="sidebar-bottom">
          <button className={`user-profile ${activePage === 'profile' ? 'user-profile-active' : ''}`} aria-haspopup="menu" aria-expanded={showUserMenu} aria-controls="sidebar-user-menu" onClick={() => setShowUserMenu((open) => !open)} title="Open account menu">
            <span className="avatar avatar-user">{initials(user.full_name)}</span>
            <span className="user-meta"><strong>{user.full_name}</strong><span>{user.role}</span></span>
            <ChevronDown className="profile-indicator" size={16} />
          </button>
        </div>
      </aside>

      {!mobileNavOpen && <button className={`sidebar-toggle ${sidebarIsCollapsed ? 'sidebar-toggle-collapsed' : ''}`} aria-label={sidebarIsCollapsed ? 'Expand navigation' : 'Collapse navigation'} title={sidebarIsCollapsed ? 'Expand navigation' : 'Collapse navigation'} onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}>
        {sidebarIsCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
      </button>}
      {showUserMenu && <>
        <button className="profile-menu-backdrop" tabIndex={-1} aria-label="Close account menu" onClick={() => setShowUserMenu(false)} />
        <div className="profile-menu" id="sidebar-user-menu" role="menu" aria-label="Account menu">
          <button className="profile-menu-item" role="menuitem" onClick={() => { setPage('profile'); setMobileNavOpen(false); setShowUserMenu(false) }}><UserRound size={16} /><span>Profile</span></button>
          <button className="profile-menu-item" role="menuitem" onClick={() => { setShowUserMenu(false); setMobileNavOpen(false); setConfirmation({
            title: 'Sign out?',
            message: 'You’ll need to sign in again to continue working in UrbanNest Realty.',
            confirmLabel: 'Sign out',
            onConfirm: signOut,
          }) }}><LogOut size={16} /><span>Sign out</span></button>
        </div>
      </>}

      <main className="main-panel">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Open menu" onClick={() => setMobileNavOpen(true)}><Menu size={20} /></button>
          <div className="topbar-actions">
            <div className={`api-indicator ${apiConnected ? '' : 'api-offline'}`}><span className="status-light" /> {apiConnected ? 'API connected' : error ? 'API unavailable' : 'API not checked'}</div>
            <ThemeButton theme={theme} onToggle={() => setTheme(theme === 'dark' ? 'light' : 'dark')} />
            {canReadWorkspace && <button className="icon-button notification-button" aria-label="Notifications" onClick={() => setShowNotifications((show) => !show)}>
              <Bell size={19} />{unreadCount > 0 && <span className="notification-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>}
            </button>}
          </div>
        </header>

        <div className="page-content">
          {(notice || (error && workspace.hasLoaded)) && (
            <div className={`toast ${error ? 'toast-error' : 'toast-success'}`} role="status">
              {error ? <CircleAlert size={17} /> : <Check size={17} />}
              <span>{error || notice}</span>
              <button className="icon-button toast-close" aria-label="Dismiss message" onClick={() => { setError(''); setNotice('') }}><X size={16} /></button>
            </div>
          )}

          <div className="page-heading">
            <div>
              <p className="eyebrow">{formatDate(renderTime.toISOString(), { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p>
              <h1>{activePage === 'overview' ? 'Sales overview' : pageTitle}</h1>
              <p className="heading-subtitle">{activePage === 'overview' ? 'A clear view of your leads and next steps' : activePage === 'leads' ? 'Track each enquiry from first contact to decision' : activePage === 'tasks' ? 'Keep client conversations moving with timely follow-ups' : activePage === 'activity' ? 'Changes across leads, follow-ups, and your team' : activePage === 'team' ? 'Manage team access and account setup' : activePage === 'org-chart' ? 'Explore your active team and reporting lines' : 'Your account details and sign-in security'}</p>
            </div>
            <div className="heading-actions">
              <button className="button button-secondary refresh-button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={16} className={loading ? 'spinning' : ''} /><span>Refresh</span></button>
              {canReadWorkspace && canWriteWorkspace && (activePage === 'overview' || activePage === 'leads') && <button className="button button-primary" onClick={() => setShowCreateLead(true)}><Plus size={17} /> Add lead</button>}
            </div>
          </div>

          {!workspace.hasLoaded
            ? loading || !error
              ? <LoadingState />
              : <AppFailureScreen kind="server" onRetry={() => void refresh()} />
            : (
            <>
              {!canReadWorkspace && activePage !== 'team' && activePage !== 'org-chart' && activePage !== 'profile' && (
                <EmptyState title="Workspace access is disabled" description="Your current role does not have permission to read CRM records." />
              )}
              {canReadWorkspace && activePage === 'overview' && (
                <OverviewPage dashboard={dashboard} leads={leads} events={auditEvents} users={teamUsers} currentUser={user} now={renderTime.getTime()} onOpenLead={setSelectedLead} onOpenLeadById={openLeadById} onOpenTasks={() => setPage('tasks')} onSeeAllActivity={() => setPage('activity')} onCompleteTask={requestCompleteTask} onOpenLeads={() => setPage('leads')} onOpenEvent={(event) => void openAuditEvent(event)} canWrite={canWriteWorkspace} />
              )}
              {canReadWorkspace && activePage === 'leads' && (
                <LeadsPage leads={leads} query={query} setQuery={setQuery} searchRef={leadSearchRef} statusFilter={statusFilter} setStatusFilter={setStatusFilter} onOpenLead={setSelectedLead} onUpdateStatus={requestLeadStatusUpdate} onAddLead={() => setShowCreateLead(true)} onImportFile={importCsv} importErrors={importErrors} onDismissImportErrors={() => dispatch({ type: 'import-errors-cleared' })} canImport={canWriteWorkspace && user.role !== 'agent'} canWrite={canWriteWorkspace} loading={loading} />
              )}
              {canReadWorkspace && activePage === 'tasks' && (
                <TasksPage tasks={visibleTasks} filter={taskFilter} setFilter={setTaskFilter} users={teamUsers} currentUser={user} now={renderTime.getTime()} onComplete={requestCompleteTask} onOpenLead={openLeadById} canWrite={canWriteWorkspace} />
              )}
              {canReadWorkspace && activePage === 'activity' && <ActivityPage events={auditEvents} unreadCount={unreadCount} onMarkRead={requestMarkRead} onOpenEvent={(event) => void openAuditEvent(event)} />}
              {activePage === 'team' && canManageTeam && <TeamPage currentUser={user} users={teamUsers} temporaryPassword={temporaryPassword} onClearTemporaryPassword={() => setTemporaryPassword(null)} onCreate={createTeamUser} onUpdate={updateTeamUser} onResetPassword={resetTeamUserPassword} onError={setError} onConfirmAction={setConfirmation} onResetAll={resetAllUserPasswords} />}
              {activePage === 'org-chart' && <OrgChartPage members={orgChartMembers} loading={loading} error={error} onRetry={() => void refresh()} />}
              {activePage === 'profile' && <ProfilePage user={user} onChangePassword={changeOwnPassword} onSaveProfile={updateOwnProfile} onConfirmAction={setConfirmation} />}
            </>
          )}
        </div>
        <footer className="app-legal-footer">
          <span>UrbanNest Realty CRM</span>
          <div>
            <a href="https://www.urbanestrealty.in/" target="_blank" rel="noopener noreferrer">UrbanNest Realty website</a>
            <button onClick={() => openLegalPage('privacy')}>Privacy policy</button>
            <button onClick={() => openLegalPage('cookies')}>Cookie and storage choices</button>
          </div>
        </footer>
      </main>

      {showNotifications && canReadWorkspace && <NotificationPanel events={auditEvents.slice(0, 5)} unreadCount={unreadCount} onClose={() => setShowNotifications(false)} onOpenEvent={(event) => void openAuditEvent(event)} onOpenActivity={() => { setPage('activity'); setShowNotifications(false) }} />}
      {confirmation && <ConfirmationDialog request={confirmation} onCancel={() => setConfirmation(null)} onConfirmed={() => setConfirmation(null)} />}
      {selectedLead && user && canReadWorkspace && <LeadDrawer lead={selectedLead} token={token} currentUser={user} onClose={() => setSelectedLead(null)} onUpdated={(updated) => { setSelectedLead(updated); void refresh() }} onError={setError} onConfirmAction={setConfirmation} canWrite={canWriteWorkspace} />}
      {showCreateLead && canWriteWorkspace && <CreateLeadModal token={token} currentUser={user} onClose={() => setShowCreateLead(false)} onConfirmAction={setConfirmation} onCreated={async (lead) => { setShowCreateLead(false); setNotice(`Added ${lead.full_name} to your leads.`); setPage('leads'); await refresh(); setSelectedLead(lead) }} onError={setError} />}
      <CookieConsentBanner consent={storageConsent} onChoose={chooseStorageConsent} onManage={() => openLegalPage('cookies')} />
    </div>
  )
}

function ThemeButton({ theme, onToggle, className = '' }: { theme: Theme; onToggle: () => void; className?: string }) {
  const nextTheme = theme === 'dark' ? 'light' : 'dark'
  return <button className={`icon-button theme-toggle ${className}`} aria-label={`Switch to ${nextTheme} mode`} aria-pressed={theme === 'dark'} title={`Switch to ${nextTheme} mode`} onClick={onToggle}>
    {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
  </button>
}

function NavButton({ icon, active, onClick, children, label }: { icon: React.ReactNode; active: boolean; onClick: () => void; children: React.ReactNode; label: string }) {
  return <button className={`nav-item ${active ? 'nav-item-active' : ''}`} onClick={onClick} title={label} aria-label={label}>{icon}<span>{children}</span></button>
}

function LoadingState() {
  return (
    <div className="loading-state workspace-skeleton dashboard-grid" role="status" aria-label="Loading your workspace">
      <section className="stat-grid" aria-hidden="true">
        {Array.from({ length: 4 }, (_, index) => (
          <div className="stat-card skeleton-stat-card" key={index}>
            <span className="skeleton-block skeleton-stat-label" />
            <span className="skeleton-block skeleton-stat-value" />
            <span className="skeleton-block skeleton-stat-detail" />
          </div>
        ))}
      </section>

      <section className="panel pipeline-panel skeleton-panel" aria-hidden="true">
        <div className="panel-header">
          <div>
            <p className="eyebrow"><span className="skeleton-block skeleton-eyebrow" /></p>
            <h2><span className="skeleton-block skeleton-panel-title" /></h2>
          </div>
          <span className="skeleton-block skeleton-header-action" />
        </div>
        <div className="pipeline-summary">
          <strong><span className="skeleton-block skeleton-pipeline-total" /></strong>
          <span><span className="skeleton-block skeleton-summary-copy" /></span>
        </div>
        <div className="pipeline-chart-layout">
          <div className="pipeline-chart skeleton-block skeleton-pipeline-chart" />
          <div className="pipeline-legend-grid">
            {Array.from({ length: 6 }, (_, index) => (
              <div className="pipeline-legend-item" key={index}>
                <span className="stage-dot skeleton-block skeleton-stage-dot" />
                <span className="skeleton-block skeleton-stage-label" />
                <span className="skeleton-block skeleton-stage-value" />
                <small className="skeleton-block skeleton-stage-percent" />
              </div>
            ))}
          </div>
        </div>
        <div className="pipeline-footer"><span className="skeleton-block skeleton-footer-label" /></div>
      </section>

      <section className="panel followup-panel skeleton-panel" aria-hidden="true">
        <div className="panel-header">
          <div>
            <p className="eyebrow"><span className="skeleton-block skeleton-eyebrow" /></p>
            <h2><span className="skeleton-block skeleton-panel-title skeleton-followup-title" /></h2>
          </div>
          <span className="skeleton-block skeleton-header-icon" />
        </div>
        <div className="followup-tabs">
          <span className="followup-tab active"><span className="skeleton-block skeleton-tab-label" /><b><span className="skeleton-block skeleton-tab-count" /></b></span>
          <span className="followup-tab"><span className="skeleton-block skeleton-tab-label skeleton-all-tasks" /></span>
        </div>
        <div className="followup-list">
          {Array.from({ length: 4 }, (_, index) => (
            <div className="followup-item" key={index}>
              <span className="task-check skeleton-block skeleton-task-check" />
              <span className="followup-copy">
                <span className="skeleton-block skeleton-task-title" />
                <span className="skeleton-block skeleton-task-lead" />
              </span>
              <span className="task-assignee">
                <span className="avatar avatar-xs skeleton-block skeleton-assignee-avatar" />
                <span className="skeleton-block skeleton-assignee-name" />
              </span>
              <span className="task-time"><span className="skeleton-block skeleton-task-time" /></span>
            </div>
          ))}
        </div>
        <div className="panel-link"><span className="skeleton-block skeleton-panel-link" /></div>
      </section>

      <section className="panel leads-panel skeleton-panel" aria-hidden="true">
        <div className="panel-header">
          <div>
            <p className="eyebrow"><span className="skeleton-block skeleton-eyebrow" /></p>
            <h2><span className="skeleton-block skeleton-panel-title" /></h2>
          </div>
          <span className="skeleton-block skeleton-header-action" />
        </div>
        <div className="table-scroll">
          <table className="data-table compact-table skeleton-leads-table">
            <colgroup><col /><col /><col /><col /></colgroup>
            <thead>
              <tr>
                <th><span className="skeleton-block skeleton-table-heading skeleton-lead-heading" /></th>
                <th><span className="skeleton-block skeleton-table-heading skeleton-interest-heading" /></th>
                <th><span className="skeleton-block skeleton-table-heading skeleton-stage-heading" /></th>
                <th><span className="skeleton-block skeleton-table-heading skeleton-added-heading" /></th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 5 }, (_, index) => (
                <tr key={index}>
                  <td>
                    <div className="lead-cell">
                      <span className="avatar skeleton-block skeleton-lead-avatar" />
                      <span>
                        <span className="skeleton-block skeleton-lead-name" />
                        <span className="skeleton-block skeleton-lead-location" />
                      </span>
                    </div>
                  </td>
                  <td>
                    <span className="skeleton-block skeleton-interest-main" />
                    <span className="skeleton-block skeleton-interest-sub" />
                  </td>
                  <td><span className="skeleton-block skeleton-status" /></td>
                  <td><span className="skeleton-block skeleton-added-date" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel activity-panel skeleton-panel" aria-hidden="true">
        <div className="panel-header">
          <div>
            <p className="eyebrow"><span className="skeleton-block skeleton-eyebrow" /></p>
            <h2><span className="skeleton-block skeleton-panel-title" /></h2>
          </div>
          <span className="skeleton-block skeleton-header-icon" />
        </div>
        <div className="activity-list">
          {Array.from({ length: 5 }, (_, index) => (
            <div className="activity-item" key={index}>
              <span className="activity-avatar skeleton-block skeleton-activity-avatar" />
              <span className="activity-body">
                <span className="activity-summary"><span className="skeleton-block skeleton-activity-summary" /></span>
                {index % 2 === 0 && <span className="activity-detail"><span className="skeleton-block skeleton-activity-detail" /></span>}
                <time><span className="skeleton-block skeleton-activity-time" /></time>
                <span className="activity-open-link"><span className="skeleton-block skeleton-activity-link" /></span>
              </span>
              <span className="activity-read-dot skeleton-block skeleton-activity-dot" />
            </div>
          ))}
        </div>
        <div className="panel-link"><span className="skeleton-block skeleton-panel-link" /></div>
      </section>
    </div>
  )
}

function LoginScreen({ onLogin, error, setError, theme, onToggleTheme, onOpenPrivacy, onOpenCookieSettings }: { onLogin: (response: LoginResponse) => void; error: string; setError: (message: string) => void; theme: Theme; onToggleTheme: () => void; onOpenPrivacy: () => void; onOpenCookieSettings: () => void }) {
  const [email, setEmail] = useState('')
  const [emailValidationError, setEmailValidationError] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [forgotPassword, setForgotPassword] = useState(false)
  const [recoverySent, setRecoverySent] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedEmail = normalizeEmail(email)
    const validationError = validateEmail(normalizedEmail)
    setEmailValidationError(validationError)
    if (validationError) return
    setSubmitting(true)
    setError('')
    try {
      if (forgotPassword) {
        await api<{ message: string }>('/auth/password-recovery', '', {
          method: 'POST',
          body: JSON.stringify({ email: normalizedEmail }),
        })
        setRecoverySent(true)
        return
      }
      const response = await api<LoginResponse>('/auth/login', '', { method: 'POST', body: JSON.stringify({ email: normalizedEmail, password }) })
      onLogin(response)
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-art">
        <a className="brand brand-light" href="#"><span className="brand-mark">U</span><span className="brand-copy"><strong>urbannest</strong><small>Realty CRM</small></span></a>
        <div className="art-copy">
          <span className="art-kicker"><span /> A clearer view of every enquiry</span>
          <h1>Every lead<br />has a <em>home</em></h1>
          <p>Keep client details, pipeline stages, and follow-ups together in one workspace.</p>
        </div>
        <div className="art-building"><div className="building-sun" /><div className="building-tower tower-one"><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /></div><div className="building-tower tower-two"><i /><i /><i /><i /><i /><i /><i /><i /></div><div className="building-house"><i /><i /><i /><i /></div><div className="building-ground" /></div>
        <p className="art-footnote">UrbanNest Realty CRM</p>
      </div>
      <div className="auth-main">
        <ThemeButton theme={theme} onToggle={onToggleTheme} className="auth-theme-toggle" />
        <div className="auth-form-wrap">
          <span className="auth-overline">{forgotPassword ? 'Password recovery' : 'Your workspace'}</span>
          <h2>{forgotPassword ? <>Request a password<br />reset</> : <>Sign in to your<br />workspace</>}</h2>
          <p className="auth-description">{forgotPassword ? 'If your account is active, your team owner can issue a temporary password.' : 'View the leads, pipeline, and follow-ups your team is working on'}</p>
          <form className="auth-form" onSubmit={(event) => void submit(event)}>
            <label>Email address<input type="email" autoComplete={forgotPassword ? 'email' : 'username'} value={email} onChange={(event) => { setEmail(event.target.value); setEmailValidationError(''); setRecoverySent(false) }} onBlur={() => { const normalized = normalizeEmail(email); setEmail(normalized); setEmailValidationError(normalized ? validateEmail(normalized) : '') }} placeholder="you@urbannest.in" maxLength={320} required aria-invalid={Boolean(emailValidationError)} aria-describedby={emailValidationError ? 'login-email-error' : undefined} />{emailValidationError && <small className="inline-form-error" id="login-email-error">{emailValidationError}</small>}</label>
            {!forgotPassword && <label>Password<span className="password-input-wrap"><input type={showPassword ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" required /><button className="password-visibility-toggle" type="button" aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} onClick={() => setShowPassword((visible) => !visible)}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></span></label>}
            {!forgotPassword && <button className="auth-link auth-forgot-link" type="button" onClick={() => { setForgotPassword(true); setRecoverySent(false); setError('') }}>Forgot password?</button>}
            {error && <div className="form-error"><CircleAlert size={16} />{error}</div>}
            {recoverySent && <div className="auth-recovery-success" role="status" aria-live="polite">If an active account matches that email, its team owner can help with a reset.</div>}
            <button className="button button-primary auth-submit" disabled={submitting || recoverySent}>{submitting ? forgotPassword ? 'Sending request…' : 'Signing in…' : forgotPassword ? 'Request reset' : 'Sign in'}<ArrowUpRight size={17} /></button>
            {forgotPassword && <button className="auth-link auth-back-link" type="button" onClick={() => { setForgotPassword(false); setRecoverySent(false); setError('') }}>Back to sign in</button>}
          </form>
          {!forgotPassword && <div className="auth-note"><span className="secure-dot" /> Your workspace is private and secure.</div>}
        </div>
        <div className="auth-footer">
          <span>© {CURRENT_YEAR} UrbanNest Realty</span>
          <span>Questions? Ask your team owner.</span>
          <div className="auth-legal-links">
            <a href="https://www.urbanestrealty.in/" target="_blank" rel="noopener noreferrer">UrbanNest Realty website</a>
            <button onClick={onOpenPrivacy}>Privacy</button>
            <button onClick={onOpenCookieSettings}>Storage choices</button>
          </div>
        </div>
      </div>
    </div>
  )
}

function PasswordScreen({ token, onComplete, onSignOut, theme, onToggleTheme }: { token: string; onComplete: (response: LoginResponse) => void; onSignOut: () => void; theme: Theme; onToggleTheme: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [showSignOutConfirmation, setShowSignOutConfirmation] = useState(false)
  const [showPasswordConfirmation, setShowPasswordConfirmation] = useState(false)

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    if (next !== confirm) {
      setError('Your new passwords do not match.')
      return
    }
    setShowPasswordConfirmation(true)
  }

  const changePassword = async () => {
    try {
      const response = await api<LoginResponse>('/auth/change-password', token, { method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }) })
      onComplete(response)
    } catch (requestError) {
      setError(getErrorMessage(requestError))
      throw requestError
    }
  }

  return <div className="password-page"><div className="password-card"><div className="password-card-head"><span className="brand-mark">U</span><ThemeButton theme={theme} onToggle={onToggleTheme} /></div><span className="auth-overline">Password setup</span><h1>Make it your own</h1><p>Your account has a temporary password. Create a new one to continue.</p><form className="auth-form" onSubmit={submit}><label>Temporary password<input type="password" value={current} onChange={(event) => setCurrent(event.target.value)} required /></label><label>New password<input type="password" minLength={12} value={next} onChange={(event) => setNext(event.target.value)} required /><small className="field-hint">Use at least 12 characters.</small></label><label>Confirm new password<input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} required /></label>{error && <div className="form-error"><CircleAlert size={16} />{error}</div>}<button className="button button-primary auth-submit">Review password change<ArrowUpRight size={17} /></button></form><button className="text-button signout-link" onClick={() => setShowSignOutConfirmation(true)}>Sign out instead</button></div>{showSignOutConfirmation && <ConfirmationDialog request={{ title: 'Sign out?', message: 'You’ll need to sign in again to continue setting up your account.', confirmLabel: 'Sign out', onConfirm: onSignOut }} onCancel={() => setShowSignOutConfirmation(false)} onConfirmed={() => setShowSignOutConfirmation(false)} />}{showPasswordConfirmation && <ConfirmationDialog request={{ title: 'Set your new password?', message: 'This replaces your temporary password. Your existing session will be renewed with the new credential.', confirmLabel: 'Save new password', onConfirm: changePassword }} onCancel={() => setShowPasswordConfirmation(false)} onConfirmed={() => setShowPasswordConfirmation(false)} />}</div>
}

function ConfirmationDialog({ request, onCancel, onConfirmed }: { request: ConfirmationRequest; onCancel: () => void; onConfirmed: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState('')

  const confirm = async () => {
    setConfirming(true)
    setConfirmError('')
    try {
      await request.onConfirm()
      onConfirmed()
    } catch (error) {
      setConfirmError(getErrorMessage(error))
      setConfirming(false)
    }
  }

  return <div className="confirmation-backdrop" onKeyDown={(event) => { if (event.key === 'Escape' && !confirming) onCancel() }} onMouseDown={(event) => { if (event.target === event.currentTarget && !confirming) onCancel() }}>
    <section className="confirmation-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirmation-title" aria-describedby="confirmation-message">
      <div className="confirmation-icon"><CircleAlert size={20} /></div>
      <h2 id="confirmation-title">{request.title}</h2>
      <p id="confirmation-message">{request.message}</p>
      {confirmError && <p className="confirmation-error" role="alert">{confirmError}</p>}
      <div className="confirmation-actions">
        <button className="button button-secondary" type="button" onClick={onCancel} disabled={confirming} autoFocus>Cancel</button>
        <button className="button button-danger" type="button" onClick={() => void confirm()} disabled={confirming}>{confirming ? 'Please wait…' : request.confirmLabel}</button>
      </div>
    </section>
  </div>
}

function OverviewPage({ dashboard, leads, events, users, currentUser, now, onOpenLead, onOpenLeadById, onOpenTasks, onSeeAllActivity, onCompleteTask, onOpenLeads, onOpenEvent, canWrite }: {
  dashboard: Dashboard | null; leads: Lead[]; events: AuditEvent[]; users: User[]; currentUser: User
  now: number
  onOpenLead: (lead: Lead) => void; onOpenLeadById: (leadId: string) => void
  onOpenTasks: () => void; onSeeAllActivity: () => void
  onCompleteTask: (task: Pick<Task, 'id' | 'title'>) => void; onOpenLeads: () => void
  onOpenEvent: (event: AuditEvent) => void
  canWrite: boolean
}) {
  const pipelineData = stages.map((stage) => ({ ...stage, count: dashboard?.pipeline_counts[stage.value] ?? 0 }))
  const pipelineTotal = pipelineData.reduce((total, item) => total + item.count, 0)
  const chartColors: Record<LeadStatus, string> = {
    new: '#a4aaa4',
    contacted: '#829b8a',
    site_visit: '#b59a69',
    negotiation: '#557b61',
    won: '#2f7258',
    lost: '#b77768',
  }
  const chartSegments = pipelineData
    .filter((item) => item.count > 0)
    .reduce(
      (segments, item) => {
        const progress = segments.progress + (item.count / pipelineTotal) * 100
        return {
          progress,
          stops: [...segments.stops, `${chartColors[item.value]} ${segments.progress}% ${progress}%`],
        }
      },
      { progress: 0, stops: [] as string[] },
    )
    .stops
  const pipelineChart = pipelineTotal
    ? `conic-gradient(${chartSegments.join(', ')})`
    : 'conic-gradient(var(--chart-empty) 0% 100%)'
  const dueTasks = [...(dashboard?.overdue ?? []), ...(dashboard?.due_today ?? [])].slice(0, 4)
  const recentLeads = leads.slice(0, 5)

  return (
    <div className="dashboard-grid">
      <section className="stat-grid">
        <StatCard label="Total leads" value={dashboard?.total_leads ?? '—'} detail="In your pipeline" />
        <StatCard label="Open follow-ups" value={dashboard?.open_tasks ?? '—'} detail={`${dashboard?.due_today_count ?? 0} due today`} />
        <StatCard label="Due today" value={dashboard?.due_today_count ?? '—'} detail="Scheduled for today" />
        <StatCard label="Overdue" value={dashboard?.overdue_count ?? '—'} detail={dashboard?.overdue_count ? 'Needs attention' : 'All caught up'} warning={Boolean(dashboard?.overdue_count)} />
      </section>

      <section className="panel pipeline-panel">
        <div className="panel-header"><div><p className="eyebrow">Lead stages</p><h2>Pipeline at a glance</h2></div><button className="text-button" onClick={onOpenLeads}>View leads <ArrowUpRight size={15} /></button></div>
        <div className="pipeline-summary"><strong>{dashboard?.total_leads ?? '—'}</strong><span>leads in your pipeline</span></div>
        <div className="pipeline-chart-layout">
          <div className="pipeline-chart" role="img" aria-label={`Lead pipeline chart: ${pipelineData.map((item) => `${item.label} ${item.count}`).join(', ')}`} style={{ background: pipelineChart }}>
            <div className="pipeline-chart-hole"><strong>{pipelineTotal}</strong><span>Total leads</span></div>
          </div>
          <div className="pipeline-legend-grid">
            {pipelineData.map((item) => <div className="pipeline-legend-item" key={item.value}>
              <span className={`stage-dot dot-${item.tone}`} />
              <span className="pipeline-stage">{item.label}</span>
              <strong>{item.count}</strong>
              <small>{pipelineTotal ? `${Math.round((item.count / pipelineTotal) * 100)}%` : '0%'}</small>
            </div>)}
          </div>
        </div>
        <div className="pipeline-footer"><span>Lead movement by stage</span></div>
      </section>

      <section className="panel followup-panel">
        <div className="panel-header"><div><p className="eyebrow">Next steps</p><h2>Follow-ups to focus on</h2></div><button className="icon-button subtle-icon" aria-label="View all follow-ups" onClick={onOpenTasks}><ArrowUpRight size={17} /></button></div>
        <div className="followup-tabs"><span className="followup-tab active">Priority <b>{dueTasks.length}</b></span><button className="followup-tab" onClick={onOpenTasks}>All tasks <ChevronRight size={13} /></button></div>
        {dueTasks.length ? <div className="followup-list">{dueTasks.map((task) => {
          const lead = leads.find((item) => item.id === task.lead_id)
          return <div className="followup-item" key={task.id}>
            {canWrite && <button className="task-check" title="Mark complete" aria-label={`Mark ${task.title} complete`} onClick={() => onCompleteTask(task)}><Check size={14} /></button>}
              <button className="followup-copy" onClick={() => lead ? onOpenLead(lead) : onOpenLeadById(task.lead_id)}><strong>{task.title}</strong><span>{task.lead_name}</span></button>
            <span className="task-assignee"><span className="avatar avatar-xs avatar-user">{initials(taskAssigneeName(task, users, currentUser))}</span>{taskAssigneeName(task, users, currentUser)}</span>
            <span className={`task-time ${taskIsOverdue(task.due_at, now) ? 'task-time-overdue' : ''}`}><Clock3 size={12} />{relativeDate(task.due_at)}</span>
          </div>
        })}</div> : <EmptyState title="You’re all caught up" description="No overdue or due-today follow-ups to show." />}
        <button className="panel-link" onClick={onOpenTasks}>Open your task list <ArrowUpRight size={14} /></button>
      </section>

      <section className="panel leads-panel">
        <div className="panel-header"><div><p className="eyebrow">New enquiries</p><h2>Recently added leads</h2></div><button className="text-button" onClick={onOpenLeads}>All leads <ArrowUpRight size={15} /></button></div>
        {recentLeads.length ? <div className="table-scroll"><table className="data-table compact-table"><thead><tr><th>Lead</th><th>Interest</th><th>Stage</th><th>Added</th></tr></thead><tbody>{recentLeads.map((lead) => <tr key={lead.id} onClick={() => onOpenLead(lead)}><td><div className="lead-cell"><div className={`avatar avatar-${avatarColor(lead.full_name)}`}>{initials(lead.full_name)}</div><span><strong>{lead.full_name}</strong><small>{lead.preferred_location || sourceLabels[lead.source]}</small></span></div></td><td>{lead.bhk ? `${lead.bhk} BHK` : '—'}<small className="table-subline">{budgetRange(lead)}</small></td><td><StatusPill status={lead.status} /></td><td className="muted-cell">{formatDate(lead.created_at)}</td></tr>)}</tbody></table></div> : <EmptyState title="No leads just yet" description="Add your first lead and start building your pipeline." />}
      </section>

      <section className="panel activity-panel">
        <div className="panel-header"><div><p className="eyebrow">Workspace updates</p><h2>Recent activity</h2></div><button className="icon-button subtle-icon" aria-label="See all activity" onClick={onSeeAllActivity}><ArrowUpRight size={17} /></button></div>
        {events.length ? <ActivityList events={events.slice(0, 5)} onOpenEvent={onOpenEvent} /> : <EmptyState title="A fresh start" description="Team updates will appear here as work happens." />}
        <button className="panel-link" onClick={onSeeAllActivity}>View activity feed <ArrowUpRight size={14} /></button>
      </section>
    </div>
  )
}

function StatCard({ label, value, detail, warning = false }: { label: string; value: string | number; detail: string; warning?: boolean }) {
  return <div className={`stat-card ${warning ? 'stat-card-warning' : ''}`}><span className="stat-label">{label}</span><strong className="stat-value">{value}</strong><span className="stat-detail">{detail}</span></div>
}

function SortableHeader({ label, sortKey, activeSort, direction, onSort, filter }: {
  label: string
  sortKey: LeadSortKey
  activeSort: LeadSortKey
  direction: SortDirection
  onSort: (sortKey: LeadSortKey) => void
  filter?: React.ReactNode
}) {
  const active = sortKey === activeSort
  const nextDirection = active && direction === 'ascending' ? 'descending' : 'ascending'
  return <th aria-sort={active ? direction : 'none'}>
    <div className="table-header-cell">
      <button type="button" className="table-sort-button" aria-label={`Sort by ${label}, ${nextDirection}`} onClick={() => onSort(sortKey)}>
        <span>{label}</span><span className="table-sort-indicator" aria-hidden="true">{active ? direction === 'ascending' ? '↑' : '↓' : '↕'}</span>
      </button>
      {filter && <div className="table-header-filter-wrap">{filter}</div>}
    </div>
  </th>
}

function LeadsPage({ leads, query, setQuery, searchRef, statusFilter, setStatusFilter, onOpenLead, onUpdateStatus, onAddLead, onImportFile, importErrors, onDismissImportErrors, canImport, canWrite, loading }: {
  leads: Lead[]; query: string; setQuery: (value: string) => void; statusFilter: string
  searchRef: React.RefObject<HTMLInputElement | null>
  setStatusFilter: (value: string) => void; onOpenLead: (lead: Lead) => void
  onUpdateStatus: (lead: Lead, status: LeadStatus) => void; onAddLead: () => void
  onImportFile: (file: File) => Promise<void>
  importErrors: CSVImportResult['errors']
  onDismissImportErrors: () => void; canImport: boolean; canWrite: boolean; loading: boolean
}) {
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importCheck, setImportCheck] = useState<LeadImportPreflight | null>(null)
  const [validatingImport, setValidatingImport] = useState(false)
  const [submittingImport, setSubmittingImport] = useState(false)
  const [importActionError, setImportActionError] = useState('')
  const importInputRef = useRef<HTMLInputElement>(null)
  const importValidationRef = useRef(0)
  const [sourceFilter, setSourceFilter] = useState<LeadSource | ''>('')
  const [locationFilter, setLocationFilter] = useState('')
  const [bedroomFilter, setBedroomFilter] = useState('')
  const [sortKey, setSortKey] = useState<LeadSortKey>('added')
  const [sortDirection, setSortDirection] = useState<SortDirection>('descending')
  const locationOptions = useMemo(() => [...new Set(leads
    .map((lead) => lead.preferred_location?.trim())
    .filter((location): location is string => Boolean(location)))].sort((a, b) => a.localeCompare(b)), [leads])
  const bedroomOptions = useMemo(() => [...new Set(leads
    .map((lead) => lead.bhk)
    .filter((bedrooms): bedrooms is number => bedrooms !== null && bedrooms !== undefined))]
    .sort((a, b) => a - b), [leads])
  const visibleLeads = useMemo(() => leads
    .filter((lead) => (!sourceFilter || lead.source === sourceFilter)
      && (!locationFilter || lead.preferred_location?.trim() === locationFilter)
      && (!bedroomFilter || String(lead.bhk ?? '') === bedroomFilter))
    .sort((left, right) => {
      const compared = compareLeads(left, right, sortKey)
      return sortDirection === 'ascending' ? compared : -compared
    }), [bedroomFilter, leads, locationFilter, sortDirection, sortKey, sourceFilter])
  const hasActiveFilters = Boolean(query || statusFilter || sourceFilter || locationFilter || bedroomFilter)

  const changeSort = (nextSortKey: LeadSortKey) => {
    if (nextSortKey === sortKey) {
      setSortDirection((current) => current === 'ascending' ? 'descending' : 'ascending')
      return
    }
    setSortKey(nextSortKey)
    setSortDirection(nextSortKey === 'added' ? 'descending' : 'ascending')
  }

  const clearFilters = () => {
    setQuery('')
    setStatusFilter('')
    setSourceFilter('')
    setLocationFilter('')
    setBedroomFilter('')
  }

  const closeImportDialog = () => {
    importValidationRef.current += 1
    setShowImportDialog(false)
    setImportFile(null)
    setImportCheck(null)
    setValidatingImport(false)
    setImportActionError('')
  }

  const inspectSelectedFile = async (file: File) => {
    const requestId = importValidationRef.current + 1
    importValidationRef.current = requestId
    setImportFile(file)
    setImportCheck(null)
    setImportActionError('')
    setValidatingImport(true)
    const result = await inspectLeadImportFile(file)
    if (importValidationRef.current === requestId) {
      setImportCheck(result)
      setValidatingImport(false)
    }
  }

  const submitImport = async () => {
    if (!importFile || !importCheck?.valid) return
    setSubmittingImport(true)
    setImportActionError('')
    try {
      await onImportFile(importFile)
      closeImportDialog()
    } catch (error) {
      setImportActionError(getErrorMessage(error))
    } finally {
      setSubmittingImport(false)
    }
  }

  return <section className="panel full-panel leads-page-panel">
    <div className="list-toolbar"><div className="search-box"><Search size={17} /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search leads, locations…" aria-label="Search leads" /><kbd className="search-shortcut">/</kbd>{query && <button className="icon-button clear-search" aria-label="Clear search" onClick={() => setQuery('')}><X size={14} /></button>}</div><span className="result-count">Showing {visibleLeads.length} of {leads.length}</span>{hasActiveFilters && <button className="text-button clear-filters" onClick={clearFilters}>Clear filters</button>}{canImport && <button type="button" className="button button-secondary import-button" onClick={() => setShowImportDialog(true)}><Upload size={15} /> Import CSV / Excel</button>}</div>
    {showImportDialog && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !submittingImport) closeImportDialog() }}><section className="create-modal import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-dialog-title"><div className="modal-header"><div><span className="eyebrow">LEAD WORKSPACE</span><h2 id="import-dialog-title">Import a spreadsheet</h2></div><button className="icon-button" type="button" aria-label="Close import dialog" onClick={closeImportDialog} disabled={submittingImport}><X size={19} /></button></div><p className="import-guidance">Use a UTF-8 <code>.csv</code> or Excel <code>.xlsx</code> file. The first worksheet row must contain these headers; extra or unknown columns are rejected.</p><div className="import-schema"><strong>Required</strong><code>full_name</code><strong>Optional</strong><span>{LEAD_IMPORT_COLUMNS.slice(1).join(', ')}</span></div><p className="import-guidance">Each remaining row is one lead. Use whole numbers for budgets (INR) and <code>bhk</code>. <code>source</code> values: website, 99acres, magicbricks, instagram, whatsapp, walk_in, manual, csv_import, other. <code>status</code> values: new, contacted, site_visit, negotiation, won, lost. Max 500 rows and 2 MiB. The browser checks the structure and the API validates it again before saving.</p><pre className="import-example"><code>full_name,email,phone,preferred_location,budget_min_inr,budget_max_inr,bhk{"\n"}Aarav Mehta,aarav@example.com,+919876543210,Baner,5000000,8000000,2</code></pre><input ref={importInputRef} className="import-file-input" type="file" accept=".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => { const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; if (file) void inspectSelectedFile(file) }} /><div className="import-file-row"><button type="button" className="button button-secondary" onClick={() => importInputRef.current?.click()} disabled={validatingImport || submittingImport}>{importFile ? 'Choose another file' : 'Choose CSV or Excel file'}</button>{importFile && <span className="import-file-name">{importFile.name}</span>}</div><div className="import-validation" aria-live="polite">{validatingImport && <p>Checking file structure…</p>}{importCheck?.valid && <p className="import-valid">{importCheck.rowCount} lead rows are ready to import.</p>}{importCheck && !importCheck.valid && <ul role="alert">{importCheck.errors.map((error) => <li key={error}>{error}</li>)}</ul>}{importActionError && <p className="confirmation-error" role="alert">{importActionError}</p>}</div><div className="confirmation-actions"><button type="button" className="button button-secondary" onClick={closeImportDialog} disabled={submittingImport}>Cancel</button><button type="button" className="button button-primary" onClick={() => void submitImport()} disabled={!importCheck?.valid || validatingImport || submittingImport}>{submittingImport ? 'Importing…' : 'Import leads'}</button></div></section></div>}
    {importErrors.length > 0 && <div className="csv-errors"><div><strong>Some rows weren’t imported</strong><span>Review the row numbers and fix the source CSV before retrying.</span></div><button className="icon-button" aria-label="Dismiss import errors" onClick={onDismissImportErrors}><X size={16} /></button><ul>{importErrors.slice(0, 8).map((item) => <li key={`${item.row}-${item.message}`}><strong>Row {item.row}</strong>{item.message}</li>)}</ul>{importErrors.length > 8 && <small>And {importErrors.length - 8} more row errors.</small>}</div>}
    <div className="table-scroll"><table className="data-table leads-table"><thead><tr>
      <SortableHeader label="Lead" sortKey="name" activeSort={sortKey} direction={sortDirection} onSort={changeSort} filter={<select className="table-header-filter" aria-label="Filter by location" value={locationFilter} onChange={(event) => setLocationFilter(event.target.value)}><option value="">All locations</option>{locationOptions.map((location) => <option key={location} value={location}>{location}</option>)}</select>} />
      <SortableHeader label="Contact" sortKey="contact" activeSort={sortKey} direction={sortDirection} onSort={changeSort} />
      <SortableHeader label="Requirement" sortKey="requirement" activeSort={sortKey} direction={sortDirection} onSort={changeSort} filter={<select className="table-header-filter" aria-label="Filter by bedrooms" value={bedroomFilter} onChange={(event) => setBedroomFilter(event.target.value)}><option value="">All sizes</option>{bedroomOptions.map((bedrooms) => <option key={bedrooms} value={bedrooms}>{bedrooms} BHK</option>)}</select>} />
      <SortableHeader label="Source" sortKey="source" activeSort={sortKey} direction={sortDirection} onSort={changeSort} filter={<select className="table-header-filter" aria-label="Filter by source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as LeadSource | '')}><option value="">All sources</option>{Object.entries(sourceLabels).map(([source, label]) => <option key={source} value={source}>{label}</option>)}</select>} />
      <SortableHeader label="Stage" sortKey="stage" activeSort={sortKey} direction={sortDirection} onSort={changeSort} filter={<select className="table-header-filter" aria-label="Filter by stage" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">All stages</option>{stages.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select>} />
      <SortableHeader label="Added" sortKey="added" activeSort={sortKey} direction={sortDirection} onSort={changeSort} />
      <th aria-label="Open" />
    </tr></thead><tbody>{visibleLeads.map((lead) => <tr key={lead.id}><td><button className="lead-cell lead-cell-button" onClick={() => onOpenLead(lead)}><div className={`avatar avatar-${avatarColor(lead.full_name)}`}>{initials(lead.full_name)}</div><span><strong>{lead.full_name}</strong><small>{lead.preferred_location || 'Location not set'}</small></span></button></td><td><span>{lead.email || '—'}</span><small className="table-subline">{lead.phone || 'No phone'}</small></td><td><strong className="requirement-main">{lead.bhk ? `${lead.bhk} BHK` : 'Home search'}</strong><small className="table-subline">{budgetRange(lead)}</small></td><td><span className="source-label">{sourceLabels[lead.source]}</span></td><td><select className={`status-select status-${stageFor(lead.status).tone}`} aria-label={`Change ${lead.full_name} stage`} value={lead.status} disabled={!canWrite} onChange={(event) => void onUpdateStatus(lead, event.target.value as LeadStatus)}>{stages.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select></td><td className="muted-cell">{formatDate(lead.created_at)}</td><td><button className="icon-button row-open" aria-label={`Open ${lead.full_name}`} onClick={() => onOpenLead(lead)}><ChevronRight size={17} /></button></td></tr>)}</tbody></table></div>
    {!visibleLeads.length && !loading && <EmptyState title={hasActiveFilters ? 'No matching leads' : 'No leads yet'} description={hasActiveFilters ? 'Try another search or clear a filter.' : 'Your next great client relationship starts here.'} action={!hasActiveFilters && canWrite ? <button className="button button-primary" onClick={onAddLead}><Plus size={16} /> Add your first lead</button> : undefined} />}
    {loading && <div className="inline-loading"><span className="spinner" /> Updating your leads…</div>}
    <div className="table-footnote"><span>Showing {visibleLeads.length} of the latest {leads.length} leads; header filters apply to this list</span><span>Visibility is managed by your team role</span></div>
  </section>
}

function TasksPage({ tasks, filter, setFilter, users, currentUser, now, onComplete, onOpenLead, canWrite }: {
  tasks: (Task | Dashboard['due_today'][number])[]; filter: 'all' | 'today' | 'overdue' | 'completed'
  users: User[]; currentUser: User
  setFilter: (filter: 'all' | 'today' | 'overdue' | 'completed') => void; now: number
  onComplete: (task: Pick<Task, 'id' | 'title'>) => void; onOpenLead: (leadId: string) => void
  canWrite: boolean
}) {
  const filters = [{ id: 'all', label: 'All open' }, { id: 'today', label: 'Due today' }, { id: 'overdue', label: 'Overdue' }, { id: 'completed', label: 'Completed' }] as const
  return <section className="panel full-panel task-page-panel">
    <div className="panel-header task-header"><div><p className="eyebrow">Follow-up schedule</p><h2>{filter === 'completed' ? 'Completed follow-ups' : 'Your follow-up list'}</h2></div><div className="task-filter-pills">{filters.map((item) => <button key={item.id} className={`filter-pill ${filter === item.id ? 'filter-pill-active' : ''}`} onClick={() => setFilter(item.id)}>{item.label}</button>)}</div></div>
    {tasks.length ? <div className="task-list">{tasks.map((task) => {
      const completed = task.status === 'completed'
      return <div className={`task-row ${completed ? 'task-row-completed' : ''}`} key={task.id}>
        {completed ? <span className="task-completed-mark"><Check size={14} /></span> : canWrite ? <button className="task-check large-check" title="Mark complete" aria-label={`Mark ${task.title} complete`} onClick={() => onComplete(task)}><Check size={14} /></button> : <span className="task-completed-mark" aria-hidden="true" />}
        <div className="task-row-main"><strong>{task.title}</strong><button className="task-lead-link" onClick={() => onOpenLead(task.lead_id)}>{'lead_name' in task ? task.lead_name : 'Open lead'}<ArrowUpRight size={12} /></button>{'description' in task && task.description && <span className="task-description">{task.description}</span>}</div>
        <span className="task-assignee"><span className="avatar avatar-xs avatar-user">{initials(taskAssigneeName(task, users, currentUser))}</span>{taskAssigneeName(task, users, currentUser)}</span>
        <span className={`task-due ${!completed && taskIsOverdue(task.due_at, now) ? 'task-time-overdue' : ''}`}><CalendarDays size={15} />{completed && 'completed_at' in task && task.completed_at ? `Completed ${relativeDate(task.completed_at)}` : relativeDate(task.due_at)}</span>
      </div>
    })}</div> : <EmptyState title={filter === 'overdue' ? 'Nothing overdue' : filter === 'today' ? 'Nothing due today' : filter === 'completed' ? 'No completed follow-ups yet' : 'No open follow-ups'} description={filter === 'all' ? 'Create a follow-up from any lead to keep the conversation moving.' : filter === 'completed' ? 'Finished follow-ups will stay here for reference.' : 'You’re all caught up. Keep it that way.'} />}
    <div className="task-footnote"><Clock3 size={14} /> Dates and due-today boundaries use your team’s configured timezone.</div>
  </section>
}

function ActivityPage({ events, unreadCount, onMarkRead, onOpenEvent }: { events: AuditEvent[]; unreadCount: number; onMarkRead: () => void; onOpenEvent: (event: AuditEvent) => void }) {
  return <section className="panel full-panel activity-page-panel"><div className="panel-header"><div><p className="eyebrow">Shared with your team</p><h2>The activity feed</h2><p className="panel-subtitle">A clear view of the important changes happening across your workspace.</p></div>{unreadCount > 0 && <button className="button button-secondary" onClick={onMarkRead}><CheckCheck size={16} /> Mark as read</button>}</div>{events.length ? <ActivityList events={events} expanded onOpenEvent={onOpenEvent} /> : <EmptyState title="Nothing to report yet" description="Team changes and lead updates will show up here." />}<div className="activity-feed-note"><span className="secure-dot" /> This feed follows your team role and lead access.</div></section>
}

const auditFieldLabels: Record<string, string> = {
  assigned_to: 'Assignee',
  bhk: 'Bedrooms',
  budget_max_inr: 'Maximum budget',
  budget_min_inr: 'Minimum budget',
  changed_fields: 'Updated fields',
  created_count: 'Leads imported',
  due_at: 'Due date',
  full_name: 'Name',
  is_active: 'Account status',
  role: 'Role',
  source: 'Source',
  status: 'Stage',
  task_title: 'Follow-up task',
  activity_type: 'Activity type',
  preferred_location: 'Preferred location',
}

function auditFieldLabel(key: string) {
  return auditFieldLabels[key] ?? key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function auditValue(key: string, value: unknown) {
  if (value == null) return 'None'
  if (key === 'budget_min_inr' || key === 'budget_max_inr') {
    return typeof value === 'number' ? formatCurrency(value) : 'Budget updated'
  }
  if (key === 'assigned_to') return 'Assignee changed'
  if (key === 'status') {
    return String(value)
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (letter) => letter.toUpperCase())
  }
  if (typeof value === 'boolean') return value ? 'Active' : 'Inactive'
  return String(value).replaceAll('_', ' ')
}

function formatAuditChange(key: string, value: unknown, entityType: string) {
  if (key === 'changed_fields' && Array.isArray(value)) {
    const fields = value.filter((field): field is string => typeof field === 'string')
    return fields.length ? `Updated: ${fields.map(auditFieldLabel).join(', ')}` : 'Details updated'
  }
  const label = key === 'status' && entityType === 'task' ? 'Status' : auditFieldLabel(key)
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    if ('from' in value && 'to' in value) {
      if (key === 'assigned_to') return 'Assignee changed'
      return `${label}: ${auditValue(key, value.from)} → ${auditValue(key, value.to)}`
    }
    return `${label} updated`
  }
  if (Array.isArray(value)) return `${label}: ${value.map((item) => String(item).replaceAll('_', ' ')).join(', ')}`
  return `${label}: ${auditValue(key, value)}`
}

function ActivityList({ events, expanded = false, onOpenEvent }: { events: AuditEvent[]; expanded?: boolean; onOpenEvent?: (event: AuditEvent) => void }) {
  return <div className={`activity-list ${expanded ? 'activity-list-expanded' : ''}`}>{events.map((event, index) => {
    const actionLabel = event.lead_id ? 'Open lead' : event.entity_type === 'task' ? 'Open follow-up' : event.entity_type === 'user' ? 'Open team' : 'View activity'
    const changes = Object.entries(event.changes ?? {})
    const taskTitleEntry = event.entity_type === 'task' ? changes.find(([key]) => key === 'task_title') : undefined
    const visibleChanges = taskTitleEntry ? changes.filter(([key]) => key !== 'task_title') : changes
    const detailText = visibleChanges.map(([key, value]) => formatAuditChange(key, value, event.entity_type)).join(' · ')
    const content = <>
      <span className={`activity-avatar activity-${index % 4}`}>{event.actor_name ? initials(event.actor_name) : <UserRound size={14} />}</span>
      <span className="activity-body">
        <span className="activity-summary"><strong>{event.actor_name || 'UrbanNest team'}</strong> {event.summary.replace(/^[A-Z]/, (letter) => letter.toLowerCase())}</span>
        {taskTitleEntry ? (
          <span className="activity-detail activity-task-detail" aria-label="What changed">
            <strong className="activity-task-title">{String(taskTitleEntry[1])}</strong>
            {detailText && <span className="activity-task-changes">{detailText}</span>}
          </span>
        ) : detailText && <span className="activity-detail" aria-label="What changed">{detailText}</span>}
        <time>{relativeDate(event.created_at)}</time>
        {onOpenEvent && <span className="activity-open-link">{actionLabel}<ArrowUpRight size={12} /></span>}
      </span>
      <span className={`activity-read-dot ${event.is_read ? 'is-read' : ''}`} />
    </>
    return onOpenEvent
      ? <button className="activity-item activity-item-action" key={event.id} onClick={() => onOpenEvent(event)} aria-label={`${actionLabel}: ${event.summary}`}>{content}</button>
      : <div className="activity-item" key={event.id}>{content}</div>
  })}</div>
}

function NotificationPanel({ events, unreadCount, onClose, onOpenEvent, onOpenActivity }: { events: AuditEvent[]; unreadCount: number; onClose: () => void; onOpenEvent: (event: AuditEvent) => void; onOpenActivity: () => void }) {
  return <><button className="popover-backdrop" aria-label="Close notifications" onClick={onClose} /><section className="notification-panel"><div className="notification-panel-head"><div><strong>Notifications</strong><span>{unreadCount ? `${unreadCount} unread updates` : 'You’re all caught up'}</span></div><button className="icon-button" aria-label="Close notifications" onClick={onClose}><X size={17} /></button></div>{events.length ? <ActivityList events={events.slice(0, 4)} onOpenEvent={onOpenEvent} /> : <EmptyState title="No new updates" description="Your team feed is quiet for now." />}<button className="panel-link" onClick={onOpenActivity}>Open activity feed <ArrowUpRight size={14} /></button></section></>
}

function ProfilePage({ user, onChangePassword, onSaveProfile, onConfirmAction }: { user: User; onChangePassword: (currentPassword: string, newPassword: string) => Promise<boolean>; onSaveProfile: (changes: ProfileUpdateRequest) => Promise<boolean>; onConfirmAction: (request: ConfirmationRequest) => void }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const storedPhone = splitStoredPhone(user.phone, user.phone_region)
  const [phone, setPhone] = useState(storedPhone.nationalNumber)
  const [phoneRegion, setPhoneRegion] = useState(storedPhone.region)
  const [phoneError, setPhoneError] = useState('')
  const [formError, setFormError] = useState('')
  const [profileSaving, setProfileSaving] = useState(false)
  const [saving, setSaving] = useState(false)

  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    let normalizedPhone
    try {
      normalizedPhone = normalizePhone(phone, phoneRegion)
      setPhoneError('')
    } catch (validationError) {
      setPhoneError(validationError instanceof Error ? validationError.message : 'Enter a valid phone number.')
      return
    }
    onConfirmAction({
      title: 'Save your profile changes?',
      message: `This will ${normalizedPhone ? 'set your profile phone number' : 'remove your profile phone number'}.`,
      confirmLabel: 'Save changes',
      onConfirm: async () => {
        setProfileSaving(true)
        try {
          if (!await onSaveProfile({
            phone: normalizedPhone?.phone ?? null,
            phone_country_code: normalizedPhone?.phone_country_code ?? null,
            phone_region: normalizedPhone?.phone_region ?? null,
            phone_national_number: normalizedPhone?.phone_national_number ?? null,
          })) {
            throw new Error('Your profile was not updated. Review the error message and try again.')
          }
          setPhone(normalizedPhone?.phone_national_number ?? '')
          if (normalizedPhone) setPhoneRegion(normalizedPhone.phone_region)
        } finally {
          setProfileSaving(false)
        }
      },
    })
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError('')
    if (newPassword !== confirmPassword) {
      setFormError('The new passwords do not match.')
      return
    }
    onConfirmAction({
      title: 'Change your password?',
      message: 'Your current password will stop working. The server will revoke the old token and issue a replacement for this session.',
      confirmLabel: 'Change password',
      onConfirm: async () => {
        setSaving(true)
        try {
          if (!await onChangePassword(currentPassword, newPassword)) {
            throw new Error('Password was not changed. Review the error message and try again.')
          }
          setCurrentPassword('')
          setNewPassword('')
          setConfirmPassword('')
        } finally {
          setSaving(false)
        }
      },
    })
  }

  return <section className="profile-page-grid">
    <article className="panel profile-summary-card">
      <div className="profile-summary-avatar">{initials(user.full_name)}</div>
      <div><p className="eyebrow">Your account</p><h2>{user.full_name}</h2></div>
      <span className="role-pill">{user.role}</span>
      <dl className="profile-details">
        <div><dt>Email</dt><dd>{user.email}</dd></div>
        <div><dt>Role</dt><dd>{user.role}</dd></div>
        {user.is_superuser && <div><dt>Access level</dt><dd>Development superuser (team-scoped)</dd></div>}
        <div><dt>Phone</dt><dd>{user.phone || 'Not added'}</dd></div>
        <div><dt>Account status</dt><dd>{user.is_active ? 'Active' : 'Inactive'}</dd></div>
        <div><dt>Team ID</dt><dd>{user.team_id}</dd></div>
        <div><dt>Password setup</dt><dd>{user.must_change_password ? 'Change required' : 'Up to date'}</dd></div>
      </dl>
      <form className="account-form profile-phone-form" onSubmit={(event) => void saveProfile(event)}>
        <PhoneNumberInput label="Phone number" value={phone} region={phoneRegion} onChange={(value) => { setPhone(value); setPhoneError('') }} onRegionChange={setPhoneRegion} error={phoneError} />
        <button className="button button-secondary" disabled={profileSaving}>{profileSaving ? 'Saving…' : 'Save phone number'}</button>
      </form>
    </article>
    <article className="panel password-panel">
      <div className="panel-header"><div><p className="eyebrow">Sign-in security</p><h2>Change your password</h2><p className="panel-subtitle">Use at least 12 characters. Your current session will be renewed securely.</p></div><KeyRound size={20} /></div>
      <form className="account-form" onSubmit={(event) => void submit(event)}>
        <label>Current password<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label>
        <label>New password<input type="password" autoComplete="new-password" minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required /></label>
        <label>Confirm new password<input type="password" autoComplete="new-password" minLength={12} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required /></label>
        {formError && <p className="inline-form-error" role="alert">{formError}</p>}
        <button className="button button-primary" disabled={saving}>{saving ? 'Updating…' : 'Update password'}</button>
      </form>
    </article>
  </section>
}

function TeamPage({ currentUser, users, temporaryPassword, onClearTemporaryPassword, onCreate, onUpdate, onResetPassword, onError, onConfirmAction, onResetAll }: {
  currentUser: User
  users: User[]
  temporaryPassword: { email: string; password: string } | null
  onClearTemporaryPassword: () => void
  onCreate: (payload: UserCreateRequest) => Promise<void>
  onUpdate: (userId: string, changes: UserUpdateRequest) => Promise<void>
  onResetPassword: (user: User) => Promise<void>
  onError: (message: string) => void
  onConfirmAction: (request: ConfirmationRequest) => void
  onResetAll: () => Promise<void>
}) {
  const [showForm, setShowForm] = useState(false)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [managerId, setManagerId] = useState('')
  const [fullNameError, setFullNameError] = useState('')
  const [emailError, setEmailError] = useState('')
  const [role, setRole] = useState<UserRole>('agent')
  const [permissions, setPermissions] = useState({
    can_read: true,
    can_write: true,
    can_delete: false,
    can_manage_users: false,
  })
  const [saving, setSaving] = useState(false)
  const ownerAccess = currentUser.role === 'owner' || currentUser.is_superuser
  const canWriteTeam = ownerAccess || currentUser.role !== 'co_owner' || currentUser.can_write
  const canDeleteUsers = ownerAccess || currentUser.role !== 'co_owner' || currentUser.can_delete

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onError('')
    const normalizedName = normalizeName(fullName)
    const normalizedEmail = normalizeEmail(email)
    const nextNameError = validateName(normalizedName)
    const nextEmailError = validateEmail(normalizedEmail)
    setFullNameError(nextNameError)
    setEmailError(nextEmailError)
    if (nextNameError || nextEmailError) return
    const newUser: UserCreateRequest = {
      full_name: normalizedName,
      email: normalizedEmail,
      role,
      ...(ownerAccess && role === 'agent' ? { manager_id: managerId || null } : {}),
      ...(role === 'co_owner' ? permissions : {}),
    }
    onConfirmAction({
      title: 'Create this team account?',
      message: `Create ${newUser.full_name} (${newUser.email}) as ${newUser.role.replace('_', ' ')}? A temporary password will be generated and shown once; share it privately, and the user will have to change it at first sign-in.`,
      confirmLabel: 'Create account',
      onConfirm: async () => {
        setSaving(true)
        try {
          await onCreate(newUser)
          setFullName('')
          setEmail('')
          setManagerId('')
          setRole('agent')
          setPermissions({ can_read: true, can_write: true, can_delete: false, can_manage_users: false })
          setShowForm(false)
        } finally {
          setSaving(false)
        }
      },
    })
  }

  return <section className="panel full-panel team-page-panel">
    <div className="panel-header team-header">
      <div><p className="eyebrow">Team access</p><h2>People in your workspace</h2><p className="panel-subtitle">{ownerAccess ? 'Create accounts, adjust access, and help teammates get back in.' : 'Manage agent access and reset passwords for your team.'}</p></div>
      <div className="team-header-actions">
        {ownerAccess && <button className="button button-danger" onClick={() => onConfirmAction({
          title: 'Reset every account password?',
          message: 'This resets every account in the team, including inactive accounts and your own. Everyone will be signed out and must change their new temporary password at next sign-in. A CSV containing all temporary passwords will download once; keep it private and share each user’s credentials securely.',
          confirmLabel: 'Reset all & download CSV',
          onConfirm: onResetAll,
        })}>Reset all passwords</button>}
        {canWriteTeam && <button className="button button-primary" onClick={() => setShowForm((show) => !show)}><UserPlus size={16} /> {showForm ? 'Close form' : 'New user'}</button>}
      </div>
    </div>
    {temporaryPassword && <div className="temporary-password-card" role="status"><div><strong>Temporary password for {temporaryPassword.email}</strong><p>Share this one-time password securely. The user must change it after signing in.</p><code>{temporaryPassword.password}</code></div><button className="icon-button" aria-label="Dismiss temporary password" onClick={onClearTemporaryPassword}><X size={16} /></button></div>}
    {showForm && canWriteTeam && <form className="team-create-form account-form" onSubmit={(event) => void submit(event)}>
      <label>Full name<input value={fullName} onChange={(event) => { setFullName(event.target.value); setFullNameError('') }} onBlur={() => { const name = normalizeName(fullName); setFullName(name); setFullNameError(validateName(name)) }} autoComplete="name" maxLength={160} required aria-invalid={Boolean(fullNameError)} />{fullNameError && <small className="inline-form-error">{fullNameError}</small>}</label>
      <label>Email address<input type="email" value={email} onChange={(event) => { setEmail(event.target.value); setEmailError('') }} onBlur={() => { const normalized = normalizeEmail(email); setEmail(normalized); setEmailError(normalized ? validateEmail(normalized) : '') }} autoComplete="email" maxLength={320} required aria-invalid={Boolean(emailError)} />{emailError && <small className="inline-form-error">{emailError}</small>}</label>
      <label>Role<select value={role} onChange={(event) => setRole(event.target.value as UserRole)}><option value="agent">Agent</option>{ownerAccess && <><option value="manager">Manager</option><option value="co_owner">Co-owner</option></>}</select></label>
      {ownerAccess && role === 'agent' && <label>Reports to<select value={managerId} onChange={(event) => setManagerId(event.target.value)}><option value="">No manager</option>{users.filter((member) => member.role === 'manager' && member.is_active).map((manager) => <option key={manager.id} value={manager.id}>{manager.full_name}</option>)}</select></label>}
      {role === 'co_owner' && ownerAccess && <fieldset className="co-owner-permissions">
        <legend>Co-owner access</legend>
        {([
          ['can_read', 'Read workspace data'],
          ['can_write', 'Create and edit records'],
          ['can_delete', 'Delete or deactivate records'],
          ['can_manage_users', 'Manage agent accounts'],
        ] as const).map(([field, label]) => <label className="permission-checkbox" key={field}>
          <input type="checkbox" checked={permissions[field]} onChange={(event) => setPermissions((current) => ({ ...current, [field]: event.target.checked }))} />
          {label}
        </label>)}
      </fieldset>}
      <button className="button button-primary" disabled={saving}>{saving ? 'Creating…' : 'Create account'}</button>
    </form>}
    <div className="team-member-list">
      {users.map((member) => <article className="team-member-row" key={member.id}>
        <div className="avatar avatar-user">{initials(member.full_name)}</div>
        <div className="team-member-identity"><strong>{member.full_name}</strong><span>{member.email}</span></div>
        {ownerAccess && member.id !== currentUser.id && member.role !== 'owner'
          ? <label className="member-role-control"><span>Role</span><select aria-label={`Role for ${member.full_name}`} value={member.role} onChange={(event) => {
            const nextRole = event.target.value as UserRole
            if (nextRole === member.role) return
            onConfirmAction({
              title: `Change ${member.full_name}'s role?`,
              message: `This changes their workspace permissions from ${member.role.replace('_', ' ')} to ${nextRole.replace('_', ' ')} and revokes their current sessions.`,
              confirmLabel: 'Change role',
              onConfirm: () => onUpdate(member.id, { role: nextRole }),
            })
          }}><option value="manager">Manager</option><option value="co_owner">Co-owner</option><option value="agent">Agent</option></select></label>
          : <span className="role-pill">{member.role}</span>}
        {ownerAccess && member.role === 'agent' && <label className="member-role-control"><span>Reports to</span><select aria-label={`Manager for ${member.full_name}`} value={member.manager_id ?? ''} onChange={(event) => {
          const nextManagerId = event.target.value || null
          if (nextManagerId === member.manager_id) return
          onConfirmAction({
            title: `Change ${member.full_name}'s manager?`,
            message: 'This changes which manager can view and assign work to this agent.',
            confirmLabel: 'Change manager',
            onConfirm: () => onUpdate(member.id, { manager_id: nextManagerId }),
          })
        }}><option value="">No manager</option>{users.filter((candidate) => candidate.role === 'manager' && candidate.is_active).map((manager) => <option key={manager.id} value={manager.id}>{manager.full_name}</option>)}</select></label>}
        {ownerAccess && member.role === 'co_owner' && member.id !== currentUser.id && <div className="member-permissions">
          {([
            ['can_read', 'Read'],
            ['can_write', 'Write'],
            ['can_delete', 'Delete or deactivate'],
            ['can_manage_users', 'Manage users'],
          ] as const).map(([field, label]) => <label className="permission-checkbox" key={field}>
            <input type="checkbox" checked={member[field]} aria-label={`${label} access for ${member.full_name}`} onChange={(event) => {
              const enabled = event.target.checked
              onConfirmAction({
                title: `Change ${label.toLowerCase()} access for ${member.full_name}?`,
                message: `${enabled ? 'Enable' : 'Disable'} ${label.toLowerCase()} access for this co-owner?`,
                confirmLabel: 'Update access',
                onConfirm: () => onUpdate(member.id, { [field]: enabled }),
              })
            }} />
            {label}
          </label>)}
        </div>}
        <span className={`member-status ${member.is_active ? 'member-status-active' : ''}`}>{member.is_active ? 'Active' : 'Inactive'}</span>
        {member.id !== currentUser.id && canWriteTeam && <div className="member-actions">
          <button className="button button-secondary" disabled={member.is_active && !canDeleteUsers} onClick={() => member.is_active
            ? onConfirmAction({
              title: `Deactivate ${member.full_name}?`,
              message: 'They will lose access to this workspace until an owner or manager reactivates their account. Their existing CRM records will remain.',
              confirmLabel: 'Deactivate account',
              onConfirm: () => onUpdate(member.id, { is_active: false }),
            })
            : onConfirmAction({
              title: `Reactivate ${member.full_name}?`,
              message: 'They will regain access to the workspace using their current password, unless an administrator resets it separately.',
              confirmLabel: 'Reactivate account',
              onConfirm: () => onUpdate(member.id, { is_active: true }),
            })}>{member.is_active ? 'Deactivate' : 'Reactivate'}</button>
          <button type="button" className="button button-secondary reset-password-button" aria-label={`Reset password for ${member.full_name}`} onClick={() => onConfirmAction({
            title: `Reset ${member.full_name}'s password?`,
            message: 'Their existing password and sessions will stop working. A temporary password will be generated and shown once; share it privately. They must choose a new password at their next sign-in.',
            confirmLabel: 'Reset password',
            onConfirm: () => onResetPassword(member),
          })}><RotateCcw size={15} /><span>Reset password</span></button>
        </div>}
      </article>)}
      {!users.length && <EmptyState title="No team members found" description="New accounts will appear here after they are created." />}
    </div>
    <p className="team-access-note">Access controls are enforced by the API. Managers and user-enabled co-owners manage agents; only owners can create managers or co-owners.</p>
  </section>
}

type OrgChartTreeNode = {
  id: string
  name: string
  detail: string
  kind: 'company' | 'group' | 'person'
  role?: UserRole
  children: OrgChartTreeNode[]
}

function orgRoleLabel(role: UserRole) {
  return role === 'co_owner' ? 'Co-owner' : role === 'owner' ? 'Owner' : role === 'manager' ? 'Manager' : 'Agent'
}

function buildOrgChartTree(members: OrgChartMember[]): OrgChartTreeNode {
  const memberNodes = new Map<string, OrgChartTreeNode>()
  for (const member of members) {
    memberNodes.set(member.id, {
      id: member.id,
      name: member.full_name,
      detail: orgRoleLabel(member.role),
      kind: 'person',
      role: member.role,
      children: [],
    })
  }

  const leadership: OrgChartTreeNode[] = []
  const managers: OrgChartTreeNode[] = []
  for (const member of members) {
    const node = memberNodes.get(member.id)
    if (!node) continue
    if (member.role === 'owner' || member.role === 'co_owner') leadership.push(node)
    if (member.role === 'manager') managers.push(node)
  }
  const assignedAgents = new Set<string>()

  for (const manager of managers) {
    manager.children = members
      .filter((member) => member.role === 'agent' && member.manager_id === manager.id)
      .flatMap((member) => {
        const node = memberNodes.get(member.id)
        if (!node) return []
        assignedAgents.add(member.id)
        return [node]
      })
    manager.detail = `${orgRoleLabel('manager')} · ${manager.children.length} direct report${manager.children.length === 1 ? '' : 's'}`
  }

  const unassignedAgents = members
    .filter((member) => member.role === 'agent' && !assignedAgents.has(member.id))
    .flatMap((member) => {
      const node = memberNodes.get(member.id)
      return node ? [node] : []
    })
  const children: OrgChartTreeNode[] = []
  if (leadership.length) children.push({ id: 'leadership', name: 'Leadership', detail: `${leadership.length} member${leadership.length === 1 ? '' : 's'}`, kind: 'group', children: leadership })
  if (managers.length) children.push({ id: 'managers', name: 'Managers', detail: `${managers.length} member${managers.length === 1 ? '' : 's'}`, kind: 'group', children: managers })
  if (unassignedAgents.length) children.push({ id: 'unassigned-agents', name: 'Agents without a manager', detail: `${unassignedAgents.length} member${unassignedAgents.length === 1 ? '' : 's'}`, kind: 'group', children: unassignedAgents })

  return {
    id: 'organization',
    name: 'UrbanNest Realty',
    detail: `${members.length} active team member${members.length === 1 ? '' : 's'}`,
    kind: 'company',
    children,
  }
}

function filterOrgChartTree(node: OrgChartTreeNode, query: string): OrgChartTreeNode | null {
  if (!query) return node
  const children = node.children
    .map((child) => filterOrgChartTree(child, query))
    .filter((child): child is OrgChartTreeNode => child !== null)
  const matches = `${node.name} ${node.detail}`.toLowerCase().includes(query)
  return matches || children.length ? { ...node, children } : null
}

function flattenOrgChartTree(node: OrgChartTreeNode): OrgChartTreeNode[] {
  return [node, ...node.children.flatMap(flattenOrgChartTree)]
}

function OrgChartPage({ members, loading, error, onRetry }: {
  members: OrgChartMember[]
  loading: boolean
  error: string
  onRetry: () => void
}) {
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('organization')
  const [expandedIds, setExpandedIds] = useState<Set<string> | null>(null)
  const tree = useMemo(() => buildOrgChartTree(members), [members])
  const filteredTree = useMemo(() => filterOrgChartTree(tree, query.trim().toLowerCase()), [query, tree])
  const visibleTree = filteredTree ?? { ...tree, children: [] }
  const selectedNode = flattenOrgChartTree(visibleTree).find((node) => node.id === selectedId) ?? visibleTree
  const selectedMember = selectedNode.kind === 'person' ? members.find((member) => member.id === selectedNode.id) : null
  const selectedManager = selectedMember?.manager_id
    ? members.find((member) => member.id === selectedMember.manager_id)
    : null
  const selectedReportCount = selectedNode.kind === 'person' ? selectedNode.children.length : 0

  const renderNode = (node: OrgChartTreeNode): React.ReactNode => {
    const expanded = expandedIds === null || expandedIds.has(node.id)
    return (
      <li className={`org-chart-node org-chart-node-${node.kind}`} role="treeitem" aria-expanded={node.children.length ? expanded : undefined} key={node.id}>
        <div className={`org-chart-node-row ${selectedId === node.id ? 'org-chart-node-selected' : ''}`}>
          <button type="button" className="org-chart-node-select" aria-pressed={selectedId === node.id} onClick={() => setSelectedId(node.id)}>
            <span className="org-chart-node-icon">{node.kind === 'company' ? <Network size={18} /> : node.kind === 'group' ? <Users size={17} /> : <UserRound size={17} />}</span>
            <span className="org-chart-node-copy"><strong>{node.name}</strong><small>{node.detail}</small></span>
          </button>
          {node.children.length > 0 && <button
            type="button"
            className="org-chart-node-toggle"
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${node.name}`}
            aria-expanded={expanded}
            onClick={() => setExpandedIds((current) => {
              const next = current ? new Set(current) : new Set(flattenOrgChartTree(visibleTree).map((item) => item.id))
              if (expanded) next.delete(node.id)
              else next.add(node.id)
              return next
            })}
          ><ChevronDown size={16} className={expanded ? '' : 'org-chart-chevron-collapsed'} /></button>}
        </div>
        {node.children.length > 0 && expanded && <ul className="org-chart-children" role="group">{node.children.map(renderNode)}</ul>}
      </li>
    )
  }

  if (loading && members.length === 0) {
    return <div className="org-chart-state" role="status"><span className="spinning"><RefreshCw size={18} /></span><p>Loading your team structure…</p></div>
  }
  if (error && members.length === 0) {
    return <EmptyState title="Could not load the org chart" description={error} action={<button className="button button-secondary" onClick={onRetry}>Try again</button>} />
  }
  if (!members.length) {
    return <EmptyState title="No active team members" description="Active team accounts will appear here as the organization grows." />
  }

  return (
    <section className="org-chart-explorer">
      <div className="org-chart-toolbar">
        <label className="org-chart-search">
          <Search size={17} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a person or role" aria-label="Search the org chart" />
          {query && <button type="button" aria-label="Clear search" onClick={() => setQuery('')}><X size={15} /></button>}
        </label>
        <div className="org-chart-actions">
          <button type="button" className="button button-secondary" onClick={() => setExpandedIds(new Set(flattenOrgChartTree(visibleTree).map((node) => node.id)))}>Expand all</button>
          <button type="button" className="button button-secondary" onClick={() => setExpandedIds(new Set())}>Collapse all</button>
        </div>
      </div>
      {error && <p className="org-chart-stale-note" role="status">Showing the last loaded org chart. Refresh to try again.</p>}
      <div className="org-chart-layout">
        <div className="org-chart-canvas">
          {filteredTree
            ? <ul className="org-chart-tree" role="tree" aria-label="Active team organization">{renderNode(visibleTree)}</ul>
            : <EmptyState title="No matching team members" description="Try a different name or role." />}
        </div>
        <aside className="org-chart-details" aria-live="polite">
          <p className="eyebrow">Explorer</p>
          <h2>{selectedNode.name}</h2>
          <p>{selectedNode.detail}</p>
          {selectedMember && <>
            <div className="org-chart-fact"><span>Role</span><strong>{orgRoleLabel(selectedMember.role)}</strong></div>
            {selectedMember.role === 'agent' && <div className="org-chart-fact"><span>Reports to</span><strong>{selectedManager?.full_name ?? 'No manager assigned'}</strong></div>}
            <div className="org-chart-fact"><span>Direct reports</span><strong>{selectedReportCount}</strong></div>
          </>}
          {selectedNode.kind !== 'person' && <div className="org-chart-fact"><span>Members in this branch</span><strong>{flattenOrgChartTree(selectedNode).filter((node) => node.kind === 'person').length}</strong></div>}
        </aside>
      </div>
    </section>
  )
}

function LeadDrawer({ lead: initialLead, token, currentUser, onClose, onUpdated, onError, onConfirmAction, canWrite }: { lead: Lead; token: string; currentUser: User; onClose: () => void; onUpdated: (lead: Lead) => void; onError: (message: string) => void; onConfirmAction: (request: ConfirmationRequest) => void; canWrite: boolean }) {
  const [lead, setLead] = useState(initialLead)
  const [assignees, setAssignees] = useState<LeadAssignee[]>([])
  const [activities, setActivities] = useState<Activity[]>([])
  const [activityText, setActivityText] = useState('')
  const [activityType, setActivityType] = useState<Activity['type']>('call')
  const [taskTitle, setTaskTitle] = useState('')
  const [taskDate, setTaskDate] = useState(() => {
    const tomorrow = new Date(Date.now() + 86_400_000)
    return `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, '0')}-${String(tomorrow.getDate()).padStart(2, '0')}T10:00`
  })
  const [activeForm, setActiveForm] = useState<'activity' | 'task' | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api<Activity[]>(`/leads/${initialLead.id}/activities?limit=50`, token)
      .then(setActivities)
      .catch((requestError: unknown) => onError(getErrorMessage(requestError)))
  }, [initialLead, onError, token])

  const canChangeAssignment = currentUser.is_superuser || ['owner', 'co_owner', 'manager'].includes(currentUser.role)

  useEffect(() => {
    if (!canChangeAssignment) return
    let active = true
    api<LeadAssignee[]>('/leads/assignees', token)
      .then((items) => {
        if (active) setAssignees(items)
      })
      .catch((requestError: unknown) => {
        if (active) onError(getErrorMessage(requestError))
      })
    return () => {
      active = false
    }
  }, [canChangeAssignment, onError, token])

  const changeAssignee = (assignedTo: string) => {
    if (!assignedTo || assignedTo === lead.assigned_to || !canWrite) return
    const assignee = assignees.find((item) => item.id === assignedTo)
    if (!assignee) return
    onConfirmAction({
      title: `Assign ${lead.full_name} to ${assignee.full_name}?`,
      message: 'This changes who owns the next follow-up for this lead.',
      confirmLabel: 'Change assignment',
      onConfirm: async () => {
        try {
          const updated = await api<Lead>(`/leads/${lead.id}`, token, {
            method: 'PATCH',
            body: JSON.stringify({ assigned_to: assignedTo }),
          })
          setLead(updated)
          onUpdated(updated)
        } catch (requestError) {
          const message = getErrorMessage(requestError)
          onError(message)
          throw new Error(message)
        }
      },
    })
  }

  const changeStage = (status: LeadStatus) => {
    if (status === lead.status) return
    onConfirmAction({
      title: `Move ${lead.full_name} to ${stageFor(status).label.toLowerCase()}?`,
      message: `This updates the lead’s pipeline stage from ${stageFor(lead.status).label.toLowerCase()} to ${stageFor(status).label.toLowerCase()}.`,
      confirmLabel: 'Update stage',
      onConfirm: async () => {
        try {
          const updated = await api<Lead>(`/leads/${lead.id}`, token, { method: 'PATCH', body: JSON.stringify({ status }) })
          setLead(updated)
          onUpdated(updated)
        } catch (requestError) {
          const message = getErrorMessage(requestError)
          onError(message)
          throw new Error(message)
        }
      },
    })
  }

  const submitActivity = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onConfirmAction({
      title: `Log ${activityType.replaceAll('_', ' ')} for ${lead.full_name}?`,
      message: 'This will add an entry to the lead’s shared activity timeline.',
      confirmLabel: 'Save activity',
      onConfirm: async () => {
        setSaving(true)
        try {
          const activity = await api<Activity>(`/leads/${lead.id}/activities`, token, { method: 'POST', body: JSON.stringify({ type: activityType, body: activityText }) })
          setActivities((items) => [activity, ...items])
          setActivityText('')
          setActiveForm(null)
          onError('')
          onUpdated(lead)
        } catch (requestError) {
          const message = getErrorMessage(requestError)
          onError(message)
          throw new Error(message)
        } finally {
          setSaving(false)
        }
      },
    })
  }

  const submitTask = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onConfirmAction({
      title: `Create this follow-up for ${lead.full_name}?`,
      message: `“${taskTitle}” will be added to your task list, due ${new Date(taskDate).toLocaleString()}.`,
      confirmLabel: 'Create follow-up',
      onConfirm: async () => {
        setSaving(true)
        try {
          await api<Task>('/tasks', token, { method: 'POST', body: JSON.stringify({ lead_id: lead.id, title: taskTitle, due_at: new Date(taskDate).toISOString() }) })
          setTaskTitle('')
          setActiveForm(null)
          onError('')
          onUpdated(lead)
        } catch (requestError) {
          const message = getErrorMessage(requestError)
          onError(message)
          throw new Error(message)
        } finally {
          setSaving(false)
        }
      },
    })
  }

  return <><button className="drawer-backdrop" aria-label="Close lead details" onClick={onClose} /><aside className="lead-drawer"><div className="drawer-topbar"><span className="eyebrow">Lead profile</span><button className="icon-button" aria-label="Close lead details" onClick={onClose}><X size={19} /></button></div><div className="drawer-lead-head"><div className={`avatar avatar-large avatar-${avatarColor(lead.full_name)}`}>{initials(lead.full_name)}</div><div><h2>{lead.full_name}</h2><span className="drawer-subtitle">Added {formatDate(lead.created_at, { day: 'numeric', month: 'long', year: 'numeric' })}</span></div></div>
    <div className="drawer-stage"><label htmlFor="drawer-status">Current stage</label><select id="drawer-status" className={`status-select status-${stageFor(lead.status).tone}`} value={lead.status} disabled={!canWrite} onChange={(event) => void changeStage(event.target.value as LeadStatus)}>{stages.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select></div>
    {canChangeAssignment && <div className="drawer-stage"><label htmlFor="drawer-assignee">Assigned to</label><select id="drawer-assignee" value={lead.assigned_to ?? ''} disabled={!canWrite} onChange={(event) => changeAssignee(event.target.value)}>{!lead.assigned_to && <option value="" disabled>Unassigned</option>}{lead.assigned_to === currentUser.id && !assignees.some((item) => item.id === currentUser.id) && <option value={currentUser.id}>{currentUser.full_name} · default</option>}{assignees.map((assignee) => <option key={assignee.id} value={assignee.id}>{assignee.full_name} · {assignee.role.replace('_', ' ')}</option>)}</select></div>}
    {canWrite && <div className="drawer-actions"><button className="button button-secondary" onClick={() => setActiveForm(activeForm === 'activity' ? null : 'activity')}><ActivityIcon size={15} /> Log activity</button><button className="button button-secondary" onClick={() => setActiveForm(activeForm === 'task' ? null : 'task')}><CalendarDays size={15} /> Add follow-up</button></div>}
    {canWrite && activeForm === 'activity' && <form className="drawer-form" onSubmit={(event) => void submitActivity(event)}><div className="drawer-form-heading"><strong>Log an interaction</strong><button type="button" className="icon-button" aria-label="Close form" onClick={() => setActiveForm(null)}><X size={15} /></button></div><select value={activityType} onChange={(event) => setActivityType(event.target.value as Activity['type'])}><option value="call">Call</option><option value="note">Note</option><option value="site_visit">Site visit</option><option value="email">Email</option><option value="whatsapp">WhatsApp</option></select><textarea value={activityText} onChange={(event) => setActivityText(event.target.value)} placeholder="What happened? Add a useful note…" rows={3} required /><button className="button button-primary" disabled={saving}>{saving ? 'Saving…' : 'Save activity'}</button></form>}
    {canWrite && activeForm === 'task' && <form className="drawer-form" onSubmit={(event) => void submitTask(event)}><div className="drawer-form-heading"><strong>Plan a follow-up</strong><button type="button" className="icon-button" aria-label="Close form" onClick={() => setActiveForm(null)}><X size={15} /></button></div><input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} placeholder="e.g. Call to confirm site visit" maxLength={200} required /><input type="datetime-local" value={taskDate} onChange={(event) => setTaskDate(event.target.value)} required /><button className="button button-primary" disabled={saving}>{saving ? 'Saving…' : 'Create follow-up'}</button></form>}
    <div className="detail-section"><p className="eyebrow">Property preferences</p><div className="detail-cards"><div className="detail-card"><span>Budget</span><strong>{budgetRange(lead)}</strong></div><div className="detail-card"><span>Configuration</span><strong>{lead.bhk ? `${lead.bhk} BHK` : 'Not specified'}</strong></div></div><div className="detail-location"><MapPin size={16} /><span>{lead.preferred_location || 'Preferred location not specified'}</span></div></div>
    <div className="detail-section contact-section"><p className="eyebrow">Contact details</p>{lead.email && <a href={`mailto:${lead.email}`}><span className="contact-icon">@</span>{lead.email}<ArrowUpRight size={13} /></a>}{lead.phone && <a href={`tel:${lead.phone}`}><span className="contact-icon">#</span>{lead.phone}<ArrowUpRight size={13} /></a>}{!lead.email && !lead.phone && <span className="empty-contact">No contact details added</span>}<div className="contact-source">Source <strong>{sourceLabels[lead.source]}</strong></div></div>
    <AICopilotPreview lead={lead} />
    <div className="detail-section timeline-section"><div className="timeline-head"><div><p className="eyebrow">Lead history</p><h3>Timeline</h3></div><span className="timeline-count">{activities.length}</span></div>{activities.length ? <div className="timeline-list">{activities.map((activity) => <div className="timeline-item" key={activity.id}><span className="timeline-dot" /><div><strong>{activity.type.replaceAll('_', ' ')}</strong><p>{activity.body}</p><time>{relativeDate(activity.occurred_at)}</time></div></div>)}</div> : <p className="timeline-empty">No activity yet. Log a call or note to start the story.</p>}</div>
  </aside></>
}

function AICopilotPreview({ lead }: { lead: Lead }) {
  return <section className="detail-section ai-copilot-section" aria-labelledby="ai-copilot-title">
    <div className="ai-copilot-heading">
      <div><p className="eyebrow">AI tools</p><h3 id="ai-copilot-title">Lead assistance</h3></div>
      <span className="ai-preview-badge">Preview</span>
    </div>
    <p className="ai-preview-note">These controls are a UI preview. AI inference will be connected in a later phase.</p>
    <article className="ai-score-card">
      <div className="ai-score-gauge" aria-label="No lead score yet">—</div>
      <div className="ai-score-copy"><strong>Lead score</strong><span>No score yet</span><small>A priority score and explanation will appear here.</small></div>
      <button className="button button-secondary ai-disabled-action" type="button" disabled title="AI inference will be connected later">Score</button>
    </article>
    <details className="ai-feature-card">
      <summary><span><strong>Draft a follow-up</strong><small>Personalized WhatsApp or email message</small></span><span className="ai-feature-state">Later</span></summary>
      <div className="ai-feature-content">
        <div className="ai-control-row">
          <label>Channel<select disabled defaultValue="whatsapp"><option value="whatsapp">WhatsApp</option><option value="email">Email</option></select></label>
          <label>Tone<select disabled defaultValue="friendly"><option value="professional">Professional</option><option value="friendly">Friendly</option><option value="concise">Concise</option><option value="warm">Warm</option></select></label>
        </div>
        <textarea disabled rows={3} placeholder="An editable message draft will appear here." aria-label="Message draft preview" />
        <button className="button button-secondary ai-disabled-action" type="button" disabled>Generate draft</button>
      </div>
    </details>
    <details className="ai-feature-card">
      <summary><span><strong>Turn notes into CRM data</strong><small>Extract preferences and a suggested follow-up</small></span><span className="ai-feature-state">Later</span></summary>
      <div className="ai-feature-content">
        <label className="ai-note-label">Lead notes<textarea readOnly rows={3} value={lead.notes ?? ''} placeholder="Add a note to this lead first." /></label>
        <div className="ai-extraction-preview"><span>Budget <strong>Not extracted</strong></span><span>Bedrooms <strong>Not extracted</strong></span><span>Location <strong>Not extracted</strong></span><span>Next follow-up <strong>Not extracted</strong></span></div>
        <button className="button button-secondary ai-disabled-action" type="button" disabled>Extract details</button>
      </div>
    </details>
  </section>
}

function CreateLeadModal({ token, currentUser, onClose, onCreated, onError, onConfirmAction }: { token: string; currentUser: User; onClose: () => void; onCreated: (lead: Lead) => void | Promise<void>; onError: (message: string) => void; onConfirmAction: (request: ConfirmationRequest) => void }) {
  const [form, setForm] = useState({
    full_name: '',
    email: '',
    phone: '',
    source: 'manual' as LeadSource,
    status: 'new' as LeadStatus,
    budget_min_inr: '',
    budget_max_inr: '',
    bhk: '',
    notes: '',
  })
  const [phoneRegion, setPhoneRegion] = useState('IN')
  const [location, setLocation] = useState<LocationSelection | null>(null)
  const [locationHasUnverifiedText, setLocationHasUnverifiedText] = useState(false)
  const [assignees, setAssignees] = useState<LeadAssignee[]>([])
  const [assignedTo, setAssignedTo] = useState(currentUser.role === 'manager' ? '' : currentUser.id)
  const [nameError, setNameError] = useState('')
  const [emailError, setEmailError] = useState('')
  const [phoneError, setPhoneError] = useState('')
  const [formError, setFormError] = useState('')
  const [duplicateCount, setDuplicateCount] = useState(0)
  const [pendingPayload, setPendingPayload] = useState<LeadCreateRequest | null>(null)
  const [saving, setSaving] = useState(false)
  const canAssign = currentUser.is_superuser || ['owner', 'co_owner', 'manager'].includes(currentUser.role)

  useEffect(() => {
    if (!canAssign) return
    let active = true
    api<LeadAssignee[]>('/leads/assignees', token)
      .then((items) => {
        if (active) setAssignees(items)
      })
      .catch((requestError: unknown) => {
        if (active) setFormError(getErrorMessage(requestError))
      })
    return () => {
      active = false
    }
  }, [canAssign, token])

  const update = (key: keyof typeof form, value: string) => {
    setForm((current) => ({ ...current, [key]: value }))
    if (key === 'full_name') setNameError('')
    if (key === 'email') setEmailError('')
  }

  const saveLead = async (payload: LeadCreateRequest, allowDuplicate: boolean) => {
    setSaving(true)
    setFormError('')
    try {
      const lead = await api<Lead>('/leads', token, {
        method: 'POST',
        body: JSON.stringify({ ...payload, allow_duplicate: allowDuplicate }),
      })
      setDuplicateCount(0)
      await onCreated(lead)
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 409 && !allowDuplicate) {
        try {
          const query = new URLSearchParams({ full_name: payload.full_name })
          const duplicateCheck = await api<LeadDuplicateCheck>(`/leads/duplicates?${query}`, token)
          setPendingPayload(payload)
          setDuplicateCount(Math.max(duplicateCheck.duplicate_count, 1))
          return
        } catch (duplicateError) {
          const message = getErrorMessage(duplicateError)
          setFormError(message)
          onError(message)
          throw new Error(message)
        }
      }
      const message = getErrorMessage(requestError)
      setFormError(message)
      onError(message)
      throw new Error(message)
    } finally {
      setSaving(false)
    }
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onError('')
    setFormError('')
    const normalizedName = normalizeName(form.full_name)
    const nextNameError = validateName(normalizedName)
    const normalizedEmail = normalizeEmail(form.email)
    const nextEmailError = normalizedEmail ? validateEmail(normalizedEmail) : ''
    setNameError(nextNameError)
    setEmailError(nextEmailError)
    if (nextNameError || nextEmailError) return
    if (locationHasUnverifiedText) {
      setFormError('Choose a verified location from the suggestions or clear the location field.')
      return
    }

    let phone
    try {
      phone = normalizePhone(form.phone, phoneRegion)
      setPhoneError('')
    } catch (validationError) {
      const message = validationError instanceof Error ? validationError.message : 'Enter a valid phone number.'
      setPhoneError(message)
      return
    }
    if (
      form.budget_min_inr
      && form.budget_max_inr
      && Number(form.budget_min_inr) > Number(form.budget_max_inr)
    ) {
      setFormError('Minimum budget must not exceed maximum budget.')
      return
    }

    const payload: LeadCreateRequest = {
      full_name: normalizedName,
      email: normalizedEmail || null,
      phone: phone?.phone ?? null,
      phone_country_code: phone?.phone_country_code ?? null,
      phone_region: phone?.phone_region ?? null,
      phone_national_number: phone?.phone_national_number ?? null,
      source: form.source,
      status: form.status,
      budget_min_inr: form.budget_min_inr ? Number(form.budget_min_inr) : null,
      budget_max_inr: form.budget_max_inr ? Number(form.budget_max_inr) : null,
      bhk: form.bhk ? Number(form.bhk) : null,
      preferred_location: location?.display_name ?? null,
      location,
      notes: form.notes.trim() || null,
      ...(assignedTo ? { assigned_to: assignedTo } : {}),
    }

    setSaving(true)
    try {
      const query = new URLSearchParams({ full_name: payload.full_name })
      const duplicateCheck = await api<LeadDuplicateCheck>(`/leads/duplicates?${query}`, token)
      if (duplicateCheck.duplicate_count) {
        setPendingPayload(payload)
        setDuplicateCount(duplicateCheck.duplicate_count)
        return
      }
    } catch (requestError) {
      const message = getErrorMessage(requestError)
      setFormError(message)
      onError(message)
      return
    } finally {
      setSaving(false)
    }

    onConfirmAction({
      title: `Add ${payload.full_name} as a lead?`,
      message: `This creates a new lead in the ${stageFor(payload.status).label.toLowerCase()} stage${payload.email ? ` with email ${payload.email}` : ''}.`,
      confirmLabel: 'Save lead',
      onConfirm: () => saveLead(payload, false),
    })
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-lead-title">
        <div className="modal-header">
          <div><span className="eyebrow">A NEW RELATIONSHIP</span><h2 id="create-lead-title">Add a lead<span className="heading-period">.</span></h2></div>
          <button className="icon-button" aria-label="Close" onClick={onClose}><X size={19} /></button>
        </div>
        <form className="lead-form" onSubmit={(event) => void submit(event)}>
          <label className="form-span">Full name
            <input autoFocus value={form.full_name} onChange={(event) => update('full_name', event.target.value)} onBlur={() => { const name = normalizeName(form.full_name); setForm((current) => ({ ...current, full_name: name })); setNameError(validateName(name)) }} placeholder="e.g. Aanya Mehta" maxLength={160} required aria-invalid={Boolean(nameError)} aria-describedby={nameError ? 'lead-name-error' : undefined} />
            {nameError && <small className="inline-form-error" id="lead-name-error">{nameError}</small>}
          </label>
          <label>Email address
            <input type="email" value={form.email} onChange={(event) => update('email', event.target.value)} onBlur={() => { const email = normalizeEmail(form.email); setForm((current) => ({ ...current, email })); setEmailError(email ? validateEmail(email) : '') }} placeholder="aanya@example.com" maxLength={320} aria-invalid={Boolean(emailError)} aria-describedby={emailError ? 'lead-email-error' : undefined} />
            {emailError && <small className="inline-form-error" id="lead-email-error">{emailError}</small>}
          </label>
          <PhoneNumberInput label="Phone number" value={form.phone} region={phoneRegion} onChange={(value) => { update('phone', value); setPhoneError('') }} onRegionChange={setPhoneRegion} error={phoneError} />
          <LocationAutocomplete value={location} onChange={(selected, unverified) => { setLocation(selected); setLocationHasUnverifiedText(unverified); setFormError('') }} />
          <label>Lead source<select value={form.source} onChange={(event) => update('source', event.target.value)}>{Object.entries(sourceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>Pipeline stage<select value={form.status} onChange={(event) => update('status', event.target.value as LeadStatus)}>{stages.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select></label>
          {(currentUser.is_superuser || ['owner', 'co_owner', 'manager'].includes(currentUser.role)) && (
            <label>Assign to
              <select value={assignedTo} onChange={(event) => setAssignedTo(event.target.value)}>
                {currentUser.role === 'manager' && <option value="">Me (default)</option>}
                {assignees.map((assignee) => <option key={assignee.id} value={assignee.id}>{assignee.full_name} · {assignee.role.replace('_', ' ')}</option>)}
              </select>
            </label>
          )}
          <label>BHK<input type="number" min="1" max="20" value={form.bhk} onChange={(event) => update('bhk', event.target.value)} placeholder="2" /></label>
          <label>Budget from (₹)<input type="number" min="0" value={form.budget_min_inr} onChange={(event) => update('budget_min_inr', event.target.value)} placeholder="6000000" /></label>
          <label>Budget up to (₹)<input type="number" min="0" value={form.budget_max_inr} onChange={(event) => update('budget_max_inr', event.target.value)} placeholder="9000000" /></label>
          <label className="form-span">Notes<textarea value={form.notes} onChange={(event) => update('notes', event.target.value)} placeholder="What would be helpful to remember?" rows={3} /></label>
          {duplicateCount > 0 && pendingPayload && (
            <div className="duplicate-lead-prompt form-span" role="alert">
              <p>{duplicateCount === 1 ? 'A lead with this name already exists.' : `${duplicateCount} leads with this name already exist.`} Do you want to create a separate one?</p>
              <div>
                <button type="button" className="button button-secondary" onClick={() => { setDuplicateCount(0); setPendingPayload(null) }}>Cancel</button>
                <button type="button" className="button button-primary" disabled={saving} onClick={() => void saveLead(pendingPayload, true)}>{saving ? 'Saving…' : 'Create separate lead'}</button>
              </div>
            </div>
          )}
          {formError && <p className="inline-form-error form-span" role="alert">{formError}</p>}
          <div className="form-span form-footer">
            <span className="form-hint">Keep contact details accurate and use fictional data for demos.</span>
            <div><button type="button" className="button button-secondary" onClick={onClose}>Cancel</button><button className="button button-primary" disabled={saving}>{saving ? 'Checking…' : 'Save lead'}<ArrowUpRight size={16} /></button></div>
          </div>
        </form>
      </section>
    </div>
  )
}

function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return <div className="empty-state"><strong>{title}</strong><p>{description}</p>{action}</div>
}

function StatusPill({ status }: { status: LeadStatus }) {
  const stage = stageFor(status)
  return <span className={`status-pill pill-${stage.tone}`}><i />{stage.label}</span>
}

function avatarColor(name: string) {
  const colors = ['peach', 'blue', 'green', 'lavender', 'yellow']
  return colors[name.charCodeAt(0) % colors.length]
}

export default App
