import type { IncidentType } from './types'

// Лаконичные SVG-иконки типов ЧС (fill: currentColor).
export function TypeIcon({ type }: { type: IncidentType }) {
  switch (type) {
    case 'fire':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2c.6 3.2-.6 5.1-2 6.9C8.6 10.7 7 12.6 7 15a5 5 0 0 0 10 0c0-1.5-.6-2.7-1.4-3.8-.3 1-.9 1.7-1.8 2.1.3-3.1-.4-6.4-1.8-11.3z" />
        </svg>
      )
    case 'flood':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3 15c2 0 2-1.6 4-1.6S9 15 11 15s2-1.6 4-1.6 2 1.6 4 1.6 2-1.6 2-1.6V18c0 2-1.5 3-3 3H6c-1.7 0-3-1.2-3-3v-3zM12 3c3.5 4.4 6 7.3 6 9.6 0 1.5-1.2 2.4-2.5 2.4-1 0-1.7-.5-2.2-1.2l-.6-.9-.6.9c-.5.7-1.2 1.2-2.2 1.2C8.6 15 7 14.1 7 12.6 7 10.3 9.5 7.4 12 3z" />
        </svg>
      )
    case 'pollution':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M9 3h6l-1 3h1.5c1 0 1.6.7 1.9 1.6L20 17h1a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1h1l2.6-9.4C8.9 6.7 9.5 6 10.5 6H12l-1-3h-2z" />
        </svg>
      )
    case 'landslide':
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M13 3l8 13h-6l-4-4-3 7H2l6-11 3 3 2-8z" />
        </svg>
      )
  }
}

export function EyeLogo() {
  return (
    <svg className="eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}
