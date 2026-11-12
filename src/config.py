# config.py
import math

TELEMETRY_INTERVAL = 0.5  # --- Стартовые координаты ---
START_X = 0
START_Y = 0
START_Z = 0
DRONE_NODE_NAME = "DRONE"

# --- Высота и скорости ---
FLIGHT_ALTITUDE = 15.0
MAX_FLOOD_ALTITUDE = 40.0
FOV = 1.047  # 60 градусов (горизонтальный угол обзора камеры)
DRONE_MAX_SPEED = -3.0
DRONE_TURN_SPEED = 1.5

# --- PID коэффициенты ---
K_VERTICAL_THRUST = 68.5
K_VERTICAL_OFFSET = 0.6
K_VERTICAL_P = 3.0
K_ROLL_P = 40.0
K_PITCH_P = 25.0

# --- ИИ и оптимизация ---
YOLO_CONFIDENCE = 0.5
FRAME_SKIP = 5
TELEMETRY_INTERVAL = 10.0  # Телеметрия раз в 10 секунд

# --- Камера ---
YOLO_W, YOLO_H = 320, 192  # буфер классических детекторов (вода/оползень/свалка)
YOLO_DET_W, YOLO_DET_H = (
    1280,
    768,
)  # кадр для нейросети = нативное разрешение камеры (см. mavic_2_pro.wbt)
YOLO_IMGSZ = 1280  # инференс издали: пламя/человек различимы и на 100+ м
YOLO_IMGSZ_CLOSE = 640  # инференс вблизи (объекты крупные) - быстрее
YOLO_CLOSE_ALT = 10.0  # ниже этой высоты (м) используется YOLO_IMGSZ_CLOSE
VIS_FPS_LIMIT = 20.0  # лимит FPS окна визуализации (экономит CPU)
CAMERA_PITCH_NADIR = 0.5

# --- Пороги детекции ---
WATER_TRIGGER_RATIO = 0.10
WATER_FULL_SCREEN_RATIO = 0.85
CONTRAST_THRESHOLD = (
    0.0002  # огонь: доля кадра (при 1280x768 пламя со 100 м ~0.03% кадра)
)
LANDSLIDE_THRESHOLD = 0.20  # доля кадра, занятая САМЫМ БОЛЬШИМ пятном грунта
LANDFILL_THRESHOLD = 0.15  # доля "захламлённых" ячеек сетки

FIRE_CONFIRM = (3, 5)  # огонь подтверждён: 3 кадра из последних 5
FIRE_MODEL_PATH = None  # дообученная YOLO (fire/smoke), напр. "fire_smoke.pt"

# --- Пожар: ступенчатый осмотр после подтверждения ---
FIRE_CAM_STEP_RAD = math.radians(3.0)  # шаг 1: камера вниз на 3°, далее по 3° за шаг
FIRE_STEP_TIME = 2.0  # длительность одного шага, сек
FIRE_MAX_STEPS = 9  # предельный наклон -27° (физический лимит камеры -0.5 рад)
FIRE_MAX_FRAMES = 6  # максимум дополнительных кадров-доказательств
FIRE_GROWTH_EPS = 0.002  # мин. прирост доли кадра, чтобы считать "пожара стало больше"

# --- Пожар: подлёт по сохранённому направлению ---
FIRE_APPROACH_STOP_DIST = (
    8.0  # м: ближе - очаг достигнут, переходим к ступенчатому осмотру
)

# --- Вода: разведка обстановки перед сближением ---
# Сектора осмотра (рад относительно курса в момент обнаружения): центр, влево/вправо на 40° и 80°
FLOOD_ASSESS_YAW_OFFSETS = (0.0, -0.7, 0.7, -1.4, 1.4)
FLOOD_ASSESS_TURN_TIME = 1.0  # с на доворот к сектору
FLOOD_ASSESS_DWELL = 1.2  # с наблюдения в секторе (накопление доли воды)
FLOOD_ASSESS_TIMEOUT = 15.0  # с предельное время разведки (страховка от зависания)

# --- Вода: мутное наводнение (коричневая гладкая вода). Включайте, если вода в сцене не синяя ---
ENABLE_MUDDY_WATER = False
WATER_TEXTURE_VAR = 40.0

# --- Люди и животные (классы COCO) ---
COCO_PERSON = 0
COCO_ANIMALS = {
    14: "bird",
    15: "cat",
    16: "dog",
    17: "horse",
    18: "sheep",
    19: "cow",
    20: "elephant",
    21: "bear",
    22: "zebra",
    23: "giraffe",
}
COCO_TRASH = {
    24: "backpack",
    26: "handbag",
    28: "suitcase",
    39: "bottle",
    41: "cup",
    45: "bowl",
}
PERSON_CONF = (
    0.30  # низкий порог: цель мелкая, надёжность даёт подтверждение по времени
)
ANIMAL_CONF = 0.30
PERSON_MAX_BOX_AREA = 0.15
PERSON_CONFIRM_FRAMES = 3
PERSON_WINDOW = 5
PERSON_CLUSTER_RADIUS = 6.0  # м
PERSON_FINAL_CONF = YOLO_CONFIDENCE  # уверенность при повторной проверке с малой высоты
PERSON_CHECK_ALT = 8.0
PERSON_LOST_TIMEOUT = 5.0
PERSON_CONFIRM_TIMEOUT = 30.0
PERSON_IGNORE_RADIUS = 10.0
TRASH_OBJECTS_FOR_LANDFILL = 3

# --- Объезд препятствий ---
# Имена устройств в .wbt. Если их нет - работает только зрение (оптический поток).
DIST_SENSORS = {"left": "ds_left", "center": "ds_front", "right": "ds_right"}
LIDAR_NAME = "lidar"  # None, если лидара нет
LIDAR_FLIP = False
RANGE_MAX = 30.0
DIST_DANGER = 7.0
DIST_WARN = 14.0
TAU_DANGER = 2.5  # с до столкновения (по зрению)
TAU_WARN = 5.0
LOOM_MIN_RATE = 0.12
LOOM_TEXTURE = 18.0
AVOID_MAX_CAM_PITCH = 0.35
AVOID_CLIMB_STEP = 5.0
OBSTACLE_MAX_ALT = 40.0
AVOID_BRAKE_TIME = 1.5
AVOID_BRAKE_PITCH = 1.5
AVOID_CLEAR_CONFIRM = 1.0
AVOID_PASS_HOLD = 8.0
AVOID_YAW_BIAS = 0.6

# --- Патрулирование (сетка 100х100) ---
GRID_SIZE = 100.0
MAX_EMPTY_SQUARES = 3
APPROACH_TIME = 2.5
FLOOD_CENTERING_TIMEOUT = 25.0

# --- Поводок: защита от улёта за ложными целями (серые скалы и т.п.) ---
# Если точка ЧС дальше этого расстояния от ближайшей точки маршрута - миссия не стартует;
# если дрон в миссии превысил его - миссия прерывается, дрон возвращается к патрулю.
MAX_CHASE_DISTANCE = 80.0

# --- Параметры 360° сканирования ---
SCAN_ROTATION_SPEED = 0.8  # Скорость вращения дрона (рад/с)
SCAN_CAM_AMPLITUDE = 0.4  # Амплитуда кивания камеры (рад)
SCAN_TIMEOUT = 12.0  # Максимальное время сканирования (сек)

# --- Батарея (виртуальная модель) ---
BATTERY_FLIGHT_TIME = 20 * 60.0
BATTERY_RESERVE = 60.0
CRUISE_SPEED_EST = 3.0
CLIMB_SPEED_EST = 1.5

# --- Профилирование (замер производительности) ---
PROFILING_ENABLED = (
    True  # включить/выключить замеры (отчёты в консоль с префиксом [PROFILER])
)
PROFILING_REPORT_INTERVAL = (
    30.0  # период вывода отчёта, сек (0 - только итоговый отчёт при завершении)
)

# --- Отчёты ---
HQ_URL = None  # напр. "http://192.168.0.10:8000/api/incident"
DEDUP_RADIUS = {
    "PERSON": 15.0,
    "FIRE": 40.0,
    "FLOOD": 80.0,
    "LANDSLIDE": 60.0,
    "LANDFILL": 40.0,
}
