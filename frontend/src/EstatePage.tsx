import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Building2, CalendarClock, ChevronDown, MapPin, Plus, Search, Users, X } from 'lucide-react'
import {
  api,
  type Estate,
  type EstateAssignee,
  type EstateInterest,
  type EstateInterestStatus,
  type EstatePipeline,
  type EstateStatus,
  type EstateType,
  type EstateVisit,
  type Lead,
  type LocationSelection,
  type User,
} from './api'
import { LocationAutocomplete } from './LocationAutocomplete'
import './EstatePage.css'

const estateTypes: { value: EstateType; label: string }[] = [
  { value: 'flat', label: 'Flat / apartment' },
  { value: 'plot', label: 'Plot' },
  { value: 'house', label: 'House' },
  { value: 'commercial_land', label: 'Commercial land' },
  { value: 'farmland', label: 'Farmland' },
  { value: 'farmhouse', label: 'Farmhouse' },
]

const estateStatuses: { value: EstateStatus; label: string }[] = [
  { value: 'available', label: 'Available' },
  { value: 'under_offer', label: 'Under offer' },
  { value: 'sold', label: 'Sold' },
  { value: 'withdrawn', label: 'Withdrawn' },
]

const interestStatuses: { value: EstateInterestStatus; label: string }[] = [
  { value: 'interested', label: 'Interested' },
  { value: 'site_visit', label: 'Site visit' },
  { value: 'negotiation', label: 'Negotiation' },
  { value: 'won', label: 'Won' },
  { value: 'lost', label: 'Lost' },
]

const propertyFields: Record<EstateType, { key: string; label: string; numeric?: boolean }[]> = {
  flat: [
    { key: 'bedrooms', label: 'Bedrooms', numeric: true },
    { key: 'bathrooms', label: 'Bathrooms', numeric: true },
    { key: 'built_up_area_sqft', label: 'Built-up area (sq ft)', numeric: true },
    { key: 'floor_number', label: 'Floor', numeric: true },
    { key: 'total_floors', label: 'Total floors', numeric: true },
    { key: 'parking_spaces', label: 'Parking spaces', numeric: true },
    { key: 'furnishing', label: 'Furnishing' },
  ],
  plot: [
    { key: 'plot_area_sqft', label: 'Plot area (sq ft)', numeric: true },
    { key: 'frontage_ft', label: 'Frontage (ft)', numeric: true },
    { key: 'depth_ft', label: 'Depth (ft)', numeric: true },
    { key: 'zoning', label: 'Zoning' },
    { key: 'facing', label: 'Facing' },
  ],
  house: [
    { key: 'bedrooms', label: 'Bedrooms', numeric: true },
    { key: 'bathrooms', label: 'Bathrooms', numeric: true },
    { key: 'built_up_area_sqft', label: 'Built-up area (sq ft)', numeric: true },
    { key: 'plot_area_sqft', label: 'Plot area (sq ft)', numeric: true },
    { key: 'floors', label: 'Floors', numeric: true },
    { key: 'parking_spaces', label: 'Parking spaces', numeric: true },
    { key: 'furnishing', label: 'Furnishing' },
  ],
  commercial_land: [
    { key: 'plot_area_sqft', label: 'Plot area (sq ft)', numeric: true },
    { key: 'frontage_ft', label: 'Frontage (ft)', numeric: true },
    { key: 'zoning', label: 'Zoning' },
  ],
  farmland: [
    { key: 'land_area_acres', label: 'Land area (acres)', numeric: true },
    { key: 'water_source', label: 'Water source' },
    { key: 'soil_type', label: 'Soil type' },
  ],
  farmhouse: [
    { key: 'bedrooms', label: 'Bedrooms', numeric: true },
    { key: 'bathrooms', label: 'Bathrooms', numeric: true },
    { key: 'built_up_area_sqft', label: 'Built-up area (sq ft)', numeric: true },
    { key: 'land_area_acres', label: 'Land area (acres)', numeric: true },
    { key: 'parking_spaces', label: 'Parking spaces', numeric: true },
    { key: 'water_source', label: 'Water source' },
    { key: 'furnishing', label: 'Furnishing' },
  ],
}

function estateTypeLabel(type: EstateType) {
  return estateTypes.find((option) => option.value === type)?.label ?? type
}

function estateStatusLabel(status: EstateStatus) {
  return estateStatuses.find((option) => option.value === status)?.label ?? status
}

function interestStatusLabel(status: EstateInterestStatus) {
  return interestStatuses.find((option) => option.value === status)?.label ?? status
}

function formatPrice(value: number | null) {
  if (value == null) return 'Price on request'
  if (value >= 10_000_000) return `₹${(value / 10_000_000).toFixed(value % 10_000_000 ? 1 : 0)}Cr`
  if (value >= 100_000) return `₹${(value / 100_000).toFixed(value % 100_000 ? 1 : 0)}L`
  return `₹${new Intl.NumberFormat('en-IN').format(value)}`
}

function detailsForForm(estate: Estate | null, type: EstateType) {
  return Object.fromEntries(
    propertyFields[type]
      .filter(({ key }) => estate?.details[key] != null)
      .map(({ key }) => [key, String(estate?.details[key])]),
  )
}

interface EstatePageProps {
  token: string
  currentUser: User
  leads: Lead[]
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
  onWorkspaceRefresh: () => void
}

export function EstatePage({
  token,
  currentUser,
  leads,
  canWrite,
  onError,
  onNotice,
  onWorkspaceRefresh,
}: EstatePageProps) {
  const [estates, setEstates] = useState<Estate[]>([])
  const [assignees, setAssignees] = useState<EstateAssignee[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<EstateType | ''>('')
  const [statusFilter, setStatusFilter] = useState<EstateStatus | ''>('')
  const [expandedEstateId, setExpandedEstateId] = useState<string | null>(null)
  const [pipeline, setPipeline] = useState<Record<string, EstatePipeline>>({})
  const [selectedLeadIds, setSelectedLeadIds] = useState<Record<string, string>>({})
  const [visitNotes, setVisitNotes] = useState<Record<string, string>>({})
  const [formEstate, setFormEstate] = useState<Estate | null | undefined>(undefined)

  const loadEstates = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [estateRows, estateAssignees] = await Promise.all([
        api<Estate[]>('/estates?limit=100', token),
        api<EstateAssignee[]>('/estates/assignees', token),
      ])
      setEstates(estateRows)
      setAssignees(estateAssignees)
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : 'Could not load estates.'
      setLoadError(message)
      onError(message)
    } finally {
      setLoading(false)
    }
  }, [onError, token])

  useEffect(() => {
    // eslint-disable-next-line react/set-state-in-effect -- Load server-owned estate inventory when the page opens.
    void loadEstates()
  }, [loadEstates])

  const filteredEstates = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase()
    return estates.filter((estate) => {
      const searchable = `${estate.title} ${estate.location.display_name} ${estate.description ?? ''}`.toLocaleLowerCase()
      return (!normalizedQuery || searchable.includes(normalizedQuery))
        && (!typeFilter || estate.estate_type === typeFilter)
        && (!statusFilter || estate.status === statusFilter)
    })
  }, [estates, query, statusFilter, typeFilter])

  const loadPipeline = async (estateId: string) => {
    try {
      const result = await api<EstatePipeline>(`/estates/${estateId}/pipeline`, token)
      setPipeline((current) => ({ ...current, [estateId]: result }))
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : 'Could not load estate enquiries.')
    }
  }

  const toggleEstate = (estateId: string) => {
    if (expandedEstateId === estateId) {
      setExpandedEstateId(null)
      return
    }
    setExpandedEstateId(estateId)
    if (!pipeline[estateId]) void loadPipeline(estateId)
  }

  const createInterest = async (estate: Estate) => {
    const leadId = selectedLeadIds[estate.id]
    if (!leadId) return
    onError('')
    try {
      await api<EstateInterest>(`/estates/${estate.id}/interests`, token, {
        method: 'POST',
        body: JSON.stringify({ lead_id: leadId }),
      })
      setSelectedLeadIds((current) => ({ ...current, [estate.id]: '' }))
      await loadPipeline(estate.id)
      onWorkspaceRefresh()
      onNotice('Lead linked to this estate.')
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : 'Could not link the lead.')
    }
  }

  const updateInterestStatus = async (
    estate: Estate,
    interest: EstateInterest,
    nextStatus: EstateInterestStatus,
  ) => {
    onError('')
    try {
      await api<EstateInterest>(`/estates/${estate.id}/interests/${interest.lead_id}`, token, {
        method: 'PATCH',
        body: JSON.stringify({ status: nextStatus }),
      })
      await loadPipeline(estate.id)
      onNotice(`${interest.lead_name} moved to ${interestStatusLabel(nextStatus).toLowerCase()}.`)
      onWorkspaceRefresh()
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : 'Could not update the lead stage.')
    }
  }

  const recordVisit = async (estate: Estate, interest: EstateInterest) => {
    onError('')
    try {
      await api<EstateVisit>(`/estates/${estate.id}/visits`, token, {
        method: 'POST',
        body: JSON.stringify({
          lead_id: interest.lead_id,
          notes: visitNotes[estate.id] || null,
        }),
      })
      setVisitNotes((current) => ({ ...current, [estate.id]: '' }))
      await loadPipeline(estate.id)
      onWorkspaceRefresh()
      onNotice(`Site visit recorded for ${interest.lead_name}.`)
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : 'Could not record the visit.')
    }
  }

  const saveEstate = async (payload: Record<string, unknown>, estateId?: string) => {
    onError('')
    try {
      const saved = await api<Estate>(estateId ? `/estates/${estateId}` : '/estates', token, {
        method: estateId ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      })
      setEstates((current) => estateId
        ? current.map((estate) => estate.id === saved.id ? saved : estate)
        : [saved, ...current])
      setFormEstate(undefined)
      onWorkspaceRefresh()
      onNotice(estateId ? 'Estate details saved.' : 'Estate added to your inventory.')
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : 'Could not save this estate.')
      throw requestError
    }
  }

  return (
    <>
      <section className="panel full-panel estate-page-panel">
        <div className="panel-header estate-page-header">
          <div>
            <p className="eyebrow">Property inventory</p>
            <h2>Estates your team can sell</h2>
            <p className="panel-subtitle">Keep listing details, ownership, buyer interest, negotiations, and site visits together.</p>
          </div>
          {canWrite && <button className="button button-primary" onClick={() => setFormEstate(null)}><Plus size={16} /> Add estate</button>}
        </div>
        <div className="estate-summary-row">
          <div><strong>{estates.length}</strong><span>in inventory</span></div>
          <div><strong>{estates.filter((estate) => estate.status === 'available').length}</strong><span>available</span></div>
          <div><strong>{estates.filter((estate) => estate.status === 'under_offer').length}</strong><span>under offer</span></div>
        </div>
        <div className="list-toolbar estate-toolbar">
          <label className="search-box"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search estate or location…" aria-label="Search estates" />{query && <button type="button" className="icon-button clear-search" aria-label="Clear estate search" onClick={() => setQuery('')}><X size={14} /></button>}</label>
          <label className="select-wrap"><span>Type</span><select aria-label="Filter estate type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as EstateType | '')}><option value="">All types</option>{estateTypes.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <label className="select-wrap"><span>Status</span><select aria-label="Filter estate status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as EstateStatus | '')}><option value="">All statuses</option>{estateStatuses.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <span className="result-count">{filteredEstates.length} of {estates.length}</span>
        </div>
        {loading && <div className="estate-loading">Loading your estate inventory…</div>}
        {!loading && loadError && <div className="estate-load-error" role="alert">{loadError}<button className="button button-secondary" onClick={() => void loadEstates()}>Try again</button></div>}
        {!loading && !loadError && !filteredEstates.length && (
          <div className="estate-empty">
            <span className="empty-icon"><Building2 size={18} /></span>
            <strong>{estates.length ? 'No estates match these filters' : 'Your inventory is ready to build'}</strong>
            <p>{estates.length ? 'Try another search or clear a filter.' : 'Add a property with its location and type-specific details, then connect it to interested leads.'}</p>
            {!estates.length && canWrite && <button className="button button-primary" onClick={() => setFormEstate(null)}><Plus size={15} /> Add your first estate</button>}
          </div>
        )}
        {!loading && !loadError && filteredEstates.length > 0 && (
          <div className="estate-list">
            {filteredEstates.map((estate) => {
              const isExpanded = expandedEstateId === estate.id
              const estatePipeline = pipeline[estate.id]
              const linkedIds = new Set((estatePipeline?.interests ?? []).map(({ lead_id }) => lead_id))
              const availableLeads = leads.filter((lead) => !linkedIds.has(lead.id))
              return (
                <article className={`estate-card ${isExpanded ? 'estate-card-expanded' : ''}`} key={estate.id}>
                  <div className="estate-card-main">
                    <div className="estate-card-symbol"><Building2 size={18} /></div>
                    <div className="estate-card-copy">
                      <div className="estate-card-title-row">
                        <button className="estate-title-button" onClick={() => toggleEstate(estate.id)} aria-expanded={isExpanded}>
                          <strong>{estate.title}</strong><ChevronDown size={15} />
                        </button>
                        <span className={`estate-status estate-status-${estate.status}`}>{estateStatusLabel(estate.status)}</span>
                      </div>
                      <span className="estate-card-meta"><span>{estateTypeLabel(estate.estate_type)}</span><i />{estate.location.display_name}</span>
                      <div className="estate-card-bottom">
                        <strong className="estate-price">{formatPrice(estate.asking_price_inr)}</strong>
                        <span><Users size={13} /> {estate.assigned_to_name ?? 'Unassigned'}</span>
                        {estatePipeline && <span>{estatePipeline.interests.length} lead{estatePipeline.interests.length === 1 ? '' : 's'} linked</span>}
                      </div>
                    </div>
                    {canWrite && <button className="button button-secondary estate-edit-button" onClick={() => setFormEstate(estate)}>Edit</button>}
                  </div>
                  {isExpanded && (
                    <div className="estate-details-panel">
                      <div className="estate-detail-facts">
                        {propertyFields[estate.estate_type].flatMap(({ key, label }) => {
                          const value = estate.details[key]
                          return value == null ? [] : [<div key={key}><small>{label}</small><strong>{value}</strong></div>]
                        })}
                      </div>
                      {estate.description && <p className="estate-description">{estate.description}</p>}
                      <div className="estate-location-line"><MapPin size={14} /><span>{estate.location.display_name}</span>{estate.location.latitude != null && estate.location.longitude != null && <a href={`https://www.openstreetmap.org/?mlat=${estate.location.latitude}&mlon=${estate.location.longitude}#map=16/${estate.location.latitude}/${estate.location.longitude}`} target="_blank" rel="noreferrer">Map</a>}</div>
                      <div className="estate-pipeline-heading"><div><p className="eyebrow">Buyer pipeline</p><h3>Interested leads</h3></div><span>{estatePipeline?.interests.length ?? 0}</span></div>
                      {estatePipeline ? estatePipeline.interests.length ? (
                        <div className="estate-interest-list">
                          {estatePipeline.interests.map((interest) => (
                            <div className="estate-interest-row" key={interest.id}>
                              <div><strong>{interest.lead_name}</strong><small>Assigned to {interest.assigned_to_name ?? 'Unassigned'}</small></div>
                              <label className="estate-interest-stage"><span>Stage</span><select aria-label={`Stage for ${interest.lead_name}`} disabled={!canWrite} value={interest.status} onChange={(event) => void updateInterestStatus(estate, interest, event.target.value as EstateInterestStatus)}>{interestStatuses.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                              {canWrite && <button className="button button-secondary" onClick={() => void recordVisit(estate, interest)}><CalendarClock size={14} /> Record visit</button>}
                            </div>
                          ))}
                        </div>
                      ) : <p className="estate-muted">No leads linked yet.</p> : <p className="estate-muted">Loading buyer pipeline…</p>}
                      {canWrite && estatePipeline && estate.status !== 'sold' && estate.status !== 'withdrawn' && (
                        <div className="estate-link-lead">
                          <label><span>Link an existing lead</span><select value={selectedLeadIds[estate.id] ?? ''} onChange={(event) => setSelectedLeadIds((current) => ({ ...current, [estate.id]: event.target.value }))}><option value="">Choose a lead…</option>{availableLeads.map((lead) => <option key={lead.id} value={lead.id}>{lead.full_name} · {lead.preferred_location ?? 'Location not set'}</option>)}</select></label>
                          <button className="button button-primary" disabled={!selectedLeadIds[estate.id]} onClick={() => void createInterest(estate)}>Link lead</button>
                        </div>
                      )}
                      {canWrite && (estatePipeline?.interests.length ?? 0) > 0 && (
                        <label className="estate-visit-note">Visit note<textarea rows={2} maxLength={10000} placeholder="Optional context to keep with the next visit record" value={visitNotes[estate.id] ?? ''} onChange={(event) => setVisitNotes((current) => ({ ...current, [estate.id]: event.target.value }))} /></label>
                      )}
                      <div className="estate-visit-history">
                        <div className="estate-pipeline-heading"><div><p className="eyebrow">Visit history</p><h3>Who has visited</h3></div><span>{estatePipeline?.visits.length ?? 0}</span></div>
                        {!estatePipeline?.visits.length
                          ? <p className="estate-muted">No site visits have been recorded.</p>
                          : estatePipeline.visits.map((visit) => <VisitRow visit={visit} key={visit.id} />)}
                      </div>
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </section>
      {formEstate !== undefined && (
        <EstateForm
          initialEstate={formEstate}
          assignees={assignees}
          currentUser={currentUser}
          onClose={() => setFormEstate(undefined)}
          onSave={(payload) => saveEstate(payload, formEstate?.id)}
        />
      )}
    </>
  )
}

function VisitRow({ visit }: { visit: EstateVisit }) {
  return <div className="estate-visit-row">
    <span className="estate-visit-dot" />
    <div><strong>{visit.lead_name}</strong><span>Visited · recorded by {visit.visited_by_name}</span>{visit.notes && <small>{visit.notes}</small>}</div>
    <time dateTime={visit.occurred_at}>{new Date(visit.occurred_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</time>
  </div>
}

function EstateForm({
  initialEstate,
  assignees,
  currentUser,
  onClose,
  onSave,
}: {
  initialEstate: Estate | null
  assignees: EstateAssignee[]
  currentUser: User
  onClose: () => void
  onSave: (payload: Record<string, unknown>) => Promise<void>
}) {
  const [title, setTitle] = useState(initialEstate?.title ?? '')
  const [estateType, setEstateType] = useState<EstateType>(initialEstate?.estate_type ?? 'flat')
  const [status, setStatus] = useState<EstateStatus>(initialEstate?.status ?? 'available')
  const [location, setLocation] = useState<LocationSelection | null>(initialEstate?.location ?? null)
  const [locationUnverified, setLocationUnverified] = useState(false)
  const [askingPrice, setAskingPrice] = useState(initialEstate?.asking_price_inr?.toString() ?? '')
  const [description, setDescription] = useState(initialEstate?.description ?? '')
  const [assignedTo, setAssignedTo] = useState(initialEstate?.assigned_to ?? (currentUser.role === 'agent' || currentUser.role === 'owner' || currentUser.role === 'co_owner' ? currentUser.id : ''))
  const [details, setDetails] = useState<Record<string, string>>(() => detailsForForm(initialEstate, initialEstate?.estate_type ?? 'flat'))
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')

  const changeEstateType = (nextType: EstateType) => {
    setEstateType(nextType)
    setDetails((current) => Object.fromEntries(
      Object.entries(current).filter(([key]) => propertyFields[nextType].some((field) => field.key === key)),
    ))
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!location) {
      setFormError('Choose a verified estate location.')
      return
    }
    if (locationUnverified) {
      setFormError('Choose a verified estate location.')
      return
    }
    setFormError('')
    const typedDetails = Object.fromEntries(
      Object.entries(details)
        .filter(([, value]) => value.trim())
        .map(([key, value]) => {
          const field = propertyFields[estateType].find((item) => item.key === key)
          return [key, field?.numeric ? Number(value) : value.trim()]
        }),
    )
    const payload = {
      title: title.trim(),
      estate_type: estateType,
      status,
      location,
      asking_price_inr: askingPrice ? Number(askingPrice) : null,
      description: description.trim() || null,
      assigned_to: assignedTo || null,
      details: typedDetails,
    }
    setSaving(true)
    try {
      await onSave(payload)
    } catch (requestError) {
      setFormError(requestError instanceof Error ? requestError.message : 'Could not save this estate.')
    } finally {
      setSaving(false)
    }
  }

  const assignedUser = initialEstate?.assigned_to && !assignees.some(({ id }) => id === initialEstate.assigned_to)
    ? initialEstate
    : null

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose() }}>
    <section className="create-modal estate-form-modal" role="dialog" aria-modal="true" aria-labelledby="estate-form-title">
      <div className="modal-header">
        <div><span className="eyebrow">PROPERTY INVENTORY</span><h2 id="estate-form-title">{initialEstate ? 'Edit estate' : 'Add an estate'}</h2></div>
        <button className="icon-button" type="button" aria-label="Close estate form" onClick={onClose} disabled={saving}><X size={19} /></button>
      </div>
      <p className="estate-form-intro">Capture the core listing details once. Fields change with the selected estate type.</p>
      <form className="estate-form" onSubmit={(event) => void submit(event)}>
        <label className="estate-form-span">Estate title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Cedar Heights, 2 BHK" minLength={2} maxLength={160} required autoFocus /></label>
        <label>Estate type<select value={estateType} onChange={(event) => changeEstateType(event.target.value as EstateType)}>{estateTypes.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label>Listing status<select value={status} onChange={(event) => setStatus(event.target.value as EstateStatus)}>{estateStatuses.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <LocationAutocomplete value={location} label="Estate location" onChange={(selected, unverified) => { setLocation(selected); setLocationUnverified(unverified); setFormError('') }} />
        <label>Asking price (INR)<input type="number" min="0" step="1" value={askingPrice} onChange={(event) => setAskingPrice(event.target.value)} placeholder="Optional" /></label>
        <label>Assigned seller<select value={assignedTo} onChange={(event) => setAssignedTo(event.target.value)}><option value="">Unassigned</option>{assignedUser && <option value={assignedUser.assigned_to ?? ''}>{assignedUser.assigned_to_name ?? 'Current assignee'}</option>}{assignees.map((member) => <option key={member.id} value={member.id}>{member.full_name} · {member.role.replace('_', ' ')}</option>)}</select></label>
        {propertyFields[estateType].map((field) => <label key={field.key}>{field.label}<input type={field.numeric ? 'number' : 'text'} min={field.numeric ? field.key === 'land_area_acres' ? '0.01' : field.key === 'floor_number' || field.key === 'parking_spaces' ? '0' : '1' : undefined} step={field.numeric ? field.key === 'land_area_acres' ? '0.01' : '1' : undefined} value={details[field.key] ?? ''} onChange={(event) => setDetails((current) => ({ ...current, [field.key]: event.target.value }))} /></label>)}
        <label className="estate-form-span">Description<textarea rows={3} maxLength={10000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Highlights, condition, ownership notes, or selling points" /></label>
        {formError && <p className="estate-form-error" role="alert">{formError}</p>}
        <div className="estate-form-actions">
          <button type="button" className="button button-secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="button button-primary" disabled={saving || !title.trim() || !location}>{saving ? 'Saving…' : initialEstate ? 'Save changes' : 'Add estate'}</button>
        </div>
      </form>
    </section>
  </div>
}
