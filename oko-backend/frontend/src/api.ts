// Клиент API «Око МЧС». Тот же origin, что и панель (в dev Vite проксирует /api на :8000).
import type { Drone, Incident, IncidentStatus, Mission, Stats, Telemetry, User } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export class Api {
  private token: string | null

  constructor(token: string | null) {
    this.token = token
  }

  private async req<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`
    let res: Response
    try {
      res = await fetch(path, { ...init, headers })
    } catch {
      throw new ApiError(0, 'Сервер недоступен. Проверьте, что запущен uvicorn.')
    }
    if (res.status === 204) return undefined as T
    const text = await res.text()
    let body: unknown = null
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      /* не JSON */
    }
    if (!res.ok) {
      const detail =
        body && typeof body === 'object' && 'detail' in body
          ? String((body as { detail: unknown }).detail)
          : `Ошибка ${res.status}`
      throw new ApiError(res.status, detail)
    }
    return body as T
  }

  login(username: string, password: string): Promise<{ token: string; user: User }> {
    return this.req('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
  }

  me(): Promise<User> {
    return this.req('/api/me')
  }

  incidents(): Promise<Incident[]> {
    return this.req('/api/incidents?limit=500')
  }

  stats(): Promise<Stats> {
    return this.req('/api/stats')
  }

  drones(): Promise<Drone[]> {
    return this.req('/api/drones')
  }

  dronePosition(droneId: number): Promise<Telemetry> {
    return this.req(`/api/drones/${droneId}/position`)
  }

  missions(): Promise<Mission[]> {
    return this.req('/api/missions')
  }

  missionTrack(missionId: number): Promise<Telemetry[]> {
    return this.req(`/api/missions/${missionId}/track`)
  }

  patchIncident(id: number, patch: { status?: IncidentStatus; note?: string }): Promise<Incident> {
    return this.req(`/api/incidents/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
  }
}

// Фото отдаётся бэкендом по /media/... — тот же origin.
export function mediaUrl(imageUrl: string): string {
  return imageUrl
}
