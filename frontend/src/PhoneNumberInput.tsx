import { getCountries, getCountryCallingCode } from 'libphonenumber-js/max'
import { normalizePhone } from './form-normalization'

const countries = getCountries()
  .map((region) => ({
    region,
    callingCode: getCountryCallingCode(region),
  }))
  .sort((left, right) => left.region.localeCompare(right.region))

interface PhoneNumberInputProps {
  label: string
  value: string
  region: string
  onChange: (value: string) => void
  onRegionChange: (region: string) => void
  onBlur?: () => void
  error?: string
}

export function PhoneNumberInput({
  label,
  value,
  region,
  onChange,
  onRegionChange,
  onBlur,
  error,
}: PhoneNumberInputProps) {
  let validationError = ''
  if (value.trim()) {
    try {
      normalizePhone(value, region)
    } catch (validation) {
      validationError = validation instanceof Error ? validation.message : 'Enter a valid phone number.'
    }
  }
  const message = error || validationError

  return (
    <label className="phone-number-field">
      {label}
      <span className="phone-number-inputs">
        <select
          aria-label="Country calling code"
          value={region}
          onChange={(event) => onRegionChange(event.target.value)}
        >
          {countries.map(({ region: country, callingCode }) => (
            <option key={country} value={country}>
              {country} (+{callingCode})
            </option>
          ))}
        </select>
        <input
          type="tel"
          autoComplete="tel-national"
          inputMode="tel"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          aria-invalid={Boolean(message)}
          aria-describedby={message ? 'phone-number-error' : undefined}
          placeholder="Phone number"
        />
      </span>
      {message && <small className="inline-form-error" id="phone-number-error">{message}</small>}
    </label>
  )
}
