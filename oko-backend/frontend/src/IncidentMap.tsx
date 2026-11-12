import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Incident, Telemetry } from "./types";
import { TYPE_COLORS, TYPE_LABELS, SEVERITY_LABELS, fmtAgo } from "./format";

interface Props {
  incidents: Incident[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  drone: Telemetry | null;
  track: Telemetry[];
}

const ARENA = {
  img: "/arena.jpg",
  sizeM: 25,
  imgW: 811,
  imgH: 810,
  originX: 5,
  originY: 5,
  northUp: true,
  eastRight: true,
};

const PX_PER_M = (ARENA.imgW + ARENA.imgH) / 2 / ARENA.sizeM;

function toPoint(x: number, y: number): [number, number] {
  const row = ARENA.northUp
    ? (ARENA.originY - y) * PX_PER_M + ARENA.imgH / 2
    : (y - ARENA.originY) * PX_PER_M + ARENA.imgH / 2;
  const col = ARENA.eastRight
    ? (x - ARENA.originX) * PX_PER_M + ARENA.imgW / 2
    : (ARENA.originX - x) * PX_PER_M + ARENA.imgW / 2;
  return [row, col];
}

const BOUNDS: [[number, number], [number, number]] = [
  [0, 0],
  [ARENA.imgH, ARENA.imgW],
];

function incidentIcon(inc: Incident, selected: boolean): L.DivIcon {
  const c = TYPE_COLORS[inc.type];
  const sev =
    inc.severity === "high"
      ? "var(--high)"
      : inc.severity === "medium"
        ? "var(--medium)"
        : "var(--low)";
  const pulse =
    inc.severity === "high" && inc.status !== "closed" ? "pulse" : "";
  const sel = selected ? "selected" : "";
  const closed = inc.status === "closed" ? "opacity:.45;" : "";
  return L.divIcon({
    className: "",
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<div class="mk ${pulse} ${sel}" style="--c:${c};--sev:${sev};${closed}">
             <span class="ring"></span><span class="core"></span>
           </div>`,
  });
}

export default function IncidentMap({
  incidents,
  selectedId,
  onSelect,
  drone,
  track,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const shapesLayerRef = useRef<L.LayerGroup | null>(null);
  const droneRef = useRef<L.Marker | null>(null);
  const trackRef = useRef<L.Polyline | null>(null);

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = L.map(ref.current, {
      crs: L.CRS.Simple,
      minZoom: -1,
      maxZoom: 5,
      zoomSnap: 0.25,
      zoomControl: true,
      attributionControl: false,
    });
    L.imageOverlay(ARENA.img, BOUNDS, { interactive: false }).addTo(map);

    shapesLayerRef.current = L.layerGroup().addTo(map);
    markersLayerRef.current = L.layerGroup().addTo(map);

    map.fitBounds(BOUNDS);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const markersLayer = markersLayerRef.current;
    const shapesLayer = shapesLayerRef.current;
    const map = mapRef.current;
    if (!markersLayer || !shapesLayer || !map) return;

    markersLayer.clearLayers();
    shapesLayer.clearLayers();

    for (const inc of incidents) {
      const center = toPoint(inc.x, inc.y);
      const color = TYPE_COLORS[inc.type];
      const isSel = inc.id === selectedId;

      // 1. Пожар (Красный) — радиус
      if (inc.type === "fire") {
        const radiusMeters = Math.max(1.5, Math.sqrt(inc.area_pct || 4) * 0.8);
        const radiusPx = radiusMeters * PX_PER_M;

        const circle = L.circle(center, {
          radius: radiusPx,
          color: color,
          weight: isSel ? 3 : 1.5,
          dashArray: "4 4",
          fillColor: color,
          fillOpacity: isSel ? 0.45 : 0.25,
          className: "hazard-area",
        });
        circle.on("click", () => onSelect(inc.id));
        circle.addTo(shapesLayer);
      }
      // 2. Наводнение (Синий) — квадрат (камера 90 градусов вниз)
      else if (inc.type === "flood") {
        const halfSideMeters = Math.max(
          1.8,
          Math.sqrt(inc.area_pct || 9) * 0.7,
        );
        const halfSidePx = halfSideMeters * PX_PER_M;

        const bounds: L.LatLngBoundsExpression = [
          [center[0] - halfSidePx, center[1] - halfSidePx],
          [center[0] + halfSidePx, center[1] + halfSidePx],
        ];
        const box = L.rectangle(bounds, {
          color: color,
          weight: isSel ? 3 : 2,
          fillColor: color,
          fillOpacity: isSel ? 0.5 : 0.3,
          className: "hazard-area",
        });
        box.on("click", () => onSelect(inc.id));
        box.addTo(shapesLayer);
      }
      // 3. Загрязнение (Жёлтый) и Завал (Серый)
      else {
        const rPx =
          Math.max(1.2, Math.sqrt(inc.area_pct || 4) * 0.6) * PX_PER_M;
        const shape = L.circle(center, {
          radius: rPx,
          color: color,
          weight: isSel ? 3 : 1.5,
          fillColor: color,
          fillOpacity: 0.3,
          className: "hazard-area",
        });
        shape.on("click", () => onSelect(inc.id));
        shape.addTo(shapesLayer);
      }

      const m = L.marker(center, {
        icon: incidentIcon(inc, isSel),
        title: TYPE_LABELS[inc.type],
      });

      m.bindPopup(`
        <div style="min-width: 170px;">
          <b style="color:${color}; font-size:14px;">${TYPE_LABELS[inc.type]}</b> 
          <span style="font-size:11px; opacity:0.8;">(${SEVERITY_LABELS[inc.severity]})</span><br/>
          <b>Координаты:</b> X: ${inc.x.toFixed(2)} м, Y: ${inc.y.toFixed(2)} м<br/>
          <b>Площадь в кадре:</b> ${inc.area_pct.toFixed(1)}%<br/>
          <b>Людей рядом:</b> <b>${inc.people_count}</b><br/>
          <small style="color:#8b98a5">${fmtAgo(inc.last_seen)}</small>
        </div>
      `);
      m.on("click", () => onSelect(inc.id));
      m.addTo(markersLayer);
    }
  }, [incidents, selectedId, onSelect]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedId) return;
    const inc = incidents.find((i) => i.id === selectedId);
    if (inc) {
      map.flyTo(toPoint(inc.x, inc.y), 2.5, { duration: 0.8 });
    }
  }, [selectedId, incidents]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!drone) {
      droneRef.current?.remove();
      droneRef.current = null;
      return;
    }

    const pos = toPoint(drone.x, drone.y);
    const yawDeg = drone.yaw ? -(drone.yaw * (180 / Math.PI)) : 0;

    const droneHtml = `
      <div class="drone-wrap" style="transform: rotate(${yawDeg}deg);">
        <div class="drone-mk" title="МЧС Дрон-Разведчик"></div>
      </div>
    `;

    if (droneRef.current) {
      droneRef.current.setLatLng(pos);
      const icon = droneRef.current.getIcon() as L.DivIcon;
      icon.options.html = droneHtml;
      droneRef.current.setIcon(icon);

      // 🔥 Жестко центрируем карту на дроне при каждом обновлении (слежение)
      map.panTo(pos, { animate: true, duration: 0.5 });
    } else {
      droneRef.current = L.marker(pos, {
        icon: L.divIcon({
          className: "",
          html: droneHtml,
          iconSize: [24, 24],
          iconAnchor: [12, 12],
        }),
        zIndexOffset: 2000,
      })
        .bindPopup(
          `
          <b>Дрон МЧС (Патруль)</b><br/>
          Координаты: X: ${drone.x.toFixed(1)} м, Y: ${drone.y.toFixed(1)} м<br/>
          Высота: <b>${drone.z.toFixed(1)} м</b><br/>
          Заряд АКБ: <b>${drone.battery ?? 100}%</b><br/>
          Статус: ${drone.state ?? "в полете"}
        `,
        )
        .addTo(map);

      // 🔥 Когда дрон только появился, ставим его в центр и задаем зум 3
      map.setView(pos, 3);
    }
  }, [drone]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    trackRef.current?.remove();
    trackRef.current = null;
    if (track.length >= 2) {
      trackRef.current = L.polyline(
        track.map((t) => toPoint(t.x, t.y)),
        { color: "#38bdf8", weight: 2.5, opacity: 0.8, dashArray: "5, 8" },
      ).addTo(map);
    }
  }, [track]);

  return (
    <div
      ref={ref}
      className="leaflet-container"
      aria-label="Карта оперативной обстановки"
    />
  );
}

export const MAP_LEGEND: { color: string; label: string }[] = [
  { color: TYPE_COLORS.fire, label: "Пожар (радиус)" },
  { color: TYPE_COLORS.flood, label: "Наводнение (квадрат)" },
  { color: TYPE_COLORS.pollution, label: "Загрязнение" },
  { color: TYPE_COLORS.landslide, label: "Завал" },
];
