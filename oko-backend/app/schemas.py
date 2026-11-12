from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from .logic import to_utc_iso

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
    time: Optional[datetime] = None

    # ── НОВОЕ: обогащение от дрона (logger.py) ──
    water_pct: Optional[float] = Field(default=0.0, ge=0, le=100)
    fire_score: Optional[float] = Field(default=0.0, ge=0, le=1)
    avoid: Optional[str] = None
    persons: Optional[int] = Field(default=0, ge=0)


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

    # ── НОВОЕ ──
    water_pct: Optional[float] = None
    fire_score: Optional[float] = None
    avoid: Optional[str] = None
    persons: Optional[int] = None


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
    merged: bool = False


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
    allowed_types: Optional[list] = None


class LoginOut(BaseModel):
    token: str
    user: UserOut


class StatsOut(BaseModel):
    total_incidents: int
    by_type: dict
    by_severity: dict
    by_status: dict
    active_missions: int
