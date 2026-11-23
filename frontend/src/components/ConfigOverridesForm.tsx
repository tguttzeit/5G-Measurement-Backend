import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ConfigSchemaField, ConfigSchemaGroup } from '../api/commands'
import {
  configFieldLabel,
  configFieldText,
  configGroupLabel,
  fieldInputError,
  formatConfigValue,
  isUnchanged,
  type ConfigInputs,
  type SoftWarning,
} from '../lib/configOverrides'
import { Banner, InfoPopover } from './ui'

export interface ConfigOverridesFormProps {
  groups: ConfigSchemaGroup[] | null
  loadError: string | null
  inputs: ConfigInputs
  currentConfig: Record<string, unknown> | null
  warnings: SoftWarning[]
  // `null` while the favorites are not loaded: the stars stay hidden, since saving would
  // replace the stored favorites with an incomplete list.
  favorites: string[] | null
  onChange: (key: string, value: string | null) => void
  onToggleFavorite: (key: string) => void
}

interface FieldEntry {
  group: ConfigSchemaGroup
  field: ConfigSchemaField
}

const FAVORITES_SECTION_ID = 'favorites'

function currentValue(currentConfig: Record<string, unknown> | null, field: ConfigSchemaField): string {
  if (!currentConfig || !(field.key in currentConfig)) return formatConfigValue(undefined)
  const value = currentConfig[field.key]
  const text =
    value === null || typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string'
      ? formatConfigValue(value)
      : formatConfigValue(undefined)
  return field.unit && value !== null && text !== formatConfigValue(undefined) ? `${text} ${field.unit}` : text
}

function FieldControl({
  field,
  ariaLabel,
  input,
  errorId,
  invalid,
  onChange,
}: {
  field: ConfigSchemaField
  ariaLabel: string
  input: string | null | undefined
  errorId: string
  invalid: boolean
  onChange: (value: string | null) => void
}) {
  const { t } = useTranslation('remoteConfiguration')
  const common = {
    'aria-label': ariaLabel,
    'aria-invalid': invalid || undefined,
    'aria-describedby': invalid ? errorId : undefined,
    className: 'remote-config__value-input',
  }

  if (field.type === 'enum' || field.type === 'bool') {
    // The options come from the delivered specification; there is no free-text entry for either.
    const options = field.type === 'bool' ? ['true', 'false'] : (field.values ?? [])
    return (
      <select {...common} value={input ?? ''} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t('overrides.unchanged')}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    )
  }

  if (field.type === 'float' || field.type === 'int') {
    const isNotSet = input === null
    return (
      <>
        <input
          {...common}
          type="number"
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.type === 'int' ? 1 : 'any'}
          disabled={isNotSet}
          value={isNotSet ? '' : (input ?? '')}
          onChange={(e) => onChange(e.target.value)}
        />
        {field.unit && <span className="remote-config__unit">{field.unit}</span>}
        {field.nullable && (
          <label className="remote-config__not-set">
            <input
              type="checkbox"
              checked={isNotSet}
              onChange={(e) => onChange(e.target.checked ? null : '')}
            />{' '}
            {t('overrides.notSetOption')}
          </label>
        )}
      </>
    )
  }

  // A type this version does not know is shown but cannot be edited, so no unchecked value is sent.
  return <span className="remote-config__unsupported">{t('overrides.unsupported')}</span>
}

function FieldRow({
  group,
  field,
  input,
  currentConfig,
  favorite,
  onChange,
  onToggleFavorite,
}: {
  group: ConfigSchemaGroup
  field: ConfigSchemaField
  input: string | null | undefined
  currentConfig: Record<string, unknown> | null
  favorite: boolean | null
  onChange: (value: string | null) => void
  onToggleFavorite: () => void
}) {
  const { t } = useTranslation('remoteConfiguration')
  const label = configFieldLabel(field.key)
  const description = configFieldText(field.key, 'description')
  const dependency = configFieldText(field.key, 'dependency')
  const changed = !isUnchanged(input)
  const error = fieldInputError(field, input)
  const errorId = `config-error-${field.key}`
  const range =
    field.min !== null && field.max !== null
      ? t('overrides.range', { min: field.min, max: field.max })
      : null

  return (
    <tr
      className={[
        changed && 'remote-config__row--changed',
        error && 'remote-config__row--invalid',
        input === null && 'remote-config__row--not-set',
      ]
        .filter(Boolean)
        .join(' ') || undefined}
    >
      <td>
        <div className="remote-config__label">
          {favorite !== null && (
            <button
              type="button"
              className="remote-config__favorite-btn"
              aria-pressed={favorite}
              aria-label={t('overrides.favorite.toggleAria', { label })}
              title={favorite ? t('overrides.favorite.remove') : t('overrides.favorite.add')}
              onClick={onToggleFavorite}
            >
              {favorite ? '★' : '☆'}
            </button>
          )}
          {label}
          {description && (
            <InfoPopover label={t('overrides.infoAria', { label })}>{description}</InfoPopover>
          )}
        </div>
        {dependency && <p className="remote-config__field-note">{dependency}</p>}
        {field.no_effect_yet && (
          <p className="remote-config__field-note">{t('overrides.noEffectYet')}</p>
        )}
      </td>
      <td className="remote-config__current">{currentValue(currentConfig, field)}</td>
      <td>
        <div className="remote-config__value-cell">
          <FieldControl
            field={field}
            ariaLabel={t('overrides.fieldAria', { group: configGroupLabel(group.id), label })}
            input={input}
            errorId={errorId}
            invalid={error !== null}
            onChange={onChange}
          />
        </div>
        {range && !error && <p className="remote-config__field-note">{range}</p>}
        {input === null && <p className="remote-config__field-note">{t('overrides.willReset')}</p>}
        {error && (
          <p id={errorId} className="remote-config__error">
            {t(`validation.${error.code}`, error)}
          </p>
        )}
      </td>
      <td>
        {changed && (
          <button
            type="button"
            className="remote-config__reset-btn"
            aria-label={t('overrides.resetField', { label })}
            title={t('overrides.reset')}
            onClick={() => onChange('')}
          >
            ↺
          </button>
        )}
      </td>
    </tr>
  )
}

function FieldGroup({
  title,
  entries,
  open,
  inputs,
  currentConfig,
  favorites,
  onToggle,
  onChange,
  onToggleFavorite,
}: {
  title: string
  entries: FieldEntry[]
  open: boolean
  inputs: ConfigInputs
  currentConfig: Record<string, unknown> | null
  favorites: Set<string> | null
  onToggle: () => void
  onChange: (key: string, value: string | null) => void
  onToggleFavorite: (key: string) => void
}) {
  const { t } = useTranslation('remoteConfiguration')
  const changes = entries.filter(({ field }) => !isUnchanged(inputs[field.key])).length
  return (
    // A group with pending changes stays open so a change can't be hidden by collapsing.
    <details className="remote-config__group" open={changes > 0 || open}>
      <summary
        className="remote-config__group-summary"
        onClick={(e) => {
          e.preventDefault()
          if (changes === 0) onToggle()
        }}
      >
        {title}
        {changes > 0 && <span className="remote-config__group-badge">{changes}</span>}
      </summary>
      <table className="remote-config__config-table">
        <thead>
          <tr>
            <th>{t('overrides.setting')}</th>
            <th>{t('overrides.current')}</th>
            <th>{t('overrides.newValue')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {entries.map(({ group, field }) => (
            <FieldRow
              key={field.key}
              group={group}
              field={field}
              input={inputs[field.key]}
              currentConfig={currentConfig}
              favorite={favorites ? favorites.has(field.key) : null}
              onChange={(value) => onChange(field.key, value)}
              onToggleFavorite={() => onToggleFavorite(field.key)}
            />
          ))}
        </tbody>
      </table>
    </details>
  )
}

export function ConfigOverridesForm({
  groups,
  loadError,
  inputs,
  currentConfig,
  warnings,
  favorites,
  onChange,
  onToggleFavorite,
}: ConfigOverridesFormProps) {
  const { t } = useTranslation('remoteConfiguration')
  const [expanded, setExpanded] = useState(false)
  // The favorites are what the user wants within reach, so that section starts open.
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set([FAVORITES_SECTION_ID]))
  const isChanged = (key: string) => !isUnchanged(inputs[key])
  const changeCount = (groups ?? []).flatMap((g) => g.fields).filter((f) => isChanged(f.key)).length

  const favoriteKeys = favorites ? new Set(favorites) : null
  const entries: FieldEntry[] = (groups ?? []).flatMap((group) =>
    group.fields.map((field) => ({ group, field })),
  )
  // A favorited field is shown only in the Favorites section, so a key never has two inputs.
  const favoriteEntries = entries.filter(({ field }) => favoriteKeys?.has(field.key))

  const toggleGroup = (id: string) =>
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (!next.delete(id)) next.add(id)
      return next
    })

  const renderGroup = (id: string, title: string, groupEntries: FieldEntry[]) => (
    <FieldGroup
      key={id}
      title={title}
      entries={groupEntries}
      open={expandedGroups.has(id)}
      inputs={inputs}
      currentConfig={currentConfig}
      favorites={favoriteKeys}
      onToggle={() => toggleGroup(id)}
      onChange={onChange}
      onToggleFavorite={onToggleFavorite}
    />
  )

  return (
    // Like a group below, the section stays open while it holds a pending change.
    <details className="remote-config__section" open={changeCount > 0 || expanded}>
      <summary
        className="remote-config__section-summary"
        onClick={(e) => {
          e.preventDefault()
          if (changeCount === 0) setExpanded((prev) => !prev)
        }}
      >
        <h2 className="remote-config__section-title">{t('overrides.title')}</h2>
        {changeCount > 0 && (
          <span className="remote-config__change-count">
            {t('overrides.pending', { count: changeCount })}
          </span>
        )}
      </summary>
      <p className="remote-config__hint">{t('overrides.hint')}</p>
      {loadError && <Banner tone="danger">{loadError}</Banner>}
      {!groups && !loadError && <p className="remote-config__hint">{t('overrides.schemaLoading')}</p>}
      {warnings.map((warning) => (
        <Banner key={warning} tone="warning" className="remote-config__warning">
          {t(`warnings.${warning}`)}
        </Banner>
      ))}
      {favoriteEntries.length > 0 &&
        renderGroup(FAVORITES_SECTION_ID, t('overrides.favorite.title'), favoriteEntries)}
      {(groups ?? []).map((group) => {
        const remaining = entries.filter(
          (entry) => entry.group === group && !favoriteKeys?.has(entry.field.key),
        )
        return remaining.length > 0 ? renderGroup(group.id, configGroupLabel(group.id), remaining) : null
      })}
    </details>
  )
}
