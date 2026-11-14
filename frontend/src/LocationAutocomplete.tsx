import { useEffect, useState } from 'react'
import type { LocationSelection } from './api'

interface PhotonFeature {
  properties?: Record<string, unknown>
  geometry?: { coordinates?: unknown }
}

interface LocationAutocompleteProps {
  value: LocationSelection | null
  onChange: (selection: LocationSelection | null, hasUnverifiedText: boolean) => void
}

const suggestionCache = new Map<string, LocationSelection[]>()

function asText(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function titleCase(value: string) {
  return value
    .trim()
    .replace(/\s+/g, ' ')
    .split(' ')
    .map((word) => word.toLowerCase().replace(/^./u, (first) => first.toUpperCase()))
    .join(' ')
}

function parseFeature(feature: PhotonFeature): LocationSelection | null {
  const properties = feature.properties
  const coordinates = feature.geometry?.coordinates
  if (!properties || !Array.isArray(coordinates) || coordinates.length < 2) return null

  const name = asText(properties.name)
  const country = asText(properties.country)
  const countryCode = asText(properties.countrycode)
  const longitude = coordinates[0]
  const latitude = coordinates[1]
  if (
    !name
    || !country
    || !countryCode
    || typeof latitude !== 'number'
    || typeof longitude !== 'number'
    || latitude < -90
    || latitude > 90
    || longitude < -180
    || longitude > 180
  ) return null

  const city = asText(properties.city) ?? (
    properties.osm_value === 'city' || properties.osm_value === 'town'
      ? name
      : null
  )
  const state = asText(properties.state)
  const displayName = [...new Set([name, city, state, country].filter((part): part is string => Boolean(part)))]
    .map(titleCase)
    .join(', ')
  const osmType = properties.osm_type
  return {
    display_name: displayName,
    city: city ? titleCase(city) : null,
    state: state ? titleCase(state) : null,
    country: titleCase(country),
    country_code: countryCode.toUpperCase(),
    latitude,
    longitude,
    osm_type: osmType === 'N' || osmType === 'W' || osmType === 'R' ? osmType : null,
    osm_id: typeof properties.osm_id === 'number' && properties.osm_id > 0
      ? properties.osm_id
      : null,
  }
}

export function LocationAutocomplete({ value, onChange }: LocationAutocompleteProps) {
  const [query, setQuery] = useState(value?.display_name ?? '')
  const [suggestions, setSuggestions] = useState<LocationSelection[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [retryCount, setRetryCount] = useState(0)
  const [activeSelection, setActiveSelection] = useState(value)

  useEffect(() => {
    const searchTerm = query.trim()
    if (activeSelection || searchTerm.length < 3) return

    const cacheKey = searchTerm.toLowerCase()
    if (suggestionCache.has(cacheKey)) return

    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setLoading(true)
      setError('')
      const url = new URL('https://photon.komoot.io/api/')
      url.searchParams.set('q', searchTerm)
      url.searchParams.set('limit', '6')
      url.searchParams.set('lang', 'en')
      void fetch(url, { signal: controller.signal })
        .then(async (response) => {
          if (!response.ok) throw new Error('Location search is temporarily unavailable.')
          const body: unknown = await response.json()
          if (
            typeof body !== 'object'
            || body === null
            || !('features' in body)
            || !Array.isArray(body.features)
          ) throw new Error('Location search returned an unexpected response.')
          const items = body.features
            .map((feature) => parseFeature(feature as PhotonFeature))
            .filter((location): location is LocationSelection => location !== null)
          suggestionCache.set(cacheKey, items)
          if (suggestionCache.size > 50) {
            const oldest = suggestionCache.keys().next().value
            if (oldest) suggestionCache.delete(oldest)
          }
          setSuggestions(items)
        })
        .catch((requestError: unknown) => {
          if (requestError instanceof DOMException && requestError.name === 'AbortError') return
          setError(requestError instanceof Error ? requestError.message : 'Location search failed.')
          setSuggestions([])
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }, 350)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [activeSelection, query, retryCount])

  const updateQuery = (nextQuery: string) => {
    setQuery(nextQuery)
    setActiveSelection(null)
    setSuggestions(suggestionCache.get(nextQuery.trim().toLowerCase()) ?? [])
    setLoading(false)
    setError('')
    onChange(null, Boolean(nextQuery.trim()))
  }

  const selectLocation = (selection: LocationSelection) => {
    setActiveSelection(selection)
    setQuery(selection.display_name)
    setSuggestions([])
    onChange(selection, false)
  }

  return (
    <label className="location-autocomplete form-span">
      Preferred location
      <input
        type="search"
        value={query}
        onChange={(event) => updateQuery(event.target.value)}
        placeholder="Search a city or locality"
        autoComplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={suggestions.length > 0}
        aria-controls="location-suggestions"
        aria-invalid={Boolean(query.trim() && !activeSelection)}
      />
      {query.trim() && !activeSelection && (
        <small className="inline-form-error">Choose a verified location from the suggestions.</small>
      )}
      {loading && <small className="location-search-state" role="status">Searching locations…</small>}
      {error && (
        <span className="location-search-error" role="alert">
          {error}
          <button type="button" onClick={() => setRetryCount((count) => count + 1)}>Retry</button>
        </span>
      )}
      {!loading && !error && query.trim().length >= 3 && !activeSelection && !suggestions.length && (
        <small className="location-search-state">No matching locations found.</small>
      )}
      {suggestions.length > 0 && (
        <ul className="location-suggestions" id="location-suggestions" role="listbox">
          {suggestions.map((suggestion) => (
            <li key={`${suggestion.osm_type}-${suggestion.osm_id}-${suggestion.display_name}`}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                onClick={() => selectLocation(suggestion)}
              >
                <strong>{suggestion.display_name}</strong>
                <small>{suggestion.country_code}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
      <small className="location-attribution">
        Location data <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a> · Search powered by <a href="https://photon.komoot.io/" target="_blank" rel="noreferrer">Photon</a>
      </small>
    </label>
  )
}
