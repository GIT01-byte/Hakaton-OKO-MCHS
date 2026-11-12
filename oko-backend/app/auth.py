"""Авторизация: ключ дрона (X-API-Key) и JWT пользователей (Bearer).

Дрон и его контроллер аутентифицируются ключом — у них нет сессий.
Люди входят через /api/login и получают JWT с ролью; роль ограничивает
и набор видимых типов ЧС, и допустимые действия.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .logic import ROLES, allowed_types
from .security import read_token

bearer = HTTPBearer(auto_error=False)


def drone_auth(request: Request):
    """Для эндпоинтов, которые вызывает контроллер дрона."""
    key = request.headers.get("X-API-Key", "")
    if key != config.DRONE_API_KEY:
        raise HTTPException(401, "Неверный или отсутствующий ключ дрона (X-API-Key)")


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> dict:
    """Для эндпоинтов панели мониторинга. Возвращает данные из JWT."""
    if creds is None:
        raise HTTPException(401, "Нужен токен: Authorization: Bearer <token> (вход через /api/login)")
    payload = read_token(creds.credentials)
    if payload is None:
        raise HTTPException(401, "Токен недействителен или просрочен")
    return payload


def require_roles(*roles: str):
    """Ограничить эндпоинт списком ролей."""
    def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Недостаточно прав (нужна роль: %s)" % "/".join(roles))
        return user
    return dep


def operator_or_drone(request: Request, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
    """Операция, которую может сделать и оператор (JWT), и сам контроллер дрона (ключ)."""
    key = request.headers.get("X-API-Key", "")
    if key == config.DRONE_API_KEY:
        return {"role": "drone", "sub": "0", "username": "drone"}
    if creds is not None:
        payload = read_token(creds.credentials)
        if payload is not None and payload["role"] == "operator":
            return payload
    raise HTTPException(401, "Нужен ключ дрона (X-API-Key) или токен оператора")


def visible_types_clause(user: dict, model):
    """Условие SQLAlchemy: только типы ЧС, разрешённые роли пользователя."""
    allowed = allowed_types(user["role"])
    if allowed is None:
        return None
    return model.type.in_(allowed) if allowed else model.type.in_([])


def check_type_visible(user: dict, inc_type: str):
    """403, если роли нельзя видеть этот тип ЧС."""
    allowed = allowed_types(user["role"])
    if allowed is not None and inc_type not in allowed:
        raise HTTPException(403, "Ваша роль («%s») не имеет доступа к типу ЧС «%s»" % (user["role"], inc_type))
