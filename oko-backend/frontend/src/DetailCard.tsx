import { useEffect, useState } from 'react'
import type { Incident, IncidentStatus } from './types'
import { Api } from './api'
import { SEVERITY_LABELS, STATUS_LABELS, TYPE_LABELS, fmtTime } from './format'
import { TypeIcon } from './icons'

interface Props {
  incident: Incident
  canEdit: boolean // только оператор меняет статус/заметку
  api: Api
  onChanged: (inc: Incident) => void
  onClose: () => void
}

export default function DetailCard({ incident: inc, canEdit, api, onChanged, onClose }: Props) {
  const [note, setNote] = useState(inc.note ?? '')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => setNote(inc.note ?? ''), [inc.id, inc.note])

  async function save(patch: { status?: IncidentStatus; note?: string }) {
    setSaving(true)
    setErr(null)
    try {
      onChanged(await api.patchIncident(inc.id, patch))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="detail" role="dialog" aria-label={`ЧС №${inc.id}`}>
      <div className="d-head">
        <span className="ico" style={{ ['--c' as string]: 'var(--accent)' }}>
          <TypeIcon type={inc.type} />
        </span>
        <div>
          <b>
            {TYPE_LABELS[inc.type]} <em className={`sev ${inc.severity}`}>{SEVERITY_LABELS[inc.severity]}</em>
          </b>
          <small>
            ЧС №{inc.id} · {STATUS_LABELS[inc.status]}
          </small>
        </div>
        <button className="x" onClick={onClose} aria-label="Закрыть">
          ×
        </button>
      </div>

      {inc.image_url ? (
        <img className="photo" src={inc.image_url} alt={`Кадр с дрона: ${TYPE_LABELS[inc.type]}`} />
      ) : (
        <div className="nophoto">Нет фото — очаг передан без кадра</div>
      )}

      {inc.subtype && (
        <div className="rowline">
          <span>Подтип</span>
          <b>{inc.subtype}</b>
        </div>
      )}
      <div className="rowline">
        <span>Площадь в кадре</span>
        <b>{inc.area_pct.toFixed(1)}%</b>
      </div>
      <div className="rowline">
        <span>Подтверждена кадрами</span>
        <b>{inc.detections}</b>
      </div>
      <div className="rowline">
        <span>Впервые замечена</span>
        <b>{fmtTime(inc.first_seen)}</b>
      </div>
      <div className="rowline">
        <span>Последний кадр</span>
        <b>{fmtTime(inc.last_seen)}</b>
      </div>

      <div className="people-hl">
        Людей в зоне очага: <b>{inc.people_count}</b>
        <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 2 }}>
          Дрон считает всех людей рядом с очагом — среди них могут быть просто прохожие.
        </div>
      </div>

      {canEdit ? (
        <>
          <div className="actions" role="group" aria-label="Статус ЧС">
            {(Object.keys(STATUS_LABELS) as IncidentStatus[]).map((s) => (
              <button
                key={s}
                className={inc.status === s ? 'on' : ''}
                disabled={saving}
                onClick={() => inc.status !== s && save({ status: s })}
              >
                {STATUS_LABELS[s]}
              </button>
            ))}
          </div>
          <textarea
            className="note-edit"
            placeholder="Заметка оператора…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button
            className="savebtn"
            disabled={saving || note === (inc.note ?? '')}
            onClick={() => save({ note })}
          >
            {saving ? 'Сохранение…' : 'Сохранить заметку'}
          </button>
        </>
      ) : (
        inc.note && <div className="note-view">Заметка оператора: {inc.note}</div>
      )}
      {err && <div className="formerr" style={{ marginTop: 8 }}>{err}</div>}
    </div>
  )
}
