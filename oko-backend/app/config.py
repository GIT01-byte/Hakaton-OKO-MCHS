import os

# База данных: по умолчанию SQLite-файл (для быстрого запуска без Docker).
# В docker-compose подставляется PostgreSQL.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./oko.db")

# Папка для фотографий (отдаётся по адресу /media/...)
MEDIA_DIR = os.getenv("MEDIA_DIR", "media")

# Собранная React-панель (frontend/dist). Если папка есть, отдаётся на /.
FRONTEND_DIR = os.getenv(
    "FRONTEND_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist"),
)

# Базовая точка карты: метры симулятора (0, 0) соответствуют этим координатам.
BASE_LAT = float(os.getenv("BASE_LAT", "56.8389"))
BASE_LON = float(os.getenv("BASE_LON", "60.6057"))

# Если новая ЧС того же типа ближе этого расстояния (м) к уже известной
# в той же миссии, она считается тем же очагом и не создаёт дубль.
MERGE_RADIUS_M = float(os.getenv("MERGE_RADIUS_M", "4.0"))

MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# --- авторизация ---
# Ключ дрона: контроллер (Webots/fake_drone) шлёт его в заголовке X-API-Key.
DRONE_API_KEY = os.getenv("DRONE_API_KEY", "oko-drone-key")
# Секрет для подписи JWT-токенов пользователей. В проде задать через переменную окружения!
SECRET_KEY = os.getenv("SECRET_KEY", "oko-dev-secret-change-me")
TOKEN_TTL_HOURS = float(os.getenv("TOKEN_TTL_HOURS", "12"))
