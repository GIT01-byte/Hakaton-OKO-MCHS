"""Око МЧС: серверная часть (приём данных от дрона, хранение, выдача панели мониторинга)."""
import os
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .auth import (check_type_visible, current_user, drone_auth, operator_or_drone,
                   require_roles, visible_types_clause)
from .db import Base, SessionLocal, engine, get_db
from .logic import (allowed_types, as_utc, distance, max_severity, normalize_severity,
                    normalize_type, utcnow)
from .models import Drone, Incident, Mission, Telemetry, User
from .schemas import (DroneOut, IncidentCreated, IncidentOut, IncidentPatch,
                      LoginIn, LoginOut, MissionCreate, MissionOut, StatsOut,
                      TelemetryIn, TelemetryOut, UserOut)
from .security import hash_password, make_token, verify_password

os.makedirs(os.path.join(config.MEDIA_DIR, "incidents"), exist_ok=True)

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png"}

# Демо-пользователи (создаются при первом запуске). Пароли задавайте через seed!
DEFAULT_USERS = [
    ("operator", "operator123", "operator", "Оператор ЦУКС"),
    ("fire", "fire123", "firefighter", "Пожарная служба"),
    ("eco", "eco123", "ecologist", "Экологическая служба"),
    ("viewer", "viewer123", "viewer", "Наблюдатель"),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(func.count(Drone.id))) == 0:
            db.add(Drone(name="Mavic-1", model="DJI Mavic 2 Pro"))
        if db.scalar(select(func.count(User.id))) == 0:
            for username, password, role, name in DEFAULT_USERS:
                db.add(User(username=username, password_hash=hash_password(password),
                            role=role, display_name=name))
        db.commit()
    yield


app = FastAPI(title="Око МЧС API", version="2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")


# ---------------------------------------------------------------- служебное
@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- вход
@app.post("/api/login", response_model=LoginOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    token = make_token(user.id, user.username, user.role, user.display_name)
    allowed = allowed_types(user.role)
    return LoginOut(token=token, user=UserOut(
        id=user.id, username=user.username, role=user.role, display_name=user.display_name,
        allowed_types=sorted(allowed) if allowed is not None else None,
    ))


@app.get("/api/me", response_model=UserOut)
def me(user: dict = Depends(current_user)):
    allowed = allowed_types(user["role"])
    return UserOut(id=int(user["sub"]), username=user["username"], role=user["role"],
                   display_name=user.get("name", ""),
                   allowed_types=sorted(allowed) if allowed is not None else None)


# ---------------------------------------------------------------- дроны и миссии
@app.get("/api/drones", response_model=List[DroneOut])
def list_drones(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Drone).order_by(Drone.id)).all()


@app.get("/api/drones/{drone_id}/position", response_model=TelemetryOut)
def drone_position(drone_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Последнее известное положение дрона."""
    row = db.scalars(
        select(Telemetry)
        .join(Mission, Mission.id == Telemetry.mission_id)
        .where(Mission.drone_id == drone_id)
        .order_by(Telemetry.time.desc(), Telemetry.id.desc())
        .limit(1)
    ).first()
    if row is None:
        raise HTTPException(404, "Нет телеметрии для этого дрона")
    return row


@app.get("/api/missions", response_model=List[MissionOut])
def list_missions(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Mission).order_by(Mission.started_at.desc())).all()


@app.post("/api/missions", response_model=MissionOut, status_code=201)
def start_mission(body: MissionCreate, user: dict = Depends(operator_or_drone),
                  db: Session = Depends(get_db)):
    if db.get(Drone, body.drone_id) is None:
        raise HTTPException(404, "Дрон не найден")
    mission = Mission(drone_id=body.drone_id)
    db.add(mission)
    db.commit()
    return mission


@app.post("/api/missions/{mission_id}/finish", response_model=MissionOut)
def finish_mission(mission_id: int, user: dict = Depends(operator_or_drone),
                   db: Session = Depends(get_db)):
    mission = db.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(404, "Миссия не найдена")
    mission.status = "finished"
    mission.finished_at = utcnow()
    db.commit()
    return mission


@app.get("/api/missions/{mission_id}/track", response_model=List[TelemetryOut])
def mission_track(mission_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Весь пройденный путь дрона (для линии маршрута на карте)."""
    if db.get(Mission, mission_id) is None:
        raise HTTPException(404, "Миссия не найдена")
    return db.scalars(
        select(Telemetry).where(Telemetry.mission_id == mission_id).order_by(Telemetry.time, Telemetry.id)
    ).all()


# ---------------------------------------------------------------- телеметрия (дрон)
@app.post("/api/telemetry", response_model=TelemetryOut, status_code=201)
def post_telemetry(body: TelemetryIn, request: Request, db: Session = Depends(get_db)):
    """Контроллер дрона шлёт положение. Требуется ключ X-API-Key."""
    drone_auth(request)
    if db.get(Mission, body.mission_id) is None:
        raise HTTPException(404, "Миссия не найдена")
    row = Telemetry(
        mission_id=body.mission_id, x=body.x, y=body.y, z=body.z, yaw=body.yaw,
        battery=body.battery, state=body.state,
        time=as_utc(body.time) or utcnow(),
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------- ЧС
def _save_image(image: UploadFile) -> str:
    ext = os.path.splitext(image.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(422, "Фото должно быть .jpg или .png")
    data = image.file.read(config.MAX_IMAGE_BYTES + 1)
    if len(data) > config.MAX_IMAGE_BYTES:
        raise HTTPException(413, "Фото слишком большое")
    rel = "incidents/%s%s" % (uuid.uuid4().hex, ext)
    with open(os.path.join(config.MEDIA_DIR, rel), "wb") as f:
        f.write(data)
    return rel


def _remove_image(rel: Optional[str]):
    if not rel:
        return
    try:
        os.remove(os.path.join(config.MEDIA_DIR, rel))
    except OSError:
        pass


@app.post("/api/incidents", response_model=IncidentCreated, status_code=201)
def create_incident(
    response: Response,
    request: Request,
    mission_id: int = Form(...),
    type: str = Form(...),
    severity: str = Form(...),
    x: float = Form(...),
    y: float = Form(...),
    area_pct: float = Form(0.0),
    people_count: int = Form(0),
    subtype: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Дрон сообщает о найденной ЧС (multipart/form-data, фото необязательно).

    Требуется ключ X-API-Key. Если рядом (MERGE_RADIUS_M) уже есть незакрытая
    ЧС того же типа в этой миссии, она обновляется (счётчик, степень, площадь,
    люди, фото), а не создаётся заново.
    """
    drone_auth(request)
    if db.get(Mission, mission_id) is None:
        raise HTTPException(404, "Миссия не найдена")
    try:
        inc_type = normalize_type(type)
        inc_sev = normalize_severity(severity)
    except ValueError as e:
        raise HTTPException(422, str(e))

    now = utcnow()
    candidates = db.scalars(
        select(Incident).where(
            Incident.mission_id == mission_id,
            Incident.type == inc_type,
            Incident.status != "closed",
        )
    ).all()
    near = [c for c in candidates if distance(c.x, c.y, x, y) <= config.MERGE_RADIUS_M]
    existing = min(near, key=lambda c: distance(c.x, c.y, x, y)) if near else None

    new_rel = _save_image(image) if image is not None and image.filename else None

    if existing is None:
        inc = Incident(
            mission_id=mission_id, type=inc_type, severity=inc_sev, x=x, y=y,
            area_pct=area_pct, people_count=max(people_count, 0), subtype=subtype,
            note=note, image_path=new_rel,
            first_seen=now, last_seen=now,
        )
        db.add(inc)
        db.commit()
        return IncidentCreated.model_validate(inc).model_copy(update={"merged": False})

    n = existing.detections
    existing.x = (existing.x * n + x) / (n + 1)   # уточняем положение (среднее по кадрам)
    existing.y = (existing.y * n + y) / (n + 1)
    existing.detections = n + 1
    existing.last_seen = now
    existing.severity = max_severity(existing.severity, inc_sev)
    existing.people_count = max(existing.people_count, people_count)
    if subtype and not existing.subtype:
        existing.subtype = subtype
    if new_rel is not None:
        if area_pct >= existing.area_pct or existing.image_path is None:
            _remove_image(existing.image_path)       # оставляем самый «крупный» кадр
            existing.image_path = new_rel
        else:
            _remove_image(new_rel)
    existing.area_pct = max(existing.area_pct, area_pct)
    if note:
        existing.note = note
    db.commit()
    response.status_code = 200
    return IncidentCreated.model_validate(existing).model_copy(update={"merged": True})


@app.get("/api/incidents", response_model=List[IncidentOut])
def list_incidents(
    mission_id: Optional[int] = None,
    type: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Список ЧС, доступный роли пользователя. Фильтры: mission_id, type, severity, status."""
    q = select(Incident)
    clause = visible_types_clause(user, Incident)
    if clause is not None:
        q = q.where(clause)
    try:
        if mission_id is not None:
            q = q.where(Incident.mission_id == mission_id)
        if type:
            inc_type = normalize_type(type)
            check_type_visible(user, inc_type)
            q = q.where(Incident.type == inc_type)
        if severity:
            q = q.where(Incident.severity == normalize_severity(severity))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if status:
        q = q.where(Incident.status == status)
    return db.scalars(q.order_by(Incident.last_seen.desc(), Incident.id.desc()).limit(limit)).all()


@app.get("/api/incidents/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, "ЧС не найдена")
    check_type_visible(user, inc.type)
    return inc


@app.patch("/api/incidents/{incident_id}", response_model=IncidentOut)
def patch_incident(incident_id: int, body: IncidentPatch,
                   user: dict = Depends(require_roles("operator")), db: Session = Depends(get_db)):
    """Оператор меняет статус (new / confirmed / closed) или добавляет заметку."""
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, "ЧС не найдена")
    if body.status is not None:
        inc.status = body.status
    if body.note is not None:
        inc.note = body.note
    db.commit()
    return inc


# ---------------------------------------------------------------- сводка
@app.get("/api/stats", response_model=StatsOut)
def stats(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """Сводка только по ЧС, доступным роли пользователя."""
    clause = visible_types_clause(user, Incident)
    base = select(Incident) if clause is None else select(Incident).where(clause)

    def grouped(col):
        q = select(col, func.count(Incident.id)).group_by(col)
        if clause is not None:
            q = q.where(clause)
        return {k: v for k, v in db.execute(q).all()}

    total_q = select(func.count(Incident.id))
    if clause is not None:
        total_q = total_q.where(clause)
    return StatsOut(
        total_incidents=db.scalar(total_q) or 0,
        by_type=grouped(Incident.type),
        by_severity=grouped(Incident.severity),
        by_status=grouped(Incident.status),
        active_missions=db.scalar(select(func.count(Mission.id)).where(Mission.status == "active")) or 0,
    )


# ---------------------------------------------------------------- панель мониторинга (React)
# ВАЖНО: монтирование — последним, после всех /api-маршрутов, иначе статика
# перехватит запросы к API. Если frontend/dist не собран, API работает сам по себе.
if os.path.isdir(config.FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
