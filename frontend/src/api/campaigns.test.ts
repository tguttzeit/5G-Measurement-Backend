import { describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { type Campaign, defaultCampaign, formatCampaignPeriod } from './campaigns'

function campaign(overrides: Partial<Campaign> & Pick<Campaign, 'id'>): Campaign {
  return { name: `campaign-${overrides.id}`, start: null, end: null, ...overrides }
}

describe('defaultCampaign', () => {
  it('picks the campaign with the most recent run end', () => {
    const older = campaign({ id: 1, start: '2026-01-01', end: '2026-02-01' })
    const newer = campaign({ id: 2, start: '2026-01-15', end: '2026-06-01' })

    expect(defaultCampaign([older, newer])).toBe(newer)
    expect(defaultCampaign([newer, older])).toBe(newer)
  })

  it('lets the later created campaign win a tie on the end day', () => {
    const first = campaign({ id: 1, end: '2026-06-01' })
    const second = campaign({ id: 2, end: '2026-06-01' })

    expect(defaultCampaign([second, first])).toBe(second)
    expect(defaultCampaign([first, second])).toBe(second)
  })

  it('ignores campaigns without runs', () => {
    const empty = campaign({ id: 1 })
    const withRuns = campaign({ id: 2, start: '2026-01-01', end: '2026-01-02' })

    expect(defaultCampaign([empty, withRuns])).toBe(withRuns)
  })

  it('is null when no campaign has runs', () => {
    expect(defaultCampaign([])).toBeNull()
    expect(defaultCampaign([campaign({ id: 1 })])).toBeNull()
  })
})

describe('formatCampaignPeriod', () => {
  it('shows the days of the oldest and newest run', () => {
    expect(formatCampaignPeriod(campaign({ id: 1, start: '2026-06-10', end: '2026-08-21' }))).toBe(
      '10/06/2026 – 21/08/2026',
    )
  })

  it('formats the days in the selected language', async () => {
    await i18n.changeLanguage('de')
    expect(formatCampaignPeriod(campaign({ id: 1, start: '2026-06-10', end: '2026-08-21' }))).toBe(
      '10.06.2026 – 21.08.2026',
    )
  })

  it('says so when the campaign has no runs', () => {
    expect(formatCampaignPeriod(campaign({ id: 1 }))).toBe('No runs')
  })
})
