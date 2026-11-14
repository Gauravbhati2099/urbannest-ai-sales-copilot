import {
  getCountries,
  getCountryCallingCode,
  parsePhoneNumberFromString,
  type CountryCode,
} from 'libphonenumber-js/max'

const phoneRegions = new Set<string>(getCountries())

export interface NormalizedPhone {
  phone: string
  phone_country_code: string
  phone_region: string
  phone_national_number: string
}

export function splitStoredPhone(phone: string | null, region: string | null | undefined) {
  const fallbackRegion = region && phoneRegions.has(region) ? region : 'IN'
  if (!phone) return { region: fallbackRegion, nationalNumber: '', e164: null as string | null }
  const parsed = parsePhoneNumberFromString(phone, fallbackRegion as CountryCode)
  if (!parsed || !parsed.isValid() || !parsed.country) {
    return { region: fallbackRegion, nationalNumber: '', e164: null as string | null }
  }
  return { region: parsed.country, nationalNumber: parsed.nationalNumber, e164: parsed.number }
}

export function normalizeName(value: string) {
  return value
    .trim()
    .replace(/\s+/g, ' ')
    .split(/([ '\u2019-])/)
    .map((part) => {
      if (part === ' ' || part === "'" || part === '\u2019' || part === '-') return part
      return part.toLowerCase().replace(/^./u, (first) => first.toUpperCase())
    })
    .join('')
}

export function validateName(value: string) {
  const normalized = normalizeName(value)
  if (!normalized) return 'Enter a name.'
  if (normalized.length > 160) return 'Name must be 160 characters or fewer.'
  const parts = normalized.split(/[ '\u2019-]/)
  if (parts.some((part) => {
    const characters = Array.from(part)
    return !part || characters.some((character, index) => {
      if (/^[\p{L}\p{M}]$/u.test(character)) return false
      return character !== '.' || index === 0 || !/^[\p{L}\p{M}]$/u.test(characters[index - 1])
    })
  })) {
    return 'Use letters, spaces, periods, hyphens, or apostrophes in the name.'
  }
  return ''
}

export function normalizeEmail(value: string) {
  return value.trim().toLowerCase()
}

export function validateEmail(value: string) {
  const normalized = normalizeEmail(value)
  if (!normalized) return 'Enter an email address.'
  if (normalized.length > 320 || !/^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$/.test(normalized)) {
    return 'Enter a valid email address.'
  }
  return ''
}

export function normalizePhone(value: string, region: string): NormalizedPhone | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!phoneRegions.has(region)) throw new Error('Choose a supported country.')
  if (!/^[\d\s()./[\]\-\u2010-\u2015]+$/u.test(trimmed)) {
    throw new Error('Use digits, spaces, brackets, periods, slashes, or hyphens in the phone number.')
  }
  const digits = trimmed.replace(/[\s()./[\]\-\u2010-\u2015]/gu, '')
  const country = region as CountryCode
  const parsed = parsePhoneNumberFromString(digits, country)
  if (!parsed || !parsed.isValid() || parsed.country !== region) {
    throw new Error('Enter a valid phone number for the selected country.')
  }
  return {
    phone: parsed.number,
    phone_country_code: `+${getCountryCallingCode(country)}`,
    phone_region: region,
    phone_national_number: parsed.nationalNumber,
  }
}
