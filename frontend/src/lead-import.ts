import type { CellValue } from 'exceljs'

export const LEAD_IMPORT_COLUMNS = [
  'full_name',
  'email',
  'phone',
  'source',
  'status',
  'budget_min_inr',
  'budget_max_inr',
  'bhk',
  'preferred_location',
  'notes',
  'assigned_to',
] as const

const MAX_FILE_BYTES = 2 * 1024 * 1024
const MAX_ROWS = 500
const SOURCES = new Set([
  'website',
  '99acres',
  'magicbricks',
  'instagram',
  'whatsapp',
  'walk_in',
  'manual',
  'csv_import',
  'other',
])
const STATUSES = new Set(['new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost'])
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export interface LeadImportPreflight {
  valid: boolean
  rowCount: number
  errors: string[]
}

class LeadImportReadError extends Error {}

function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let value = ''
  let quoted = false

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]
    if (quoted) {
      if (character === '"') {
        if (text[index + 1] === '"') {
          value += '"'
          index += 1
        } else {
          quoted = false
        }
      } else {
        value += character
      }
      continue
    }

    if (character === '"' && value.length === 0) {
      quoted = true
    } else if (character === ',') {
      row.push(value)
      value = ''
    } else if (character === '\n' || character === '\r') {
      row.push(value)
      rows.push(row)
      row = []
      value = ''
      if (character === '\r' && text[index + 1] === '\n') index += 1
    } else if (character === '"') {
      throw new LeadImportReadError('CSV contains a quote in an invalid position.')
    } else {
      value += character
    }
  }

  if (quoted) throw new LeadImportReadError('CSV contains an unclosed quoted field.')
  if (value.length > 0 || row.length > 0) {
    row.push(value)
    rows.push(row)
  }
  if (rows.length > 0) rows[0][0] = rows[0][0].replace(/^\uFEFF/, '')
  return rows
}

function excelCellText(value: CellValue | undefined): string {
  if (value == null) return ''
  if (value instanceof Date) return value.toISOString()
  if (typeof value !== 'object') return String(value)
  if ('result' in value) return excelCellText(value.result)
  if ('text' in value) return value.text
  if ('richText' in value) return value.richText.map((item) => item.text).join('')
  return ''
}

async function readExcel(file: File): Promise<string[][]> {
  const { Workbook } = await import('exceljs')
  const workbook = new Workbook()
  await workbook.xlsx.load(await file.arrayBuffer())
  const worksheet = workbook.worksheets[0]
  if (!worksheet) throw new LeadImportReadError('The Excel file does not contain a worksheet.')
  if (worksheet.rowCount > MAX_ROWS + 1) {
    throw new LeadImportReadError(`The first worksheet may contain at most ${MAX_ROWS} data rows.`)
  }
  return Array.from({ length: worksheet.rowCount }, (_, index) => {
    const values = worksheet.getRow(index + 1).values
    return Array.isArray(values) ? values.slice(1).map((value) => excelCellText(value)) : []
  })
}

function validateRows(rows: string[][]): LeadImportPreflight {
  const errors: string[] = []
  const headers = rows[0]?.map((value) => value.trim().toLowerCase()) ?? []
  while (headers.length > 0 && !headers[headers.length - 1]) headers.pop()

  if (headers.length === 0 || headers.some((header) => !header)) {
    return { valid: false, rowCount: 0, errors: ['The first row must contain a header for every column.'] }
  }
  if (new Set(headers).size !== headers.length) {
    errors.push('Column names must be unique; duplicate headers were found.')
  }
  if (!headers.includes('full_name')) errors.push('The required full_name column is missing.')
  const unknown = headers.filter((header) => !(LEAD_IMPORT_COLUMNS as readonly string[]).includes(header))
  if (unknown.length > 0) errors.push(`Unsupported columns: ${unknown.join(', ')}.`)
  if (errors.length > 0) return { valid: false, rowCount: 0, errors }

  const rowsWithValues = rows.slice(1)
    .map((cells, index) => ({ cells, row: index + 2 }))
    .filter(({ cells }) => cells.some((cell) => cell.trim() !== ''))
  if (rowsWithValues.length === 0) {
    errors.push('Add at least one lead row below the header.')
  }
  if (rowsWithValues.length > MAX_ROWS) {
    errors.push(`The file may contain at most ${MAX_ROWS} data rows.`)
  }

  const columnIndex = new Map(headers.map((header, index) => [header, index]))
  const cell = (cells: string[], column: string) => cells[columnIndex.get(column) ?? -1]?.trim() ?? ''
  for (const { cells, row } of rowsWithValues.slice(0, MAX_ROWS)) {
    const rowErrors: string[] = []
    if (cells.slice(headers.length).some((extra) => extra.trim() !== '')) {
      rowErrors.push('contains values beyond the header columns')
    }
    const name = cell(cells, 'full_name')
    if (!name) rowErrors.push('full_name is required')
    if (name.length > 160) rowErrors.push('full_name must be at most 160 characters')

    const email = cell(cells, 'email')
    if (email && !EMAIL_PATTERN.test(email)) rowErrors.push('email must be valid')

    for (const column of ['budget_min_inr', 'budget_max_inr', 'bhk']) {
      const value = cell(cells, column)
      if (value && (!/^\d+$/.test(value) || Number(value) < (column === 'bhk' ? 1 : 0))) {
        rowErrors.push(`${column} must be a whole number`)
      }
    }
    const minimum = cell(cells, 'budget_min_inr')
    const maximum = cell(cells, 'budget_max_inr')
    if (minimum && maximum && /^\d+$/.test(minimum) && /^\d+$/.test(maximum) && Number(minimum) > Number(maximum)) {
      rowErrors.push('budget_min_inr must not exceed budget_max_inr')
    }

    const source = cell(cells, 'source')
    if (source && !SOURCES.has(source)) rowErrors.push('source is not supported')
    const status = cell(cells, 'status')
    if (status && !STATUSES.has(status)) rowErrors.push('status is not supported')
    const assignee = cell(cells, 'assigned_to')
    if (assignee && !UUID_PATTERN.test(assignee)) rowErrors.push('assigned_to must be a user ID')

    if (rowErrors.length > 0) errors.push(`Row ${row}: ${rowErrors.join('; ')}.`)
    if (errors.length >= 8) break
  }

  return { valid: errors.length === 0, rowCount: rowsWithValues.length, errors }
}

export async function inspectLeadImportFile(file: File): Promise<LeadImportPreflight> {
  if (file.size === 0) return { valid: false, rowCount: 0, errors: ['The selected file is empty.'] }
  if (file.size > MAX_FILE_BYTES) {
    return { valid: false, rowCount: 0, errors: ['The file must be no larger than 2 MiB.'] }
  }

  const extension = file.name.toLowerCase().split('.').pop()
  if (extension !== 'csv' && extension !== 'xlsx') {
    return { valid: false, rowCount: 0, errors: ['Choose a UTF-8 .csv file or an Excel .xlsx file.'] }
  }

  try {
    const rows = extension === 'csv'
      ? parseCsv(new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()))
      : await readExcel(file)
    return validateRows(rows)
  } catch (error) {
    return {
      valid: false,
      rowCount: 0,
      errors: [error instanceof LeadImportReadError
        ? error.message
        : extension === 'csv'
          ? 'The CSV file could not be read. Check its quoting and UTF-8 encoding.'
          : 'The Excel file could not be read. Re-save it as a valid .xlsx workbook.'],
    }
  }
}
