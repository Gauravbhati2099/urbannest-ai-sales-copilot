import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type FormEvent } from 'react'
import {
  Activity as ActivityIcon,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  CalendarDays,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  LayoutDashboard,
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
  SlidersHorizontal,
  Sparkles,
  Sun,
  Upload,
  UserPlus,
  Users,
  UserRound,
  X,
} from 'lucide-react'
import {
  api,
  downloadAllPasswordResetCsv,
  type Activity,
  type AuditEvent,
  type Dashboard,
  type CSVImportResult,
  type Lead,
  type LeadSource,
  type LeadStatus,
  type LoginResponse,
  type PasswordResetResponse,
  type Task,
  type User,
  type UserCreateRequest,
  type UserCreatedResponse,
  type ProfileUpdateRequest,
  type UserRole,
  type UserUpdateRequest,
} from './api'
import { initialWorkspaceState, workspaceReducer } from './workspace-state'
import './App.css'

type Page = 'overview' | 'leads' | 'tasks' | 'activity' | 'team' | 'profile'
type Theme = 'light' | 'dark'

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

function taskIsOverdue(dueAt: string, now: number) {
  return new Date(dueAt).getTime() < now
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('urbannest_token') ?? '')
  const [renderTime] = useState(() => new Date())
  const [theme, setTheme] = useState<Theme>(() => localStorage.getItem('urbannest_theme') === 'dark' ? 'dark' : 'light')
  const leadSearchRef = useRef<HTMLInputElement>(null)
  const refreshControllerRef = useRef<AbortController | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [authReady, setAuthReady] = useState(() => !sessionStorage.getItem('urbannest_token'))
  const [page, setPage] = useState<Page>('overview')
  const [workspace, dispatch] = useReducer(workspaceReducer, initialWorkspaceState)
  const { dashboard, leads, tasks, completedTasks, teamUsers, auditEvents, unreadCount, loading, error, apiConnected, importErrors } = workspace
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('urbannest_sidebar_collapsed') === 'true')
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [taskFilter, setTaskFilter] = useState<'all' | 'today' | 'overdue' | 'completed'>('all')
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null)
  const [showCreateLead, setShowCreateLead] = useState(false)
  const [showNotifications, setShowNotifications] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [confirmation, setConfirmation] = useState<ConfirmationRequest | null>(null)
  const [notice, setNotice] = useState('')
  const [temporaryPassword, setTemporaryPassword] = useState<{ email: string; password: string } | null>(null)
  const setError = useCallback((message: string) => {
    dispatch(message ? { type: 'error-set', error: message } : { type: 'error-cleared' })
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    localStorage.setItem('urbannest_theme', theme)
  }, [theme])

  useEffect(() => {
    localStorage.setItem('urbannest_sidebar_collapsed', String(sidebarCollapsed))
  }, [sidebarCollapsed])

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
  }, [])

  const signOut = useCallback(() => {
    sessionStorage.removeItem('urbannest_token')
    setToken('')
    setUser(null)
    setTemporaryPassword(null)
    setAuthReady(true)
    refreshControllerRef.current?.abort()
    dispatch({ type: 'session-cleared' })
    setPage('overview')
  }, [])

  useEffect(() => {
    if (!token) {
      return
    }
    let active = true
    api<User>('/auth/me', token)
      .then((currentUser) => {
        if (active) setUser(currentUser)
      })
      .catch(() => {
        if (active) signOut()
      })
      .finally(() => {
        if (active) setAuthReady(true)
      })
    return () => {
      active = false
    }
  }, [signOut, token])

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
  const activePage = !canReadWorkspace && page !== 'team' && page !== 'profile'
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
        const users = canManageTeam
          ? await api<User[]>('/users?limit=100', token, { signal: controller.signal })
          : []
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
      const [summary, leadRows, taskRows, completedTaskRows, feed, users] = await Promise.all([
        api<Dashboard>('/dashboard/summary', token, requestOptions),
        api<Lead[]>(`/leads?${params.toString()}`, token, requestOptions),
        api<Task[]>('/tasks?limit=100', token, requestOptions),
        api<Task[]>('/tasks?status=completed&limit=100', token, requestOptions),
        api<{ events: AuditEvent[]; unread_count: number }>('/audit/events?limit=8', token, requestOptions),
        usersRequest,
      ])
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
      dispatch({ type: 'refresh-failed', error: getErrorMessage(requestError) })
    } finally {
      if (refreshControllerRef.current === controller) refreshControllerRef.current = null
    }
  }, [canManageTeam, canReadWorkspace, debouncedQuery, statusFilter, token])

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
    profile: 'My profile',
  }[activePage]

  const visibleTasks = useMemo(() => {
    if (taskFilter === 'completed') return completedTasks
    if (taskFilter === 'today') return dashboard?.due_today ?? []
    if (taskFilter === 'overdue') return dashboard?.overdue ?? []
    return tasks
  }, [completedTasks, dashboard, taskFilter, tasks])

  const updateLeadStatus = async (lead: Lead, status: LeadStatus) => {
    try {
      await api<Lead>(`/leads/${lead.id}`, token, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      })
      setNotice(`${lead.full_name} moved to ${stageFor(status).label.toLowerCase()}.`)
      await refresh()
      if (selectedLead?.id === lead.id) setSelectedLead({ ...lead, status })
    } catch (requestError) {
      dispatch({ type: 'request-failed', error: getErrorMessage(requestError) })
    }
  }

  const completeTask = async (task: Pick<Task, 'id'>) => {
    try {
      await api<Task>(`/tasks/${task.id}`, token, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'completed' }),
      })
      setNotice('Follow-up marked complete.')
      dispatch({ type: 'request-succeeded' })
      await refresh()
    } catch (requestError) {
      dispatch({ type: 'request-failed', error: getErrorMessage(requestError) })
    }
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
      setError(getErrorMessage(requestError))
    }
  }

  const markRead = async () => {
    try {
      await api('/audit/read', token, { method: 'POST' })
      dispatch({ type: 'read-marked' })
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    }
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

  if (!authReady) {
    return <div className="boot-screen"><span className="brand-mark">U</span><span className="spinner" /></div>
  }

  if (!token || !user) {
    return <LoginScreen onLogin={handleLogin} error={error} setError={setError} theme={theme} onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')} />
  }

  if (user.must_change_password) {
    return <PasswordScreen token={token} onComplete={setSession} onSignOut={signOut} theme={theme} onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')} />
  }

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'app-shell-collapsed' : ''}`}>
      {mobileNavOpen && <button className="mobile-backdrop" aria-label="Close menu" onClick={() => setMobileNavOpen(false)} />}
      <aside className={`sidebar ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${mobileNavOpen ? 'sidebar-open' : ''}`}>
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setPage('overview') }}>
          <span className="brand-mark">U</span>
          <span className="brand-copy"><strong>urbannest</strong><small>REALTY CRM</small></span>
        </a>
        <button className="sidebar-toggle icon-button" aria-label={sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'} title={sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'} onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}>
          {sidebarCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
        </button>

        <div className="nav-caption">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Main navigation">
          {canReadWorkspace && <>
            <NavButton label="Overview" icon={<LayoutDashboard size={18} />} active={activePage === 'overview'} onClick={() => { setPage('overview'); setMobileNavOpen(false) }}>Overview</NavButton>
            <NavButton label="Leads" icon={<Users size={18} />} active={activePage === 'leads'} onClick={() => { setPage('leads'); setMobileNavOpen(false) }}>Leads<span className="nav-count">{dashboard?.total_leads ?? '—'}</span></NavButton>
            <NavButton label="Follow-ups" icon={<CalendarDays size={18} />} active={activePage === 'tasks'} onClick={() => { setPage('tasks'); setMobileNavOpen(false) }}>Follow-ups</NavButton>
            <NavButton label="Activity" icon={<ActivityIcon size={18} />} active={activePage === 'activity'} onClick={() => { setPage('activity'); setMobileNavOpen(false) }}>Activity{unreadCount > 0 && <span className="nav-count">{unreadCount > 9 ? '9+' : unreadCount}</span>}</NavButton>
          </>}
          {canManageTeam && <NavButton label="Team" icon={<UserRound size={18} />} active={activePage === 'team'} onClick={() => { setPage('team'); setMobileNavOpen(false) }}>Team</NavButton>}
        </nav>

        <div className="sidebar-bottom">
          <button className={`user-profile ${activePage === 'profile' ? 'user-profile-active' : ''}`} onClick={() => { setPage('profile'); setMobileNavOpen(false) }} title="Open your profile">
            <span className="avatar avatar-user">{initials(user.full_name)}</span>
            <span className="user-meta"><strong>{user.full_name}</strong><span>{user.role}</span></span>
            <UserRound className="profile-indicator" size={16} />
          </button>
          <button className="sign-out-button" onClick={() => setConfirmation({
            title: 'Sign out?',
            message: 'You’ll need to sign in again to continue working in UrbanNest Realty.',
            confirmLabel: 'Sign out',
            onConfirm: signOut,
          })}><LogOut size={16} /><span>Sign out</span></button>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Open menu" onClick={() => setMobileNavOpen(true)}><Menu size={20} /></button>
          <div className="topbar-actions">
            <div className={`api-indicator ${apiConnected ? '' : 'api-offline'}`}><span className="status-light" /> {apiConnected ? 'API connected' : 'API not checked'}</div>
            <ThemeButton theme={theme} onToggle={() => setTheme(theme === 'dark' ? 'light' : 'dark')} />
            {canReadWorkspace && <button className="icon-button notification-button" aria-label="Notifications" onClick={() => setShowNotifications((show) => !show)}>
              <Bell size={19} />{unreadCount > 0 && <span className="notification-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>}
            </button>}
          </div>
        </header>

        <div className="page-content">
          {(error || notice) && (
            <div className={`toast ${error ? 'toast-error' : 'toast-success'}`} role="status">
              {error ? <CircleAlert size={17} /> : <Check size={17} />}
              <span>{error || notice}</span>
              <button className="icon-button toast-close" aria-label="Dismiss message" onClick={() => { setError(''); setNotice('') }}><X size={16} /></button>
            </div>
          )}

          <div className="page-heading">
            <div>
              <p className="eyebrow">{formatDate(renderTime.toISOString(), { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p>
              <h1>{activePage === 'overview' ? `Good ${renderTime.getHours() < 12 ? 'morning' : renderTime.getHours() < 17 ? 'afternoon' : 'evening'}, ${user.full_name.split(' ')[0]}` : pageTitle}<span className="heading-period">.</span></h1>
              <p className="heading-subtitle">{activePage === 'overview' ? 'Here’s what’s happening with your sales today.' : activePage === 'leads' ? 'Keep every conversation moving forward.' : activePage === 'tasks' ? 'A thoughtful follow-up can make all the difference.' : activePage === 'activity' ? 'A shared view of what’s changing across your team.' : activePage === 'team' ? 'Manage team access and account setup.' : 'Your account details and sign-in security.'}</p>
            </div>
            <div className="heading-actions">
              <button className="button button-secondary refresh-button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={16} className={loading ? 'spinning' : ''} /><span>Refresh</span></button>
              {canReadWorkspace && canWriteWorkspace && (activePage === 'overview' || activePage === 'leads') && <button className="button button-primary" onClick={() => setShowCreateLead(true)}><Plus size={17} /> Add lead</button>}
            </div>
          </div>

          {loading && !dashboard && canReadWorkspace ? <LoadingState /> : (
            <>
              {!canReadWorkspace && activePage !== 'team' && activePage !== 'profile' && (
                <EmptyState title="Workspace access is disabled" description="Your current role does not have permission to read CRM records." />
              )}
              {canReadWorkspace && activePage === 'overview' && (
                <OverviewPage dashboard={dashboard} leads={leads} events={auditEvents} users={teamUsers} currentUser={user} now={renderTime.getTime()} onOpenLead={setSelectedLead} onOpenLeadById={openLeadById} onOpenTasks={() => setPage('tasks')} onSeeAllActivity={() => setPage('activity')} onCompleteTask={completeTask} onOpenLeads={() => setPage('leads')} onOpenEvent={(event) => void openAuditEvent(event)} canWrite={canWriteWorkspace} />
              )}
              {canReadWorkspace && activePage === 'leads' && (
                <LeadsPage leads={leads} query={query} setQuery={setQuery} searchRef={leadSearchRef} statusFilter={statusFilter} setStatusFilter={setStatusFilter} onOpenLead={setSelectedLead} onUpdateStatus={updateLeadStatus} onAddLead={() => setShowCreateLead(true)} onImportFile={importCsv} importErrors={importErrors} onDismissImportErrors={() => dispatch({ type: 'import-errors-cleared' })} canImport={canWriteWorkspace && user.role !== 'agent'} canWrite={canWriteWorkspace} loading={loading} />
              )}
              {canReadWorkspace && activePage === 'tasks' && (
                <TasksPage tasks={visibleTasks} filter={taskFilter} setFilter={setTaskFilter} users={teamUsers} currentUser={user} now={renderTime.getTime()} onComplete={completeTask} onOpenLead={openLeadById} canWrite={canWriteWorkspace} />
              )}
              {canReadWorkspace && activePage === 'activity' && <ActivityPage events={auditEvents} unreadCount={unreadCount} onMarkRead={markRead} onOpenEvent={(event) => void openAuditEvent(event)} />}
              {activePage === 'team' && canManageTeam && <TeamPage currentUser={user} users={teamUsers} temporaryPassword={temporaryPassword} onClearTemporaryPassword={() => setTemporaryPassword(null)} onCreate={createTeamUser} onUpdate={updateTeamUser} onResetPassword={resetTeamUserPassword} onError={setError} onConfirmAction={setConfirmation} onResetAll={resetAllUserPasswords} />}
              {activePage === 'profile' && <ProfilePage user={user} onChangePassword={changeOwnPassword} onSaveProfile={updateOwnProfile} onConfirmAction={setConfirmation} />}
            </>
          )}
        </div>
      </main>

      {showNotifications && canReadWorkspace && <NotificationPanel events={auditEvents.slice(0, 5)} unreadCount={unreadCount} onClose={() => setShowNotifications(false)} onOpenEvent={(event) => void openAuditEvent(event)} onOpenActivity={() => { setPage('activity'); setShowNotifications(false) }} />}
      {confirmation && <ConfirmationDialog request={confirmation} onCancel={() => setConfirmation(null)} onConfirmed={() => setConfirmation(null)} />}
      {selectedLead && canReadWorkspace && <LeadDrawer lead={selectedLead} token={token} onClose={() => setSelectedLead(null)} onUpdated={(updated) => { setSelectedLead(updated); void refresh() }} onError={setError} canWrite={canWriteWorkspace} />}
      {showCreateLead && canWriteWorkspace && <CreateLeadModal token={token} currentUser={user} onClose={() => setShowCreateLead(false)} onCreated={async (lead) => { setShowCreateLead(false); setNotice(`Added ${lead.full_name} to your leads.`); setPage('leads'); await refresh(); setSelectedLead(lead) }} onError={setError} />}
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
  return <div className="loading-state"><span className="spinner" /><p>Getting your workspace ready…</p></div>
}

function LoginScreen({ onLogin, error, setError, theme, onToggleTheme }: { onLogin: (response: LoginResponse) => void; error: string; setError: (message: string) => void; theme: Theme; onToggleTheme: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const response = await api<LoginResponse>('/auth/login', '', { method: 'POST', body: JSON.stringify({ email, password }) })
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
        <a className="brand brand-light" href="#"><span className="brand-mark">U</span><span className="brand-copy"><strong>urbannest</strong><small>REALTY CRM</small></span></a>
        <div className="art-copy">
          <span className="art-kicker"><span /> YOUR NEXT MOVE, MADE CLEAR</span>
          <h1>Every lead<br />has a <em>home.</em></h1>
          <p>One calm place to build better client relationships and close with confidence.</p>
        </div>
        <div className="art-building"><div className="building-sun" /><div className="building-tower tower-one"><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /></div><div className="building-tower tower-two"><i /><i /><i /><i /><i /><i /><i /><i /></div><div className="building-house"><i /><i /><i /><i /></div><div className="building-ground" /></div>
        <p className="art-footnote">MADE FOR THE WAY REAL ESTATE REALLY WORKS.</p>
      </div>
      <div className="auth-main">
        <ThemeButton theme={theme} onToggle={onToggleTheme} className="auth-theme-toggle" />
        <div className="auth-form-wrap">
          <span className="auth-overline">WELCOME BACK</span>
          <h2>Sign in to your<br />workspace<span className="heading-period">.</span></h2>
          <p className="auth-description">Good to see you again. Let’s pick up where you left off.</p>
          <form className="auth-form" onSubmit={(event) => void submit(event)}>
            <label>Email address<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@urbannest.in" required /></label>
            <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" required /></label>
            {error && <div className="form-error"><CircleAlert size={16} />{error}</div>}
            <button className="button button-primary auth-submit" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}<ArrowUpRight size={17} /></button>
          </form>
          <div className="auth-note"><span className="secure-dot" /> Your workspace is private and secure.</div>
        </div>
        <div className="auth-footer"><span>© {CURRENT_YEAR} UrbanNest Realty</span><span>Questions? Ask your team owner.</span></div>
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

  return <div className="password-page"><div className="password-card"><div className="password-card-head"><span className="brand-mark">U</span><ThemeButton theme={theme} onToggle={onToggleTheme} /></div><span className="auth-overline">ONE QUICK STEP</span><h1>Make it your own<span className="heading-period">.</span></h1><p>Your account has a temporary password. Create a new one to continue.</p><form className="auth-form" onSubmit={submit}><label>Temporary password<input type="password" value={current} onChange={(event) => setCurrent(event.target.value)} required /></label><label>New password<input type="password" minLength={12} value={next} onChange={(event) => setNext(event.target.value)} required /><small className="field-hint">Use at least 12 characters.</small></label><label>Confirm new password<input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} required /></label>{error && <div className="form-error"><CircleAlert size={16} />{error}</div>}<button className="button button-primary auth-submit">Review password change<ArrowUpRight size={17} /></button></form><button className="text-button signout-link" onClick={() => setShowSignOutConfirmation(true)}>Sign out instead</button></div>{showSignOutConfirmation && <ConfirmationDialog request={{ title: 'Sign out?', message: 'You’ll need to sign in again to continue setting up your account.', confirmLabel: 'Sign out', onConfirm: onSignOut }} onCancel={() => setShowSignOutConfirmation(false)} onConfirmed={() => setShowSignOutConfirmation(false)} />}{showPasswordConfirmation && <ConfirmationDialog request={{ title: 'Set your new password?', message: 'This replaces your temporary password. Your existing session will be renewed with the new credential.', confirmLabel: 'Save new password', onConfirm: changePassword }} onCancel={() => setShowPasswordConfirmation(false)} onConfirmed={() => setShowPasswordConfirmation(false)} />}</div>
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
  onCompleteTask: (task: Pick<Task, 'id'>) => void; onOpenLeads: () => void
  onOpenEvent: (event: AuditEvent) => void
  canWrite: boolean
}) {
  const pipelineData = stages.map((stage) => ({ ...stage, count: dashboard?.pipeline_counts[stage.value] ?? 0 }))
  const pipelineTotal = pipelineData.reduce((total, item) => total + item.count, 0)
  const chartColors: Record<LeadStatus, string> = {
    new: '#93a2a4',
    contacted: '#6a9dc1',
    site_visit: '#8e83bc',
    negotiation: '#d3a457',
    won: '#68a17c',
    lost: '#cb8379',
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
        <StatCard label="Total leads" value={dashboard?.total_leads ?? '—'} icon={<Users size={18} />} hint="Across your workspace" tone="blue" trend="All time" />
        <StatCard label="Open follow-ups" value={dashboard?.open_tasks ?? '—'} icon={<CalendarDays size={18} />} hint="Keep the momentum" tone="violet" trend={`${dashboard?.due_today_count ?? 0} due today`} />
        <StatCard label="Due today" value={dashboard?.due_today_count ?? '—'} icon={<Clock3 size={18} />} hint="A good day to reconnect" tone="amber" trend="Today's focus" />
        <StatCard label="Overdue" value={dashboard?.overdue_count ?? '—'} icon={<CircleAlert size={18} />} hint="Bring these back on track" tone="rose" trend={dashboard?.overdue_count ? 'Needs attention' : 'All caught up'} />
      </section>

      <section className="panel pipeline-panel">
        <div className="panel-header"><div><p className="eyebrow">YOUR SALES JOURNEY</p><h2>Pipeline at a glance</h2></div><button className="text-button" onClick={onOpenLeads}>View leads <ArrowUpRight size={15} /></button></div>
        <div className="pipeline-summary"><strong>{dashboard?.total_leads ?? '—'}</strong><span>leads in your pipeline</span><span className="pipeline-legend"><i /> Active</span></div>
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
        <div className="pipeline-footer"><span>Progress, not just numbers.</span><span className="pipeline-footer-icon"><ArrowUpRight size={15} /></span></div>
      </section>

      <section className="panel followup-panel">
        <div className="panel-header"><div><p className="eyebrow">DON’T LET A GOOD LEAD GO COLD</p><h2>Follow-ups to focus on</h2></div><button className="icon-button subtle-icon" aria-label="View all follow-ups" onClick={onOpenTasks}><ArrowUpRight size={17} /></button></div>
        <div className="followup-tabs"><span className="followup-tab active">Priority <b>{dueTasks.length}</b></span><button className="followup-tab" onClick={onOpenTasks}>All tasks <ChevronRight size={13} /></button></div>
        {dueTasks.length ? <div className="followup-list">{dueTasks.map((task) => {
          const lead = leads.find((item) => item.id === task.lead_id)
          return <div className="followup-item" key={task.id}>
            {canWrite && <button className="task-check" title="Mark complete" onClick={() => onCompleteTask(task)}><Check size={13} /></button>}
              <button className="followup-copy" onClick={() => lead ? onOpenLead(lead) : onOpenLeadById(task.lead_id)}><strong>{task.title}</strong><span>{task.lead_name}</span></button>
            <span className="task-assignee"><span className="avatar avatar-xs avatar-user">{initials(taskAssigneeName(task, users, currentUser))}</span>{taskAssigneeName(task, users, currentUser)}</span>
            <span className={`task-time ${taskIsOverdue(task.due_at, now) ? 'task-time-overdue' : ''}`}><Clock3 size={12} />{relativeDate(task.due_at)}</span>
          </div>
        })}</div> : <EmptyState title="You’re all caught up" description="No overdue or due-today follow-ups to show." />}
        <button className="panel-link" onClick={onOpenTasks}>Open your task list <ArrowUpRight size={14} /></button>
      </section>

      <section className="panel leads-panel">
        <div className="panel-header"><div><p className="eyebrow">FRESH OPPORTUNITIES</p><h2>Recently added leads</h2></div><button className="text-button" onClick={onOpenLeads}>All leads <ArrowUpRight size={15} /></button></div>
        {recentLeads.length ? <div className="table-scroll"><table className="data-table compact-table"><thead><tr><th>Lead</th><th>Interest</th><th>Stage</th><th>Added</th></tr></thead><tbody>{recentLeads.map((lead) => <tr key={lead.id} onClick={() => onOpenLead(lead)}><td><div className="lead-cell"><div className={`avatar avatar-${avatarColor(lead.full_name)}`}>{initials(lead.full_name)}</div><span><strong>{lead.full_name}</strong><small>{lead.preferred_location || sourceLabels[lead.source]}</small></span></div></td><td>{lead.bhk ? `${lead.bhk} BHK` : '—'}<small className="table-subline">{budgetRange(lead)}</small></td><td><StatusPill status={lead.status} /></td><td className="muted-cell">{formatDate(lead.created_at)}</td></tr>)}</tbody></table></div> : <EmptyState title="No leads just yet" description="Add your first lead and start building your pipeline." />}
      </section>

      <section className="panel activity-panel">
        <div className="panel-header"><div><p className="eyebrow">THE TEAM PULSE</p><h2>Recent activity</h2></div><button className="icon-button subtle-icon" aria-label="See all activity" onClick={onSeeAllActivity}><ArrowUpRight size={17} /></button></div>
        {events.length ? <ActivityList events={events.slice(0, 5)} onOpenEvent={onOpenEvent} /> : <EmptyState title="A fresh start" description="Team updates will appear here as work happens." />}
        <button className="panel-link" onClick={onSeeAllActivity}>View activity feed <ArrowUpRight size={14} /></button>
      </section>
    </div>
  )
}

function StatCard({ label, value, icon, hint, tone, trend }: { label: string; value: string | number; icon: React.ReactNode; hint: string; tone: string; trend: string }) {
  return <div className="stat-card"><div className={`stat-icon stat-${tone}`}>{icon}</div><span className="stat-label">{label}</span><strong className="stat-value">{value}</strong><span className="stat-hint">{hint}</span><span className={`stat-trend trend-${tone}`}>{tone === 'rose' ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />}{trend}</span></div>
}

function LeadsPage({ leads, query, setQuery, searchRef, statusFilter, setStatusFilter, onOpenLead, onUpdateStatus, onAddLead, onImportFile, importErrors, onDismissImportErrors, canImport, canWrite, loading }: {
  leads: Lead[]; query: string; setQuery: (value: string) => void; statusFilter: string
  searchRef: React.RefObject<HTMLInputElement | null>
  setStatusFilter: (value: string) => void; onOpenLead: (lead: Lead) => void
  onUpdateStatus: (lead: Lead, status: LeadStatus) => void; onAddLead: () => void
  onImportFile: (file: File) => void; importErrors: CSVImportResult['errors']
  onDismissImportErrors: () => void; canImport: boolean; canWrite: boolean; loading: boolean
}) {
  return <section className="panel full-panel leads-page-panel">
    <div className="list-toolbar"><div className="search-box"><Search size={17} /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search leads, locations…" aria-label="Search leads" /><kbd className="search-shortcut">/</kbd>{query && <button className="icon-button clear-search" aria-label="Clear search" onClick={() => setQuery('')}><X size={14} /></button>}</div><label className="select-wrap"><SlidersHorizontal size={15} /><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Filter by stage"><option value="">All stages</option>{stages.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select><ChevronDown size={14} /></label><span className="result-count">{leads.length} leads</span>{canImport && <label className="button button-secondary import-button"><Upload size={15} /> Import CSV<input type="file" accept=".csv,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) onImportFile(file); event.currentTarget.value = '' }} /></label>}</div>
    {importErrors.length > 0 && <div className="csv-errors"><div><strong>Some rows weren’t imported</strong><span>Review the row numbers and fix the source CSV before retrying.</span></div><button className="icon-button" aria-label="Dismiss import errors" onClick={onDismissImportErrors}><X size={16} /></button><ul>{importErrors.slice(0, 8).map((item) => <li key={`${item.row}-${item.message}`}><strong>Row {item.row}</strong>{item.message}</li>)}</ul>{importErrors.length > 8 && <small>And {importErrors.length - 8} more row errors.</small>}</div>}
    <div className="table-scroll"><table className="data-table leads-table"><thead><tr><th>Lead</th><th>Contact</th><th>Requirement</th><th>Source</th><th>Stage</th><th>Added</th><th aria-label="Open" /></tr></thead><tbody>{leads.map((lead) => <tr key={lead.id}><td><button className="lead-cell lead-cell-button" onClick={() => onOpenLead(lead)}><div className={`avatar avatar-${avatarColor(lead.full_name)}`}>{initials(lead.full_name)}</div><span><strong>{lead.full_name}</strong><small>{lead.preferred_location || 'Location not set'}</small></span></button></td><td><span>{lead.email || '—'}</span><small className="table-subline">{lead.phone || 'No phone'}</small></td><td><strong className="requirement-main">{lead.bhk ? `${lead.bhk} BHK` : 'Home search'}</strong><small className="table-subline">{budgetRange(lead)}</small></td><td><span className="source-label">{sourceLabels[lead.source]}</span></td><td><select className={`status-select status-${stageFor(lead.status).tone}`} aria-label={`Change ${lead.full_name} stage`} value={lead.status} disabled={!canWrite} onChange={(event) => void onUpdateStatus(lead, event.target.value as LeadStatus)}>{stages.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select></td><td className="muted-cell">{formatDate(lead.created_at)}</td><td><button className="icon-button row-open" aria-label={`Open ${lead.full_name}`} onClick={() => onOpenLead(lead)}><ChevronRight size={17} /></button></td></tr>)}</tbody></table></div>
    {!leads.length && !loading && <EmptyState title={query || statusFilter ? 'No matching leads' : 'No leads yet'} description={query || statusFilter ? 'Try another search or clear the stage filter.' : 'Your next great client relationship starts here.'} action={!query && !statusFilter && canWrite ? <button className="button button-primary" onClick={onAddLead}><Plus size={16} /> Add your first lead</button> : undefined} />}
    {loading && <div className="inline-loading"><span className="spinner" /> Updating your leads…</div>}
    <div className="table-footnote"><span>Showing the latest {leads.length} leads</span><span>Visibility is managed by your team role</span></div>
  </section>
}

function TasksPage({ tasks, filter, setFilter, users, currentUser, now, onComplete, onOpenLead, canWrite }: {
  tasks: (Task | Dashboard['due_today'][number])[]; filter: 'all' | 'today' | 'overdue' | 'completed'
  users: User[]; currentUser: User
  setFilter: (filter: 'all' | 'today' | 'overdue' | 'completed') => void; now: number
  onComplete: (task: Pick<Task, 'id'>) => void; onOpenLead: (leadId: string) => void
  canWrite: boolean
}) {
  const filters = [{ id: 'all', label: 'All open' }, { id: 'today', label: 'Due today' }, { id: 'overdue', label: 'Overdue' }, { id: 'completed', label: 'Completed' }] as const
  return <section className="panel full-panel task-page-panel">
    <div className="panel-header task-header"><div><p className="eyebrow">A LITTLE NUDGE GOES A LONG WAY</p><h2>{filter === 'completed' ? 'Completed follow-ups' : 'Your follow-up list'}</h2></div><div className="task-filter-pills">{filters.map((item) => <button key={item.id} className={`filter-pill ${filter === item.id ? 'filter-pill-active' : ''}`} onClick={() => setFilter(item.id)}>{item.label}</button>)}</div></div>
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
  return <section className="panel full-panel activity-page-panel"><div className="panel-header"><div><p className="eyebrow">SHARED WITH YOUR TEAM</p><h2>The activity feed</h2><p className="panel-subtitle">A clear view of the important changes happening across your workspace.</p></div>{unreadCount > 0 && <button className="button button-secondary" onClick={onMarkRead}><CheckCheck size={16} /> Mark as read</button>}</div>{events.length ? <ActivityList events={events} expanded onOpenEvent={onOpenEvent} /> : <EmptyState title="Nothing to report yet" description="Team changes and lead updates will show up here." />}<div className="activity-feed-note"><span className="secure-dot" /> This feed follows your team role and lead access.</div></section>
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
      <span className={`activity-avatar activity-${index % 4}`}>{event.actor_name ? initials(event.actor_name) : <Sparkles size={14} />}</span>
      <span className="activity-body">
        <span className="activity-summary"><strong>{event.actor_name || 'UrbanNest team'}</strong> {event.summary.toLowerCase()}</span>
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
  const [phone, setPhone] = useState(user.phone ?? '')
  const [formError, setFormError] = useState('')
  const [profileSaving, setProfileSaving] = useState(false)
  const [saving, setSaving] = useState(false)

  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setProfileSaving(true)
    const normalizedPhone = phone.trim()
    if (await onSaveProfile({ phone: normalizedPhone || null })) setPhone(normalizedPhone)
    setProfileSaving(false)
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
      <div><p className="eyebrow">YOUR ACCOUNT</p><h2>{user.full_name}</h2></div>
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
        <label>Phone number<input type="tel" autoComplete="tel" maxLength={32} value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="Add a phone number (optional)" /></label>
        <button className="button button-secondary" disabled={profileSaving || phone.trim() === (user.phone ?? '')}>{profileSaving ? 'Saving…' : 'Save phone number'}</button>
      </form>
    </article>
    <article className="panel password-panel">
      <div className="panel-header"><div><p className="eyebrow">SIGN-IN SECURITY</p><h2>Change your password</h2><p className="panel-subtitle">Use at least 12 characters. Your current session will be renewed securely.</p></div><KeyRound size={20} /></div>
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
    const newUser: UserCreateRequest = {
      full_name: fullName,
      email,
      role,
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
      <div><p className="eyebrow">TEAM ACCESS</p><h2>People in your workspace</h2><p className="panel-subtitle">{ownerAccess ? 'Create accounts, adjust access, and help teammates get back in.' : 'Manage agent access and reset passwords for your team.'}</p></div>
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
      <label>Full name<input value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="name" maxLength={160} required /></label>
      <label>Email address<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" maxLength={320} required /></label>
      <label>Role<select value={role} onChange={(event) => setRole(event.target.value as UserRole)}><option value="agent">Agent</option>{ownerAccess && <><option value="manager">Manager</option><option value="co_owner">Co-owner</option></>}</select></label>
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
          <button className="icon-button" aria-label={`Reset password for ${member.full_name}`} title="Reset password" onClick={() => onConfirmAction({
            title: `Reset ${member.full_name}'s password?`,
            message: 'Their existing password and sessions will stop working. A temporary password will be generated and shown once; share it privately. They must choose a new password at their next sign-in.',
            confirmLabel: 'Reset password',
            onConfirm: () => onResetPassword(member),
          })}><RotateCcw size={16} /></button>
        </div>}
      </article>)}
      {!users.length && <EmptyState title="No team members found" description="New accounts will appear here after they are created." />}
    </div>
    <p className="team-access-note">Access controls are enforced by the API. Managers and user-enabled co-owners manage agents; only owners can create managers or co-owners.</p>
  </section>
}

function LeadDrawer({ lead: initialLead, token, onClose, onUpdated, onError, canWrite }: { lead: Lead; token: string; onClose: () => void; onUpdated: (lead: Lead) => void; onError: (message: string) => void; canWrite: boolean }) {
  const [lead, setLead] = useState(initialLead)
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

  const changeStage = async (status: LeadStatus) => {
    try {
      const updated = await api<Lead>(`/leads/${lead.id}`, token, { method: 'PATCH', body: JSON.stringify({ status }) })
      setLead(updated)
      onUpdated(updated)
    } catch (requestError) {
      onError(getErrorMessage(requestError))
    }
  }

  const submitActivity = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    try {
      const activity = await api<Activity>(`/leads/${lead.id}/activities`, token, { method: 'POST', body: JSON.stringify({ type: activityType, body: activityText }) })
      setActivities((items) => [activity, ...items])
      setActivityText('')
      setActiveForm(null)
      onError('')
      onUpdated(lead)
    } catch (requestError) {
      onError(getErrorMessage(requestError))
    } finally {
      setSaving(false)
    }
  }

  const submitTask = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api<Task>('/tasks', token, { method: 'POST', body: JSON.stringify({ lead_id: lead.id, title: taskTitle, due_at: new Date(taskDate).toISOString() }) })
      setTaskTitle('')
      setActiveForm(null)
      onError('')
      onUpdated(lead)
    } catch (requestError) {
      onError(getErrorMessage(requestError))
    } finally {
      setSaving(false)
    }
  }

  return <><button className="drawer-backdrop" aria-label="Close lead details" onClick={onClose} /><aside className="lead-drawer"><div className="drawer-topbar"><span className="eyebrow">LEAD PROFILE</span><button className="icon-button" aria-label="Close lead details" onClick={onClose}><X size={19} /></button></div><div className="drawer-lead-head"><div className={`avatar avatar-large avatar-${avatarColor(lead.full_name)}`}>{initials(lead.full_name)}</div><div><h2>{lead.full_name}</h2><span className="drawer-subtitle">Added {formatDate(lead.created_at, { day: 'numeric', month: 'long', year: 'numeric' })}</span></div></div>
    <div className="drawer-stage"><label htmlFor="drawer-status">CURRENT STAGE</label><select id="drawer-status" className={`status-select status-${stageFor(lead.status).tone}`} value={lead.status} disabled={!canWrite} onChange={(event) => void changeStage(event.target.value as LeadStatus)}>{stages.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select></div>
    {canWrite && <div className="drawer-actions"><button className="button button-secondary" onClick={() => setActiveForm(activeForm === 'activity' ? null : 'activity')}><ActivityIcon size={15} /> Log activity</button><button className="button button-secondary" onClick={() => setActiveForm(activeForm === 'task' ? null : 'task')}><CalendarDays size={15} /> Add follow-up</button></div>}
    {canWrite && activeForm === 'activity' && <form className="drawer-form" onSubmit={(event) => void submitActivity(event)}><div className="drawer-form-heading"><strong>Log an interaction</strong><button type="button" className="icon-button" aria-label="Close form" onClick={() => setActiveForm(null)}><X size={15} /></button></div><select value={activityType} onChange={(event) => setActivityType(event.target.value as Activity['type'])}><option value="call">Call</option><option value="note">Note</option><option value="site_visit">Site visit</option><option value="email">Email</option><option value="whatsapp">WhatsApp</option></select><textarea value={activityText} onChange={(event) => setActivityText(event.target.value)} placeholder="What happened? Add a useful note…" rows={3} required /><button className="button button-primary" disabled={saving}>{saving ? 'Saving…' : 'Save activity'}</button></form>}
    {canWrite && activeForm === 'task' && <form className="drawer-form" onSubmit={(event) => void submitTask(event)}><div className="drawer-form-heading"><strong>Plan a follow-up</strong><button type="button" className="icon-button" aria-label="Close form" onClick={() => setActiveForm(null)}><X size={15} /></button></div><input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} placeholder="e.g. Call to confirm site visit" maxLength={200} required /><input type="datetime-local" value={taskDate} onChange={(event) => setTaskDate(event.target.value)} required /><button className="button button-primary" disabled={saving}>{saving ? 'Saving…' : 'Create follow-up'}</button></form>}
    <div className="detail-section"><p className="eyebrow">WHAT THEY’RE LOOKING FOR</p><div className="detail-cards"><div className="detail-card"><span>Budget</span><strong>{budgetRange(lead)}</strong></div><div className="detail-card"><span>Configuration</span><strong>{lead.bhk ? `${lead.bhk} BHK` : 'Not specified'}</strong></div></div><div className="detail-location"><MapPin size={16} /><span>{lead.preferred_location || 'Preferred location not specified'}</span></div></div>
    <div className="detail-section contact-section"><p className="eyebrow">CONTACT DETAILS</p>{lead.email && <a href={`mailto:${lead.email}`}><span className="contact-icon">@</span>{lead.email}<ArrowUpRight size={13} /></a>}{lead.phone && <a href={`tel:${lead.phone}`}><span className="contact-icon">#</span>{lead.phone}<ArrowUpRight size={13} /></a>}{!lead.email && !lead.phone && <span className="empty-contact">No contact details added.</span>}<div className="contact-source">Source <strong>{sourceLabels[lead.source]}</strong></div></div>
    <AICopilotPreview lead={lead} />
    <div className="detail-section timeline-section"><div className="timeline-head"><div><p className="eyebrow">THE STORY SO FAR</p><h3>Timeline</h3></div><span className="timeline-count">{activities.length}</span></div>{activities.length ? <div className="timeline-list">{activities.map((activity) => <div className="timeline-item" key={activity.id}><span className="timeline-dot" /><div><strong>{activity.type.replaceAll('_', ' ')}</strong><p>{activity.body}</p><time>{relativeDate(activity.occurred_at)}</time></div></div>)}</div> : <p className="timeline-empty">No activity yet. Log a call or note to start the story.</p>}</div>
  </aside></>
}

function AICopilotPreview({ lead }: { lead: Lead }) {
  return <section className="detail-section ai-copilot-section" aria-labelledby="ai-copilot-title">
    <div className="ai-copilot-heading">
      <div><p className="eyebrow">AI SALES COPILOT</p><h3 id="ai-copilot-title">AI tools</h3></div>
      <span className="ai-preview-badge"><Sparkles size={12} /> Preview</span>
    </div>
    <p className="ai-preview-note">These controls are a UI preview. AI inference will be connected in a later phase.</p>
    <article className="ai-score-card">
      <div className="ai-score-gauge" aria-label="No lead score yet">—</div>
      <div className="ai-score-copy"><strong>Lead score</strong><span>No score yet</span><small>A priority score and explanation will appear here.</small></div>
      <button className="button button-secondary ai-disabled-action" type="button" disabled title="AI inference will be connected later">Score</button>
    </article>
    <details className="ai-feature-card">
      <summary><Sparkles size={15} /><span><strong>Draft a follow-up</strong><small>Personalized WhatsApp or email message</small></span><span className="ai-feature-state">Later</span></summary>
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
      <summary><Sparkles size={15} /><span><strong>Turn notes into CRM data</strong><small>Extract preferences and a suggested follow-up</small></span><span className="ai-feature-state">Later</span></summary>
      <div className="ai-feature-content">
        <label className="ai-note-label">Lead notes<textarea readOnly rows={3} value={lead.notes ?? ''} placeholder="Add a note to this lead first." /></label>
        <div className="ai-extraction-preview"><span>Budget <strong>Not extracted</strong></span><span>Bedrooms <strong>Not extracted</strong></span><span>Location <strong>Not extracted</strong></span><span>Next follow-up <strong>Not extracted</strong></span></div>
        <button className="button button-secondary ai-disabled-action" type="button" disabled>Extract details</button>
      </div>
    </details>
  </section>
}

function CreateLeadModal({ token, currentUser, onClose, onCreated, onError }: { token: string; currentUser: User; onClose: () => void; onCreated: (lead: Lead) => void; onError: (message: string) => void }) {
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', source: 'manual' as LeadSource, status: 'new' as LeadStatus, budget_min_inr: '', budget_max_inr: '', bhk: '', preferred_location: '', notes: '' })
  const [saving, setSaving] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    onError('')
    const payload = {
      ...form,
      email: form.email || null,
      phone: form.phone || null,
      budget_min_inr: form.budget_min_inr ? Number(form.budget_min_inr) : null,
      budget_max_inr: form.budget_max_inr ? Number(form.budget_max_inr) : null,
      bhk: form.bhk ? Number(form.bhk) : null,
      notes: form.notes || null,
      assigned_to: currentUser.role === 'agent' ? currentUser.id : undefined,
    }
    try {
      const lead = await api<Lead>('/leads', token, { method: 'POST', body: JSON.stringify(payload) })
      onCreated(lead)
    } catch (requestError) {
      onError(getErrorMessage(requestError))
    } finally {
      setSaving(false)
    }
  }

  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }))

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-lead-title"><div className="modal-header"><div><span className="eyebrow">A NEW RELATIONSHIP</span><h2 id="create-lead-title">Add a lead<span className="heading-period">.</span></h2></div><button className="icon-button" aria-label="Close" onClick={onClose}><X size={19} /></button></div><form className="lead-form" onSubmit={(event) => void submit(event)}><label className="form-span">Full name<input autoFocus value={form.full_name} onChange={(event) => update('full_name', event.target.value)} placeholder="e.g. Aanya Mehta" maxLength={160} required /></label><label>Email address<input type="email" value={form.email} onChange={(event) => update('email', event.target.value)} placeholder="aanya@example.com" /></label><label>Phone number<input type="tel" value={form.phone} onChange={(event) => update('phone', event.target.value)} placeholder="+91 98765 43210" /></label><label>Preferred location<input value={form.preferred_location} onChange={(event) => update('preferred_location', event.target.value)} placeholder="Baner, Pune" maxLength={160} /></label><label>Lead source<select value={form.source} onChange={(event) => update('source', event.target.value)}>{Object.entries(sourceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Pipeline stage<select value={form.status} onChange={(event) => update('status', event.target.value)}>{stages.map((stage) => <option key={stage.value} value={stage.value}>{stage.label}</option>)}</select></label><label>BHK<input type="number" min="1" max="20" value={form.bhk} onChange={(event) => update('bhk', event.target.value)} placeholder="2" /></label><label>Budget from (₹)<input type="number" min="0" value={form.budget_min_inr} onChange={(event) => update('budget_min_inr', event.target.value)} placeholder="6000000" /></label><label>Budget up to (₹)<input type="number" min="0" value={form.budget_max_inr} onChange={(event) => update('budget_max_inr', event.target.value)} placeholder="9000000" /></label><label className="form-span">Notes<textarea value={form.notes} onChange={(event) => update('notes', event.target.value)} placeholder="What would be helpful to remember?" rows={3} /></label><div className="form-span form-footer"><span className="form-hint">Keep contact details accurate and use fictional data for demos.</span><div><button type="button" className="button button-secondary" onClick={onClose}>Cancel</button><button className="button button-primary" disabled={saving}>{saving ? 'Saving…' : 'Save lead'}<ArrowUpRight size={16} /></button></div></div></form></section></div>
}

function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Sparkles size={19} /></div><strong>{title}</strong><p>{description}</p>{action}</div>
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
