from controller import Supervisor
import cv2
import numpy as np
from ultralytics import YOLO
import math
import threading
import queue

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
START_X = 118.0
START_Y = -16.0
START_Z = 2.0

FLIGHT_ALTITUDE = 20.0
MAX_FLOOD_ALTITUDE = 50.0

DRONE_MAX_SPEED = -3.0
DRONE_TURN_SPEED = 1.5

K_VERTICAL_THRUST = 68.5
K_VERTICAL_OFFSET = 0.6
K_VERTICAL_P = 3.0
K_ROLL_P = 40.0
K_PITCH_P = 25.0

YOLO_CONFIDENCE = 0.5
FRAME_SKIP = 5
TELEMETRY_INTERVAL = 3.0
REPORT_INTERVAL = 3.0

FOV = 1.047
GRID_STEP = 15.0

# 🔧 Двойной порог + мультизамер
FLOOD_HIGH = 0.55          # точно вода → считаем площадь
FLOOD_LOW  = 0.30          # подозрительно → расширяем BFS
SETTLE_TIME = 0.8          # секунд висеть на клетке перед решением
REPORT_COOLDOWN = 15.0     # не начинать новую сессию сразу после отчёта
FLOOD_LOST_FRAMES_LIMIT = 5

# ==========================================
# 🚁 ИНИЦИАЛИЗАЦИЯ WEBOTS
# ==========================================
print("Инициализация контроллера...")
supervisor = Supervisor()
timestep = int(supervisor.getBasicTimeStep())

imu = supervisor.getDevice("inertial unit"); imu.enable(timestep)
gps = supervisor.getDevice("gps"); gps.enable(timestep)
gyro = supervisor.getDevice("gyro"); gyro.enable(timestep)
camera = supervisor.getDevice("camera"); camera.enable(timestep)

camera_roll_motor = supervisor.getDevice("camera roll")
camera_pitch_motor = supervisor.getDevice("camera pitch")

fl = supervisor.getDevice("front left propeller")
fr = supervisor.getDevice("front right propeller")
rl = supervisor.getDevice("rear left propeller")
rr = supervisor.getDevice("rear right propeller")

for m in [fl, fr, rl, rr]:
    m.setPosition(float("inf"))
    m.setVelocity(0.0)

drone_node = supervisor.getFromDef("DRONE")
if drone_node is None:
    print("❌ ОШИБКА: 'DRONE' не найден!")

# ==========================================
# 🧵 АСИНХРОННЫЙ YOLO
# ==========================================
frame_queue = queue.Queue(maxsize=1)
result_queue = queue.Queue(maxsize=1)

def yolo_worker():
    model = YOLO("yolov8n.pt")
    while True:
        frame = frame_queue.get()
        if frame is None:
            break
        results = model(frame, conf=YOLO_CONFIDENCE, classes=[0],
                        verbose=False, imgsz=320)
        detected = len(results[0].boxes) > 0
        boxes = [b.xyxy[0].tolist() for b in results[0].boxes]
        while True:
            try: result_queue.get_nowait()
            except queue.Empty: break
        result_queue.put((detected, boxes))

threading.Thread(target=yolo_worker, daemon=True).start()

# ==========================================
# 🔍 ДЕТЕКТОРЫ
# ==========================================
def detect_flood(img, pitch):
    if pitch < -0.15:
        return False, 0.0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([90, 50, 50]), np.array([130, 255, 200]))
    h, w = mask.shape
    mask[:h // 3, :] = 0
    valid = w * (h - h // 3)
    if valid <= 0:
        return False, 0.0
    ratio = cv2.countNonZero(mask) / valid
    return ratio > FLOOD_HIGH, ratio

def detect_fire(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 150, 150]), np.array([10, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 150, 150]), np.array([180, 255, 255]))
    mask = cv2.bitwise_or(m1, m2)
    ratio = cv2.countNonZero(mask) / (img.shape[0] * img.shape[1])
    return ratio > 0.15, ratio

def reset_drone():
    print("\n🔄 [RESET] Сброс дрона...")
    if drone_node is not None:
        fl.setVelocity(0); fr.setVelocity(0); rl.setVelocity(0); rr.setVelocity(0)
        drone_node.getField("translation").setSFVec3f([START_X, START_Y, START_Z])
        drone_node.getField("rotation").setSFRotation([0.0, 0.0, 1.0, 0.0])
        drone_node.setVelocity([0.0] * 6)
        drone_node.resetPhysics()
        if camera_pitch_motor: camera_pitch_motor.setPosition(0.0)
        if camera_roll_motor: camera_roll_motor.setPosition(0.0)
        while not frame_queue.empty():
            try: frame_queue.get_nowait()
            except queue.Empty: break
        while not result_queue.empty():
            try: result_queue.get_nowait()
            except queue.Empty: break
        print("✅ [RESET] Применён.")

def cell_of(x, y):
    return (round(x / GRID_STEP) * GRID_STEP,
            round(y / GRID_STEP) * GRID_STEP)

def clear_session():
    """Сбрасываем сессионное. flood_cells и cell_max_ratio сохраняем."""
    global mapping_active, map_target, current_map_cell, map_arrival_time
    global map_queue, queued_cells, visited_cells, sweep_queue
    mapping_active = False
    map_target = None
    current_map_cell = None
    map_arrival_time = 0.0
    map_queue = []
    queued_cells = set()
    visited_cells = set()
    sweep_queue = []

def populate_sweep():
    """Заполняет sweep_queue недостающими клетками внутри bbox flood_cells."""
    if not flood_cells:
        return 0
    xs = [c[0] for c in flood_cells]
    ys = [c[1] for c in flood_cells]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    sweep_set = set(sweep_queue)
    added = 0
    x = min_x
    while x <= max_x + 0.1:
        y = min_y
        while y <= max_y + 0.1:
            cell = (round(x / GRID_STEP) * GRID_STEP,
                    round(y / GRID_STEP) * GRID_STEP)
            if cell not in visited_cells and cell not in sweep_set:
                sweep_queue.append(cell)
                sweep_set.add(cell)
                added += 1
            y += GRID_STEP
        x += GRID_STEP
    return added

# ==========================================
# 🗺️ МАРШРУТ И ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ==========================================
waypoints = []
for i in range(10):
    x_off = 30.0 if i % 2 == 0 else 0.0
    waypoints.append((START_X + x_off, START_Y + i * 10.0))
default_waypoints = waypoints.copy()
current_wp = 0

mode = "TAKEOFF"
target_altitude = FLIGHT_ALTITUDE
last_telemetry_time = 0.0
last_report_time = 0.0
last_session_end_time = -1000.0
frame_count = 0

last_annotated = None
person_detected = False
yolo_boxes = []
is_fire = False
is_flood = False
alert_type = "NONE"
smooth_pitch_disturbance = 0.0

# Сессионные
mapping_active = False
map_target = None
current_map_cell = None
map_arrival_time = 0.0
map_queue = []
queued_cells = set()
visited_cells = set()
sweep_queue = []

# Глобальные (сохраняются между сессиями)
cell_max_ratio = {}
flood_cells = set()
flood_area_total = 0.0

flood_source_cell = None
flood_source_altitude = 0.0
flood_lost_frames = 0

print(f"Система 'Око МЧС' запущена. Взлёт на {FLIGHT_ALTITUDE} м...")

# ==========================================
# 🔄 ГЛАВНЫЙ ЦИКЛ
# ==========================================
while supervisor.step(timestep) != -1:
    current_time = supervisor.getTime()

    roll, pitch, yaw = imu.getRollPitchYaw()
    gps_x, gps_y, altitude = gps.getValues()
    roll_velocity = gyro.getValues()[0]
    pitch_velocity = gyro.getValues()[1]

    # --- Автосброс ---
    if altitude < 0.5 and current_time > 3.0:
        reset_drone()
        clear_session()
        mode = "TAKEOFF"
        target_altitude = FLIGHT_ALTITUDE
        smooth_pitch_disturbance = 0.0
        current_wp = 0
        flood_source_cell = None
        continue

    # --- Подвес камеры ---
    if camera_roll_motor:
        camera_roll_motor.setPosition(max(-0.5, min(0.5, -0.05 * roll_velocity)))
    if camera_pitch_motor:
        camera_pitch_motor.setPosition(max(-0.5, min(0.5, -0.05 * pitch_velocity)))

    # --- Телеметрия ---
    if current_time - last_telemetry_time >= TELEMETRY_INTERVAL:
        map_info = ""
        if mapping_active or len(flood_cells) > 0:
            map_info = (f" | MAP: {len(flood_cells)} кл., "
                        f"{flood_area_total:.0f} м², "
                        f"vis={len(visited_cells)}, "
                        f"q={len(map_queue)}, sw={len(sweep_queue)}")
        print(f"[ТЕЛЕМЕТРИЯ {current_time:.1f}s] "
              f"X={gps_x:.1f}, Y={gps_y:.1f} | "
              f"Z={altitude:.1f} м | {mode}{map_info}")
        last_telemetry_time = current_time

    # --- YOLO ---
    while True:
        try:
            person_detected, yolo_boxes = result_queue.get_nowait()
        except queue.Empty:
            break

    # --- Компьютерное зрение ---
    if frame_count % FRAME_SKIP == 0:
        raw_image = camera.getImage()
        if raw_image:
            image = np.frombuffer(raw_image, np.uint8).reshape(
                (camera.getHeight(), camera.getWidth(), 4))
            bgr_image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            small_img = cv2.resize(bgr_image, (320, 240))

            try:
                frame_queue.put_nowait(small_img.copy())
            except queue.Full:
                pass

            is_fire, fire_ratio = detect_fire(small_img)
            is_flood, blue_ratio = detect_flood(small_img, pitch)

            # Мультизамер: обновляем max ratio для клетки под дроном
            cur_cell = cell_of(gps_x, gps_y)
            prev = cell_max_ratio.get(cur_cell, 0.0)
            if blue_ratio > prev:
                cell_max_ratio[cur_cell] = blue_ratio

            # Аннотация
            last_annotated = bgr_image.copy()
            if person_detected:
                sx = last_annotated.shape[1] / 320.0
                sy = last_annotated.shape[0] / 240.0
                for x1, y1, x2, y2 in yolo_boxes:
                    cv2.rectangle(last_annotated,
                                  (int(x1 * sx), int(y1 * sy)),
                                  (int(x2 * sx), int(y2 * sy)),
                                  (255, 0, 0), 2)
            if is_fire:
                cv2.putText(last_annotated, f"FIRE: {fire_ratio*100:.1f}%",
                            (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            if blue_ratio > FLOOD_LOW:
                color = (0, 0, 255) if is_flood else (0, 165, 255)
                cv2.putText(last_annotated, f"WATER: {blue_ratio*100:.1f}%",
                            (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)

    frame_count += 1

    # ==========================================
    # 🤖 FSM
    # ==========================================
    target_pitch_disturbance = 0.0
    yaw_disturbance = 0.0

    # ---------- 1. ВЗЛЁТ ----------
    if mode == "TAKEOFF":
        target_altitude = FLIGHT_ALTITUDE
        if altitude >= FLIGHT_ALTITUDE - 0.3:
            print(f"✅ Взлёт завершён. Высота: {altitude:.1f} м.")
            mode = "PATROL"

    # ---------- 2. ПАТРУЛИРОВАНИЕ ----------
    elif mode == "PATROL":
        target_altitude = FLIGHT_ALTITUDE

        if mapping_active and map_target is not None:
            target_x, target_y = map_target
        else:
            target_x, target_y = waypoints[current_wp]

        distance = math.sqrt((target_x - gps_x)**2 + (target_y - gps_y)**2)

        if distance < 3.0:
            if mapping_active and map_target is not None:
                current_map_cell = map_target
                map_arrival_time = current_time
                mode = "MEASURING"
            else:
                current_wp = (current_wp + 1) % len(waypoints)
                print(f"[NAV] Точка достигнута. Следующая: {waypoints[current_wp]}")
        else:
            target_yaw = math.atan2(target_y - gps_y, target_x - gps_x)
            yaw_error = target_yaw - yaw
            if yaw_error > math.pi: yaw_error -= 2 * math.pi
            elif yaw_error < -math.pi: yaw_error += 2 * math.pi
            yaw_disturbance = max(-1.5, min(1.5, yaw_error * DRONE_TURN_SPEED))
            if abs(yaw_error) < 0.4:
                target_pitch_disturbance = DRONE_MAX_SPEED
            else:
                target_pitch_disturbance = DRONE_MAX_SPEED * 0.3

        # Триггер алертов только вне картирования и с кулдауном
        if (not mapping_active
                and current_time - last_session_end_time > REPORT_COOLDOWN):
            if is_flood:
                alert_type = "FLOOD"
                flood_source_cell = cell_of(gps_x, gps_y)
                flood_source_altitude = altitude
                flood_lost_frames = 0
                print(f"\n[ALERT] Наводнение. Источник: {flood_source_cell}")
                mode = "FLOOD_ASCEND"
                target_altitude = max(altitude, FLIGHT_ALTITUDE)
            elif person_detected or is_fire:
                alert_type = "PERSON" if person_detected else "FIRE"
                print(f"\n[ALERT] Обнаружено: {alert_type}.")
                mode = "SCAN"

    # ---------- 3. ПОДЪЁМ ПРИ НАВОДНЕНИИ ----------
    elif mode == "FLOOD_ASCEND":
        target_pitch_disturbance = 0.0
        yaw_disturbance = 0.0
        target_altitude = min(MAX_FLOOD_ALTITUDE, target_altitude + 0.05)

        if is_flood:
            flood_lost_frames = 0
        else:
            flood_lost_frames += 1

        reached_top = target_altitude >= MAX_FLOOD_ALTITUDE - 0.1
        lost_flood = flood_lost_frames > FLOOD_LOST_FRAMES_LIMIT

        if reached_top or lost_flood:
            print(f"[FLOOD] Берег найден или достигнут предел. Seed + BFS.")
            clear_session()

            seed = flood_source_cell if flood_source_cell else cell_of(gps_x, gps_y)
            seed_alt = flood_source_altitude if flood_source_altitude > 0 else altitude

            if seed not in flood_cells:
                flood_cells.add(seed)
                fw = 2.0 * seed_alt * math.tan(FOV / 2.0)
                flood_area_total += fw ** 2
                print(f"[SEED] {seed} добавлен в flood_cells, "
                      f"площадь кадра {fw**2:.1f} м²")

            if flood_cells:
                # Все известные водные клетки → visited, neighbors → queue
                for fc in list(flood_cells):
                    visited_cells.add(fc)
                    for dx, dy in [(GRID_STEP, 0), (-GRID_STEP, 0),
                                   (0, GRID_STEP), (0, -GRID_STEP)]:
                        n = (fc[0] + dx, fc[1] + dy)
                        if n not in visited_cells and n not in queued_cells:
                            map_queue.append(n)
                            queued_cells.add(n)
            else:
                visited_cells.add(seed)
                for dx, dy in [(GRID_STEP, 0), (-GRID_STEP, 0),
                               (0, GRID_STEP), (0, -GRID_STEP)]:
                    n = (seed[0] + dx, seed[1] + dy)
                    if n not in visited_cells and n not in queued_cells:
                        map_queue.append(n)
                        queued_cells.add(n)

            mapping_active = True
            target_altitude = FLIGHT_ALTITUDE

            if map_queue:
                # 🔧 Сортировка по расстоянию (перенесено из Кода 2)
                map_queue.sort(key=lambda p: math.hypot(p[0] - gps_x, p[1] - gps_y))
                map_target = map_queue.pop(0)
                queued_cells.discard(map_target)
                print(f"[BFS] Старт. Очередь: {len(map_queue)}, "
                      f"цель: {map_target}")
                mode = "PATROL"
            else:
                print("[BFS] Очередь пуста — сразу к bbox sweep.")
                mode = "BBOX_SWEEP"

    # ---------- 4. ЗАМЕР НА КЛЕТКЕ ----------
    elif mode == "MEASURING":
        target_altitude = FLIGHT_ALTITUDE
        target_pitch_disturbance = 0.0
        yaw_disturbance = 0.0
        if current_time - map_arrival_time >= SETTLE_TIME:
            mode = "MAP_DECIDE"

    # ---------- 5. РЕШЕНИЕ ПО КЛЕТКЕ ----------
    elif mode == "MAP_DECIDE":
        target_altitude = FLIGHT_ALTITUDE
        target_pitch_disturbance = 0.0
        yaw_disturbance = 0.0

        cell = current_map_cell if current_map_cell else cell_of(gps_x, gps_y)
        ratio_here = cell_max_ratio.get(cell, 0.0)

        visited_cells.add(cell)

        is_definite = ratio_here > FLOOD_HIGH
        is_probable = ratio_here > FLOOD_LOW

        if is_definite and cell not in flood_cells:
            flood_cells.add(cell)
            fw = 2.0 * altitude * math.tan(FOV / 2.0)
            flood_area_total += fw ** 2

        if is_probable:
            for dx, dy in [(GRID_STEP, 0), (-GRID_STEP, 0),
                           (0, GRID_STEP), (0, -GRID_STEP)]:
                n = (cell[0] + dx, cell[1] + dy)
                if n not in visited_cells and n not in queued_cells:
                    map_queue.append(n)
                    queued_cells.add(n)

        print(f"[DECIDE] {cell}: ratio={ratio_here:.3f} "
              f"definite={is_definite} probable={is_probable} "
              f"queue={len(map_queue)}")

        # 🔧 Сортировка по расстоянию
        if map_queue:
            map_queue.sort(key=lambda p: math.hypot(p[0] - gps_x, p[1] - gps_y))
            map_target = map_queue.pop(0)
            queued_cells.discard(map_target)
            mode = "PATROL"
        elif sweep_queue:
            sweep_queue.sort(key=lambda p: math.hypot(p[0] - gps_x, p[1] - gps_y))
            map_target = sweep_queue.pop(0)
            mode = "PATROL"
        else:
            mode = "BBOX_SWEEP"

    # ---------- 6. BBOX SWEEP ----------
    elif mode == "BBOX_SWEEP":
        target_altitude = FLIGHT_ALTITUDE
        target_pitch_disturbance = 0.0
        yaw_disturbance = 0.0

        added = populate_sweep()
        print(f"[BBOX] Заполнено {added} клеток для sweep.")

        if sweep_queue:
            sweep_queue.sort(key=lambda p: math.hypot(p[0] - gps_x, p[1] - gps_y))
            map_target = sweep_queue.pop(0)
            mode = "PATROL"
        else:
            mode = "FINAL_REPORT"

    # ---------- 7. ФИНАЛЬНЫЙ ОТЧЁТ ----------
    elif mode == "FINAL_REPORT":
        target_altitude = FLIGHT_ALTITUDE
        target_pitch_disturbance = 0.0
        yaw_disturbance = 0.0

        print("\n=== ФИНАЛЬНЫЙ ОТЧЁТ ПО НАВОДНЕНИЮ ===")
        print(f"Всего посещено клеток: {len(visited_cells)}")
        print(f"Затопленных клеток: {len(flood_cells)}")
        print(f"Общая площадь: {flood_area_total:.1f} м²")

        if flood_cells:
            xs = [c[0] for c in flood_cells]
            ys = [c[1] for c in flood_cells]
            print(f"BBox: X=[{min(xs):.0f}..{max(xs):.0f}], "
                  f"Y=[{min(ys):.0f}..{max(ys):.0f}]")
            print("Координаты клеток:")
            for c in sorted(flood_cells):
                r = cell_max_ratio.get(c, 0.0)
                print(f"  {c}  ratio={r:.3f}")
        print("=====================================\n")

        clear_session()
        waypoints = default_waypoints.copy()
        current_wp = 0
        last_report_time = current_time
        last_session_end_time = current_time
        mode = "COOLDOWN"

    # ---------- 8. СКАНИРОВАНИЕ ----------
    elif mode == "SCAN":
        target_altitude = FLIGHT_ALTITUDE
        target_pitch_disturbance = 0.0
        yaw_disturbance = 0.0
        if current_time - last_report_time > REPORT_INTERVAL:
            filename = f"alert_{alert_type}_{int(current_time)}.jpg"
            if last_annotated is not None:
                cv2.imwrite(filename, last_annotated)
            print(f"🚨 [ШТАБ] {alert_type} | X={gps_x:.1f}, Y={gps_y:.1f}")
            mode = "COOLDOWN"
            last_report_time = current_time

    # ---------- 9. ПАУЗА ----------
    elif mode == "COOLDOWN":
        target_altitude = FLIGHT_ALTITUDE
        target_pitch_disturbance = 0.0
        yaw_disturbance = 0.0
        if current_time - last_report_time > 5.0:
            mode = "PATROL"

    # --- Сглаживание ---
    smooth_pitch_disturbance = (
        smooth_pitch_disturbance * 0.95 + target_pitch_disturbance * 0.05)
    pitch_disturbance = smooth_pitch_disturbance

    # ==========================================
    # ⚙️ PID И МОТОРЫ
    # ==========================================
    roll_input = K_ROLL_P * max(-1.0, min(1.0, roll)) + roll_velocity
    pitch_input = (K_PITCH_P * max(-1.0, min(1.0, pitch))
                   + pitch_velocity + pitch_disturbance)
    yaw_input = yaw_disturbance

    clamped_diff_alt = max(-1.0,
                           min(1.0, target_altitude - altitude + K_VERTICAL_OFFSET))
    vertical_input = K_VERTICAL_P * math.pow(clamped_diff_alt, 3.0)

    fl_in = K_VERTICAL_THRUST + vertical_input - roll_input + pitch_input - yaw_input
    fr_in = K_VERTICAL_THRUST + vertical_input + roll_input + pitch_input + yaw_input
    rl_in = K_VERTICAL_THRUST + vertical_input - roll_input - pitch_input + yaw_input
    rr_in = K_VERTICAL_THRUST + vertical_input + roll_input - pitch_input - yaw_input

    fl.setVelocity(max(0.0, fl_in))
    fr.setVelocity(-max(0.0, fr_in))
    rl.setVelocity(-max(0.0, rl_in))
    rr.setVelocity(max(0.0, rr_in))

    # ==========================================
    # 📺 ВИЗУАЛИЗАЦИЯ
    # ==========================================
    if last_annotated is not None:
        cv2.putText(last_annotated, f"Mode: {mode}", (20, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(last_annotated,
                    f"Alt: {altitude:.1f}m / Tgt: {target_altitude:.1f}m",
                    (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        if mapping_active or flood_cells:
            cv2.putText(last_annotated,
                        f"MAP: {len(flood_cells)}c {flood_area_total:.0f}m2",
                        (20, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (0, 255, 255), 2)

        cv2.imshow("Oko MCHS", last_annotated)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == ord("й"):
            break
        elif key == ord("r") or key == ord("к"):
            reset_drone()
            clear_session()
            flood_cells.clear()
            cell_max_ratio.clear()
            flood_area_total = 0.0
            flood_source_cell = None
            flood_source_altitude = 0.0
            mode = "TAKEOFF"
            target_altitude = FLIGHT_ALTITUDE
            smooth_pitch_disturbance = 0.0
            current_wp = 0

try:
    frame_queue.put_nowait(None)
except queue.Full:
    pass
cv2.destroyAllWindows()