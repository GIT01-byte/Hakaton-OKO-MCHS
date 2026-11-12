# config.py (Примерный вид, добавь недостающие константы, если их нет)

# --- Дрон ---
DRONE_NODE_NAME = "Mavic_2_PRO"  # Укажи имя своего нода
START_X = 0.0
START_Y = 0.0
START_Z = 0.5
FLIGHT_ALTITUDE = 8.0

# --- PID ---
K_VERTICAL_THRUST = 68.5
K_VERTICAL_OFFSET = 0.6
K_VERTICAL_P = 3.0
K_ROLL_P = 50.0
K_PITCH_P = 30.0

# --- Зрение ---
YOLO_H = 320
YOLO_W = 320
FRAME_SKIP = 2
YOLO_CONFIDENCE = 0.4
TELEMETRY_INTERVAL = 1.0

# --- Пороги (ВНИМАНИЕ: ОБНОВЛЕНО!) ---
CONTRAST_THRESHOLD = 0.0005  # Огонь теперь считается в долях площади (0.05% экрана)
LANDSLIDE_THRESHOLD = 0.15
LANDFILL_THRESHOLD = 0.20
