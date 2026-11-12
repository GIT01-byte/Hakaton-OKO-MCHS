import type { IncidentStatus, IncidentType, Role, Severity } from './types'

export const TYPE_LABELS: Record<IncidentType, string> = {
  fire: 'Пожар',
  flood: 'Наводнение',
  pollution: 'Загрязнение',
  landslide: 'Завал',
}

export const TYPE_COLORS: Record<IncidentType, string> = {
  fire: '#ef4444',       // Красный (Пожар)
  flood: '#2563eb',      // Синий (Наводнение)
  pollution: '#eab308',  // Желтый (Загрязнения, свалки, утечки топлива)
  landslide: '#64748b',  // Серый (Завал / сходы грунта)
}

export const SEVERITY_LABELS: Record<Severity, string> = {
  low: 'Низкая',
  medium: 'Средняя',
  high: 'Высокая',
}

export const SEVERITY_RANK: Record<Severity, number> = { low: 1, medium: 2, high: 3 }

export const SEVERITY_ORDER: Severity[] = ['high', 'medium', 'low']

export const STATUS_LABELS: Record<IncidentStatus, string> = {
  new: 'Новая',
  confirmed: 'Подтверждена',
  closed: 'Закрыта',
}

export const ROLE_LABELS: Record<Role, string> = {
  operator: 'Оператор ЦУКС',
  firefighter: 'Пожарная служба',
  ecologist: 'Экологическая служба',
  viewer: 'Наблюдатель',
}

/** Время из API приходит в UTC с явным поясом — браузер сам покажет местное. */
export function fmtTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function fmtAgo(iso: string): string {
  const sec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (sec < 60) return 'только что'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} мин назад`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} ч назад`
  return `${Math.floor(h / 24)} дн назад`
}