import { apiClient } from './client'

// Mirrors app/schemas/favorite_config_fields.py. Keys are those of GET /config-schema.
export interface FavoriteConfigFields {
  field_keys: string[]
}

export function getFavoriteConfigFields(): Promise<FavoriteConfigFields> {
  return apiClient.get<FavoriteConfigFields>('/favorite-config-fields')
}

// Replaces the stored favorites with exactly these keys.
export function putFavoriteConfigFields(fieldKeys: string[]): Promise<FavoriteConfigFields> {
  return apiClient.put<FavoriteConfigFields>('/favorite-config-fields', { field_keys: fieldKeys })
}
