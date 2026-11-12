from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from .logic import to_utc_iso

# Время всегда отдаём в UTC с явным указанием пояса: 2026-11-11T09:30:00+00:00
UtcDT = Annotated[datetime, PlainSerializer(to_utc_iso, return_type=str)]

IncidentStatus = Literal["new", "confirmed", "closed"]
Role = Literal["operator", "firefighter", "ecologist", "viewer"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DroneOut(ORM):
    id: int
    name: str
    model: str


class MissionCreate(BaseModel):
    drone_id: int


class MissionOut(ORM):
    id: int
    drone_id: int
    started_at: UtcDT
    finished_at: Optional[UtcDT] = None
    status: str


class TelemetryIn(BaseModel):
    mission_id: int
    x: float
    y: float
    z: float = 0.0
    yaw: Optional[float] = None
    battery: Optional[float] = Field(default=None, ge=0, le=100)
    state: Optional[str] = None
    time: Optional[datetime] = None  # если не указано, ставится время сервера


class TelemetryOut(ORM):
    id: int
    mission_id: int
    time: UtcDT
    x: float
    y: float
    z: float
    lat: float
    lon: float
    yaw: Optional[float] = None
    battery: Optional[float] = None
    state: Optional[str] = None


class IncidentOut(ORM):
    id: int
    mission_id: int
    type: str
    severity: str
    status: str
    x: float
    y: float
    lat: float
    lon: float
    area_pct: float
    detections: int
    people_count: int
    subtype: Optional[str] = None
    first_seen: UtcDT
    last_seen: UtcDT
    image_url: Optional[str] = None
    note: Optional[str] = None


class IncidentCreated(IncidentOut):
    merged: bool = False  # True, если обновлён уже известный очаг, а не создан новый


class IncidentPatch(BaseModel):
    status: Optional[IncidentStatus] = None
    note: Optional[str] = None


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    display_name: str
    allowed_types: Optional[list] = None  # None = все типы ЧС


class LoginOut(BaseModel):
    token: str
    user: UserOut


class StatsOut(BaseModel):
    total_incidents: int
    by_type: dict
    by_severity: dict
    by_status: dict
    active_missions: int
