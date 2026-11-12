import type { Incident, IncidentType, Severity, Stats, User } from './types'
import {
  SEVERITY_LABELS, SEVERITY_ORDER, SEVERITY_RANK, STATUS_LABELS,
  TYPE_COLORS, TYPE_LABELS, fmtAgo,
} from './format'
import { TypeIcon } from './icons'

interface Props {
  incidents: Incident[]          // уже отфильтрованные (тип/степень)
  stats: Stats | null
  user: User
  sevFilter: Set<Severity>       // пусто = все
  typeFilter: Set<IncidentType>  // пусто = все
  onSevFilter: (s: Set<Severity>) => void
  onTypeFilter: (s: Set<IncidentType>) => void
  selectedId: number | null
  onSelect: (id: number | null) => void
}

function toggle<T>(set: Set<T>, v: T): Set<T> {
  const next = new Set(set)
  if (next.has(v)) next.delete(v)
  else next.add(v)
  return next
}

export default function Sidebar(p: Props) {
  const { incidents, stats, user } = p
  const visibleTypes: IncidentType[] = user.allowed_types ?? ['fire', 'flood', 'pollution', 'landslide']

  // счётчики степеней и типов считаем по всем ЧС роли (до фильтрации), чтобы цифры не «прыгали»
  const all = stats
    ? {
        low: stats.by_severity.low ?? 0,
        medium: stats.by_severity.medium ?? 0,
        high: stats.by_severity.high ?? 0,
      }
    : null

  const feed = [...incidents].sort(
    (a, b) =>
      SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] ||
      new Date(b.last_seen).getTime() - new Date(a.last_seen).getTime(),
  )

  const peopleTotal = incidents
    .filter((i) => i.status !== 'closed')
    .reduce((sum, i) => sum + i.people_count, 0)

  return (
    <aside>
      <div className="card">
        <h3>Обстановка</h3>
        <div className="tiles">
          <div className="tile high" title="ЧС высокой степени (по всем типам роли)">
            <b>{all?.high ?? '—'}</b>
            <span>высокая</span>
          </div>
          <div className="tile medium">
            <b>{all?.medium ?? '—'}</b>
            <span>средняя</span>
          </div>
          <div className="tile low">
            <b>{all?.low ?? '—'}</b>
            <span>низкая</span>
          </div>
          <div className="tile people" title="Людей в зонах активных очагов (по видимым ЧС)">
            <b>{peopleTotal}</b>
            <span>людей в зонах</span>
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Фильтры</h3>
        <div className="filterhead">
          <span>По степени опасности</span>
          {p.sevFilter.size > 0 && (
            <button className="linkbtn" onClick={() => p.onSevFilter(new Set())}>
              сбросить
            </button>
          )}
        </div>
        <div className="chips">
          {SEVERITY_ORDER.map((s) => (
            <button
              key={s}
              className={`chip sev-${s} ${p.sevFilter.has(s) ? 'on' : ''}`}
              onClick={() => p.onSevFilter(toggle(p.sevFilter, s))}
              title={`Показать ЧС ${SEVERITY_LABELS[s].toLowerCase()} степени`}
            >
              {SEVERITY_LABELS[s]}
              <span className="n">{all ? (all[s] ?? 0) : '—'}</span>
            </button>
          ))}
        </div>

        <div className="filterhead">
          <span>По типу</span>
          {p.typeFilter.size > 0 && (
            <button className="linkbtn" onClick={() => p.onTypeFilter(new Set())}>
              сбросить
            </button>
          )}
        </div>
        <div className="chips">
          {visibleTypes.map((t) => (
            <button
              key={t}
              className={`chip ${p.typeFilter.has(t) ? 'on' : ''}`}
              onClick={() => p.onTypeFilter(toggle(p.typeFilter, t))}
            >
              <span className="sw" style={{ background: TYPE_COLORS[t] }} />
              {TYPE_LABELS[t]}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>
          Лента ЧС · {feed.length}
          <span style={{ textTransform: 'none', letterSpacing: 0, fontWeight: 400 }}>
            {' '}— по убыванию опасности
          </span>
        </h3>
        <div className="feed" role="list">
          {feed.length === 0 && <div className="empty">Нет ЧС по выбранным фильтрам</div>}
          {feed.map((inc) => (
            <button
              key={inc.id}
              role="listitem"
              className={`item ${inc.id === p.selectedId ? 'sel' : ''} ${inc.status === 'closed' ? 'closed' : ''}`}
              style={{ ['--c' as string]: TYPE_COLORS[inc.type] }}
              onClick={() => p.onSelect(inc.id === p.selectedId ? null : inc.id)}
            >
              <span className="ico">
                <TypeIcon type={inc.type} />
              </span>
              <span className="meta">
                <span className="t">
                  {TYPE_LABELS[inc.type]}
                  <em className={`sev ${inc.severity}`}>{SEVERITY_LABELS[inc.severity]}</em>
                  {inc.people_count > 0 && (
                    <em className="sev" style={{ background: 'rgba(76,195,255,.15)', color: 'var(--accent)' }}>
                      людей: {inc.people_count}
                    </em>
                  )}
                </span>
                <span className="s">
                  {inc.subtype ? `${inc.subtype} · ` : ''}
                  {fmtAgo(inc.last_seen)} · {STATUS_LABELS[inc.status]}
                </span>
              </span>
              <span className={`st ${inc.status}`}>#{inc.id}</span>
            </button>
          ))}
        </div>
      </div>
    </aside>
  )
}
