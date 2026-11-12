import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Incident, IncidentType, Mission, Severity, Stats, Telemetry, User } from './types'
import { Api, ApiError } from './api'
import { SEVERITY_LABELS, TYPE_LABELS, ROLE_LABELS } from './format'
import { EyeLogo } from './icons'
import IncidentMap, { MAP_LEGEND } from './IncidentMap'
import Sidebar from './Sidebar'
import DetailCard from './DetailCard'
import LoginScreen from './LoginScreen'
import Toasts, { type Toast } from './Toasts'

const LS_TOKEN = 'oko.token'
const LS_USER = 'oko.user'
const POLL_MS = 2000

type Conn = 'live' | 'demo' | 'off'

export default function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(LS_TOKEN))
  const [user, setUser] = useState<User | null>(() => {
    try {
      const raw = localStorage.getItem(LS_USER)
      return raw ? (JSON.parse(raw) as User) : null
    } catch {
      return null
    }
  })

  const api = useMemo(() => new Api(token), [token])

  const [incidents, setIncidents] = useState<Incident[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [drone, setDrone] = useState<Telemetry | null>(null)
  const [track, setTrack] = useState<Telemetry[]>([])
  const [conn, setConn] = useState<Conn>('off')
  const [sevFilter, setSevFilter] = useState<Set<Severity>>(new Set())
  const [typeFilter, setTypeFilter] = useState<Set<IncidentType>>(new Set())
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const seenRef = useRef<Map<number, Severity>>(new Map())
  const toastSeq = useRef(0)

  const onLogin = useCallback((t: string, u: User) => {
    localStorage.setItem(LS_TOKEN, t)
    localStorage.setItem(LS_USER, JSON.stringify(u))
    setToken(t)
    setUser(u)
    setSelectedId(null)
    setSevFilter(new Set())
    setTypeFilter(new Set())
    seenRef.current = new Map()
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(LS_TOKEN)
    localStorage.removeItem(LS_USER)
    setToken(null)
    setUser(null)
    setIncidents([])
    setStats(null)
    setDrone(null)
    setTrack([])
    setToasts([])
    seenRef.current = new Map()
  }, [])

  const pushToast = useCallback((title: string, body: string) => {
    const id = ++toastSeq.current
    setToasts((prev) => [...prev.slice(-2), { id, title, body }])
    window.setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 7000)
  }, [])

  // основной опрос: ЧС, сводка, дрон, активный вылет
  useEffect(() => {
    if (!token || !user) return
    let active = true
    let lastMissionId: number | null = null

    async function poll() {
      try {
        const [incs, st, drones, missions] = await Promise.all([
          api.incidents(),
          api.stats(),
          api.drones(),
          api.missions(),
        ])
        if (!active) return
        setIncidents(incs)
        setStats(st)
        setConn('live')

        // тосты о высокой степени: новый очаг или эскалация до высокой
        for (const inc of incs) {
          const prev = seenRef.current.get(inc.id)
          if (inc.severity === 'high' && inc.status !== 'closed') {
            if (prev === undefined) {
              pushToast(
                `Высокая степень: ${TYPE_LABELS[inc.type]}`,
                `Новый очаг №${inc.id}${inc.people_count ? ` · людей в зоне: ${inc.people_count}` : ''}`,
              )
            } else if (prev !== 'high') {
              pushToast(
                `Эскалация: ${TYPE_LABELS[inc.type]} №${inc.id}`,
                `Степень повышена до высокой (${SEVERITY_LABELS[prev].toLowerCase()} → высокая)`,
              )
            }
          }
          seenRef.current.set(inc.id, inc.severity)
        }

        // дрон и трек активного вылета
        const droneRow = drones[0]
        if (droneRow) {
          try {
            const pos = await api.dronePosition(droneRow.id)
            if (active) setDrone(pos)
          } catch {
            if (active) setDrone(null)
          }
        }
        const activeMission = missions.find((m: Mission) => m.status === 'active')
        if (activeMission && activeMission.id !== lastMissionId) {
          lastMissionId = activeMission.id
          try {
            const tr = await api.missionTrack(activeMission.id)
            if (active) setTrack(tr)
          } catch {
            if (active) setTrack([])
          }
        } else if (!activeMission && lastMissionId !== null) {
          lastMissionId = null
          if (active) setTrack([])
        }
      } catch (e) {
        if (!active) return
        setConn((c) => (c === 'off' ? c : 'demo'))
        if (e instanceof ApiError && e.status === 401) logout()
      }
    }

    void poll()
    const timer = window.setInterval(() => void poll(), POLL_MS)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [token, user, api, pushToast, logout])

  const filtered = useMemo(
    () =>
      incidents.filter(
        (i) =>
          (sevFilter.size === 0 || sevFilter.has(i.severity)) &&
          (typeFilter.size === 0 || typeFilter.has(i.type)),
      ),
    [incidents, sevFilter, typeFilter],
  )

  const selected = filtered.find((i) => i.id === selectedId) ?? null

  if (!token || !user) {
    return <LoginScreen onLogin={onLogin} />
  }

  return (
    <div className="app">
      <header>
        <div className="brand">
          <EyeLogo />
          <div>
            Око МЧС
            <small>панель мониторинга ЧС</small>
          </div>
        </div>
        <div className="conn">
          <span className={`dot ${conn}`} />
          {conn === 'live' ? 'связь с сервером' : conn === 'demo' ? 'сервер недоступен' : 'нет связи'}
          {stats && <span>· вылетов активно: {stats.active_missions}</span>}
        </div>
        <div className="spacer" />
        <div className="userbox">
          <div className="who">
            <b>{user.display_name}</b>
            <span>{ROLE_LABELS[user.role]}</span>
          </div>
          <button className="logout" onClick={logout}>
            Выйти
          </button>
        </div>
      </header>

      <main>
        <div className="mapwrap">
          <IncidentMap
            incidents={filtered}
            selectedId={selectedId}
            onSelect={setSelectedId}
            drone={drone}
            track={track}
          />
          <div className="legend">
            {MAP_LEGEND.map((l) => (
              <span key={l.label}>
                <i style={{ background: l.color }} />
                {l.label}
              </span>
            ))}
            <span>
              <i style={{ background: '#090d12', border: '1.5px solid #ffffff' }} />
              Дрон
            </span>
          </div>
          <Toasts
            toasts={toasts}
            onPick={(t) => {
              const id = Number(/\b№(\d+)\b/.exec(t.title)?.[1] ?? /\b№(\d+)\b/.exec(t.body)?.[1])
              if (Number.isFinite(id)) setSelectedId(id)
              setToasts((prev) => prev.filter((x) => x.id !== t.id))
            }}
          />
          {selected && (
            <DetailCard
              incident={selected}
              canEdit={user.role === 'operator'}
              api={api}
              onClose={() => setSelectedId(null)}
              onChanged={(upd) =>
                setIncidents((prev) => prev.map((i) => (i.id === upd.id ? upd : i)))
              }
            />
          )}
          <div className="scale-note">
            {drone ? `Дрон: ${drone.battery ?? '—'}% · ${drone.z} м` : 'Дрон на земле'}
          </div>
        </div>
        <Sidebar
          incidents={filtered}
          stats={stats}
          user={user}
          sevFilter={sevFilter}
          typeFilter={typeFilter}
          onSevFilter={setSevFilter}
          onTypeFilter={setTypeFilter}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      </main>
    </div>
  )
}