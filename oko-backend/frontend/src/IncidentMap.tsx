import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Incident, Telemetry } from './types'
import { TYPE_COLORS, TYPE_LABELS, SEVERITY_LABELS, fmtAgo } from './format'

interface Props {
  incidents: Incident[]
  selectedId: number | null
  onSelect: (id: number | null) => void
  drone: Telemetry | null
  track: Telemetry[]
}

// Спутниковые тайлы Esri World Imagery — бесплатно и без API-ключа
// (CARTO/Stadia и другие «тёмные» тайлы сейчас требуют ключ). Слегка
// затемнены CSS-фильтром в index.css, чтобы сочетаться с тёмной панелью.
const TILE_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
const TILE_OPTS = {
  attribution: 'Esri, Maxar, Earthstar Geographics',
  maxZoom: 20,
}

function incidentIcon(inc: Incident, selected: boolean): L.DivIcon {
  const c = TYPE_COLORS[inc.type]
  const sev = inc.severity === 'high' ? 'var(--high)' : inc.severity === 'medium' ? 'var(--medium)' : 'var(--low)'
  const pulse = inc.severity === 'high' && inc.status !== 'closed' ? 'pulse' : ''
  const sel = selected ? 'selected' : ''
  const closed = inc.status === 'closed' ? 'opacity:.45;' : ''
  return L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<div class="mk ${pulse} ${sel}" style="--c:${c};--sev:${sev};${closed}">
             <span class="ring"></span><span class="core"></span>
           </div>`,
  })
}

/** Настоящая карта (Leaflet, тёмные тайлы CARTO). Маркеры ЧС, дрон и его трек. */
export default function IncidentMap({ incidents, selectedId, onSelect, drone, track }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)
  const droneRef = useRef<L.Marker | null>(null)
  const trackRef = useRef<L.Polyline | null>(null)
  const selRef = useRef<L.Marker | null>(null)

  // инициализация карты (один раз)
  useEffect(() => {
    if (!ref.current || mapRef.current) return
    const map = L.map(ref.current, { center: [56.8389, 60.6057], zoom: 19, zoomControl: true })
    L.tileLayer(TILE_URL, TILE_OPTS).addTo(map)
    layerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // маркеры ЧС
  useEffect(() => {
    const layer = layerRef.current
    const map = mapRef.current
    if (!layer || !map) return
    layer.clearLayers()
    for (const inc of incidents) {
      const m = L.marker([inc.lat, inc.lon], {
        icon: incidentIcon(inc, inc.id === selectedId),
        title: TYPE_LABELS[inc.type],
      })
      m.bindPopup(
        `<b>${TYPE_LABELS[inc.type]}</b> · ${SEVERITY_LABELS[inc.severity]}<br>` +
          `Людей в зоне: <b>${inc.people_count}</b><br>` +
          `<span style="color:#8b98a5">${fmtAgo(inc.last_seen)}</span>`,
      )
      m.on('click', () => onSelect(inc.id))
      m.addTo(layer)
      if (inc.id === selectedId) selRef.current = m
    }
  }, [incidents, selectedId, onSelect])

  // подлет к выбранной ЧС
  useEffect(() => {
    const map = mapRef.current
    if (!map || !selectedId) return
    const inc = incidents.find((i) => i.id === selectedId)
    if (inc) map.flyTo([inc.lat, inc.lon], Math.max(map.getZoom(), 18), { duration: 0.6 })
  }, [selectedId, incidents])

  // маркер дрона
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (!drone) {
      droneRef.current?.remove()
      droneRef.current = null
      return
    }
    const html = '<div class="drone-mk"></div>'
    if (droneRef.current) {
      droneRef.current.setLatLng([drone.lat, drone.lon])
    } else {
      droneRef.current = L.marker([drone.lat, drone.lon], {
        icon: L.divIcon({ className: '', html, iconSize: [18, 18], iconAnchor: [9, 9] }),
        zIndexOffset: 1000,
        title: 'Дрон',
      })
        .bindPopup(
          `Дрон Mavic-1<br>Заряд: <b>${drone.battery ?? '—'}%</b> · ${drone.state ?? ''}<br>` +
            `Высота: ${drone.z} м`,
        )
        .addTo(map)
    }
  }, [drone])

  // трек активного вылета
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    trackRef.current?.remove()
    trackRef.current = null
    if (track.length >= 2) {
      trackRef.current = L.polyline(
        track.map((t) => [t.lat, t.lon] as [number, number]),
        { color: '#4cc3ff', weight: 2, opacity: 0.7, dashArray: '6 6' },
      ).addTo(map)
    }
  }, [track])

  return <div ref={ref} className="leaflet-container" aria-label="Карта ЧС" />
}

export const MAP_LEGEND: { color: string; label: string }[] = [
  { color: TYPE_COLORS.fire, label: 'Пожар' },
  { color: TYPE_COLORS.flood, label: 'Наводнение' },
  { color: TYPE_COLORS.pollution, label: 'Загрязнение' },
  { color: TYPE_COLORS.landslide, label: 'Оползень' },
]
