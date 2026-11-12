// Контракты API (см. app/schemas.py бэкенда).

export type Severity = 'low' | 'medium' | 'high'
export type IncidentType = 'fire' | 'flood' | 'pollution' | 'landslide'
export type IncidentStatus = 'new' | 'confirmed' | 'closed'
export type Role = 'operator' | 'firefighter' | 'ecologist' | 'viewer'

export interface User {
  id: number
  username: string
  role: Role
  display_name: string
  allowed_types: IncidentType[] | null // null = все типы ЧС
}

export interface Incident {
  id: number
  mission_id: number
  type: IncidentType
  severity: Severity
  status: IncidentStatus
  x: number
  y: number
  lat: number
  lon: number
  area_pct: number
  detections: number
  people_count: number // людей в зоне очага (не «пострадавшие»)
  subtype: string | null
  first_seen: string
  last_seen: string
  image_url: string | null
  note: string | null
}

export interface Stats {
  total_incidents: number
  by_type: Partial<Record<IncidentType, number>>
  by_severity: Partial<Record<Severity, number>>
  by_status: Partial<Record<IncidentStatus, number>>
  active_missions: number
}

export interface Telemetry {
  id: number
  mission_id: number
  time: string
  x: number
  y: number
  z: number
  lat: number
  lon: number
  yaw: number | null
  battery: number | null
  state: string | null
}

export interface Mission {
  id: number
  drone_id: number
  started_at: string
  finished_at: string | null
  status: 'active' | 'finished'
}

export interface Drone {
  id: number
  name: string
  model: string
}
