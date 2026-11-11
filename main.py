from controller import Supervisor
import cv2
import numpy as np
from ultralytics import YOLO
import math
import threading
import queue
import time
import csv

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
START_X = 118.0
START_Y = -16.0
START_Z = 2.0

FLIGHT_ALTITUDE = 20.0
MAX_FLOOD_ALTITUDE = 35.0

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

# 🔧 Параметры камеры
CAMERA_WIDTH = 400
CAMERA_HEIGHT = 240
YOLO_W, YOLO_H = 320, 192  # 5:3 пропорции

# 🔧 Пороги для детекции
WATER_THRESHOLD = 0.40
EDGE_WATER_THRESHOLD = 0.15
LANDSLIDE_THRESHOLD = 0.20

# Ручная скорость поворота камеры
CAMERA_PITCH_STEP = 0.05

# Отключаем многопоточность OpenCV, чтобы не конфликтовала с YOLO
cv2.setNumThreads(1)

# ==========================================
# 📊 ПРОФАЙЛЕР
# ==========================================
PROFILER_FILE = "performance_log.csv"
LOG_INTERVAL = 10
profiler_buffer = []
log_headers = [
    "Time_s",
    "Total_Loop_ms",
    "Webots_Step_ms",
    "Vision_ms",
    "Control_ms",
    "Mode",
    "Task",
]
with open(PROFILER_FILE, mode="w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerow(log_headers)

# ==========================================
# 🚁 ИНИЦИАЛИЗАЦИЯ WEBOTS
# ==========================================
print("Инициализация контроллера...")
supervisor = Supervisor()
timestep = int(supervisor.getBasicTimeStep())

imu = supervisor.getDevice("inertial unit")
imu.enable(timestep)
gps = supervisor.getDevice("gps")
gps.enable(timestep)
gyro = supervisor.getDevice("gyro")
gyro.enable(timestep)

camera = supervisor.getDevice("camera")
camera.enable(timestep)

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

# ==========================================
# 🧵 ОЧЕРЕДИ И ПОТОКИ
# ==========================================
frame_queue = queue.Queue(maxsize=1)
result_queue = queue.Queue(maxsize=1)
vis_queue = queue.Queue(maxsize=1)
key_queue = queue.Queue(maxsize=10)


def yolo_worker():
    model = YOLO("yolov8n.pt")
    while True:
        frame = frame_queue.get()
        if frame is None:
            break
        results = model(
            frame, conf=YOLO_CONFIDENCE, classes=[0], verbose=False, imgsz=320
        )
        detected = len(results[0].boxes) > 0
        boxes = [b.xyxy[0].tolist() for b in results[0].boxes]
        while True:
            try:
                result_queue.get_nowait()
            except queue.Empty:
                break
        result_queue.put((detected, boxes))


def visualization_worker():
    cv2.namedWindow("Oko MCHS", cv2.WINDOW_NORMAL)
    while True:
        try:
            frame = vis_queue.get(timeout=1.0)
            if frame is None:
                break
            cv2.imshow("Oko MCHS", frame)
            key = cv2.waitKey(1) & 0xFF
            if key != 255:
                try:
                    key_queue.put_nowait(key)
                except queue.Full:
                    pass
        except queue.Empty:
            pass


threading.Thread(target=yolo_worker, daemon=True).start()
threading.Thread(target=visualization_worker, daemon=True).start()


# ==========================================
# 🔍 ФУНКЦИИ ЗРЕНИЯ (С ЗАЩИТОЙ ОТ НЕБА)
# ==========================================
def detect_flood_and_edges(img, drone_pitch, camera_pitch):
    """
    Детектор наводнения с жесткой защитой от неба.
    drone_pitch: наклон дрона (от IMU)
    camera_pitch: наклон подвеса камеры (от -0.5 до 0.5)
    """
    # 1. Итоговый угол камеры в пространстве (приблизительно)
    total_pitch = drone_pitch + camera_pitch

    # 2. ЖЕСТКАЯ ЗАЩИТА: Если камера смотрит горизонтально или вверх (угол > -10 град / -0.17 рад)
    # Детектор воды полностью отключается, чтобы не поймать небо.
    if total_pitch > -0.17:
        return 0.0, []

    # 3. ДИНАМИЧЕСКАЯ МАСКА (отрезаем небо в зависимости от угла)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([90, 50, 50]), np.array([130, 255, 200]))
    h, w = mask.shape

    # Чем ближе к горизонту, тем больше верхней части кадра отрезаем
    if total_pitch < -0.5:
        sky_cut_ratio = 0.10  # Камера смотрит круто вниз, отрезаем 10% верха
    elif total_pitch < -0.3:
        sky_cut_ratio = 0.25  # Наклон средний, отрезаем 25%
    else:
        sky_cut_ratio = 0.45  # Смотрим почти прямо, отрезаем 45% (в основном небо)

    cut_y = int(h * sky_cut_ratio)
    mask[:cut_y, :] = 0

    # 4. Защита по яркости (небо всегда светлее воды)
    hsv_sky = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask_v_high = cv2.inRange(hsv_sky, np.array([0, 0, 200]), np.array([255, 255, 255]))
    mask = cv2.bitwise_and(mask, cv2.bitwise_not(mask_v_high))

    # 5. Считаем площадь
    valid_area = w * (h - cut_y)
    if valid_area <= 0:
        return 0.0, []
    ratio = cv2.countNonZero(mask) / valid_area

    # 6. Поиск краев (только в валидной зоне)
    edge_h, edge_w = h // 5, w // 5
    edges = []

    if cut_y < edge_h:  # Если верхний край не был отрезан
        if cv2.countNonZero(mask[0:edge_h, :]) > (edge_h * w * EDGE_WATER_THRESHOLD):
            edges.append("top")

    if cv2.countNonZero(mask[h - edge_h : h, :]) > (edge_h * w * EDGE_WATER_THRESHOLD):
        edges.append("bottom")
    if cv2.countNonZero(mask[:, 0:edge_w]) > (h * edge_w * EDGE_WATER_THRESHOLD):
        edges.append("left")
    if cv2.countNonZero(mask[:, w - edge_w : w]) > (h * edge_w * EDGE_WATER_THRESHOLD):
        edges.append("right")

    return ratio, edges


def detect_fire(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 150, 150]), np.array([10, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 150, 150]), np.array([180, 255, 255]))
    mask = cv2.bitwise_or(m1, m2)
    return (cv2.countNonZero(mask) / (img.shape[0] * img.shape[1])) > 0.15


def detect_landslide(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([10, 40, 40]), np.array([35, 180, 180]))
    return (
        cv2.countNonZero(mask) / (img.shape[0] * img.shape[1])
    ) > LANDSLIDE_THRESHOLD


def reset_drone():
    print("\n🔄 [RESET] Сброс дрона...")
    if drone_node is not None:
        fl.setVelocity(0)
        fr.setVelocity(0)
        rl.setVelocity(0)
        rr.setVelocity(0)
        drone_node.getField("translation").setSFVec3f([START_X, START_Y, START_Z])
        drone_node.getField("rotation").setSFRotation([0.0, 0.0, 1.0, 0.0])
        drone_node.setVelocity([0.0] * 6)
        drone_node.resetPhysics()
        print("✅ [RESET] Применён.")


# ==========================================
# 🗺️ ПЕРЕМЕННЫЕ
# ==========================================
waypoints = [
    (START_X + 30.0, START_Y),
    (START_X + 30.0, START_Y + 30.0),
    (START_X, START_Y + 30.0),
]
current_wp = 0
search_task = "FLOOD"
mode = "TAKEOFF"
target_altitude = FLIGHT_ALTITUDE

last_telemetry_time = 0.0
frame_count = 0
last_annotated = None
person_detected = False
yolo_boxes = []
smooth_pitch_disturbance = 0.0

is_water = False
current_wet_edges = []
current_water_ratio = 0.0
lost_water_frames = 0
flood_track_start_gps = None

# 🎥 Камера
camera_pitch_manual = 0.0
camera_pitch_base = 0.0

small_img_buffer = np.zeros((YOLO_H, YOLO_W, 3), dtype=np.uint8)

print(f"Система 'Око МЧС' запущена. Режим: {search_task}. Взлёт...")

# ==========================================
# 🔄 ГЛАВНЫЙ ЦИКЛ
# ==========================================
try:
    while True:
        t_loop_start = time.perf_counter()

        if supervisor.step(timestep) == -1:
            break
        t_step_end = time.perf_counter()

        current_time = supervisor.getTime()
        roll, pitch, yaw = imu.getRollPitchYaw()
        gps_x, gps_y, altitude = gps.getValues()
        roll_velocity = gyro.getValues()[0]
        pitch_velocity = gyro.getValues()[1]

        # --- Обработка клавиш ---
        while True:
            try:
                key = key_queue.get_nowait()
                if key == 27:  # ESC
                    raise SystemExit
                elif key == ord("r") or key == ord("к"):
                    reset_drone()
                    camera_pitch_manual = 0.0
                    mode = "TAKEOFF"
                    target_altitude = FLIGHT_ALTITUDE
                    smooth_pitch_disturbance = 0.0
                elif key == ord("1"):
                    search_task = "FLOOD"
                    print("🔄 Режим: ПОИСК НАВОДНЕНИЯ")
                elif key == ord("2"):
                    search_task = "FIRE"
                    print("🔄 Режим: ПОИСК ПОЖАРА")
                elif key == ord("3"):
                    search_task = "LANDSLIDE"
                    print("🔄 Режим: ПОИСК ОБВАЛА")
                elif key == ord("e") or key == ord("у"):
                    camera_pitch_manual = min(
                        0.5, camera_pitch_manual + CAMERA_PITCH_STEP
                    )
                    print(f"📷 Камера вверх: {math.degrees(camera_pitch_manual):.0f}°")
                elif key == ord("q") or key == ord("й"):
                    camera_pitch_manual = max(
                        -0.5, camera_pitch_manual - CAMERA_PITCH_STEP
                    )
                    print(f"📷 Камера вниз: {math.degrees(camera_pitch_manual):.0f}°")
            except queue.Empty:
                break

        # Автосброс
        if altitude < 0.5 and current_time > 3.0:
            reset_drone()
            mode = "TAKEOFF"
            target_altitude = FLIGHT_ALTITUDE
            smooth_pitch_disturbance = 0.0
            continue

        # Стабилизация камеры (roll)
        if camera_roll_motor:
            camera_roll_motor.setPosition(max(-0.5, min(0.5, -0.05 * roll_velocity)))

        if current_time - last_telemetry_time >= TELEMETRY_INTERVAL:
            print(
                f"[{current_time:.1f}s] X={gps_x:.1f}, Y={gps_y:.1f} | Z={altitude:.1f}м | {search_task}/{mode} | Cam:{math.degrees(camera_pitch_manual):.0f}°"
            )
            last_telemetry_time = current_time

        while True:
            try:
                person_detected, yolo_boxes = result_queue.get_nowait()
            except queue.Empty:
                break

        # --- ЗРЕНИЕ ---
        t_vision_start = time.perf_counter()
        if frame_count % FRAME_SKIP == 0:
            raw_image = camera.getImage()
            if raw_image:
                w, h = camera.getWidth(), camera.getHeight()
                image = np.frombuffer(raw_image, np.uint8).reshape((h, w, 4))
                bgr_image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

                cv2.resize(bgr_image, (YOLO_W, YOLO_H), dst=small_img_buffer)

                try:
                    frame_queue.put_nowait(small_img_buffer.copy())
                except queue.Full:
                    pass

                is_fire = detect_fire(small_img_buffer)
                is_landslide = detect_landslide(small_img_buffer)

                # ВЫЗОВ ДЕТЕКТОРА ВОДЫ С ЗАЩИТОЙ ОТ НЕБА
                current_total_pitch = pitch + camera_pitch_base + camera_pitch_manual
                current_water_ratio, current_wet_edges = detect_flood_and_edges(
                    small_img_buffer, pitch, camera_pitch_base + camera_pitch_manual
                )
                is_water = current_water_ratio > WATER_THRESHOLD

                last_annotated = bgr_image.copy()

                if person_detected:
                    sx, sy = w / YOLO_W, h / YOLO_H
                    for x1, y1, x2, y2 in yolo_boxes:
                        cv2.rectangle(
                            last_annotated,
                            (int(x1 * sx), int(y1 * sy)),
                            (int(x2 * sx), int(y2 * sy)),
                            (255, 0, 0),
                            2,
                        )

                cv2.putText(
                    last_annotated,
                    f"TASK: {search_task}",
                    (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                )

                # Вывод статуса защиты от неба
                if search_task == "FLOOD":
                    real_cam_angle = math.degrees(current_total_pitch)
                    if current_total_pitch > -0.17:
                        cv2.putText(
                            last_annotated,
                            f"WATER DETECT: OFF (Sky Protection, Cam: {real_cam_angle:.0f}deg)",
                            (20, 60),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (128, 128, 128),
                            2,
                        )
                    elif current_water_ratio > 0.05:
                        cv2.putText(
                            last_annotated,
                            f"WATER: {current_water_ratio*100:.1f}% | Edges: {len(current_wet_edges)} | Cam: {real_cam_angle:.0f}deg",
                            (20, 60),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 0, 0),
                            2,
                        )

                if search_task == "FIRE" and is_fire:
                    cv2.putText(
                        last_annotated,
                        "FIRE DETECTED",
                        (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 0, 255),
                        2,
                    )
                if search_task == "LANDSLIDE" and is_landslide:
                    cv2.putText(
                        last_annotated,
                        "LANDSLIDE DETECTED",
                        (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 165, 255),
                        2,
                    )

        frame_count += 1
        t_vision_end = time.perf_counter()

        # ==========================================
        # 🤖 FSM
        # ==========================================
        t_control_start = time.perf_counter()
        target_pitch_disturbance = 0.0
        yaw_disturbance = 0.0

        camera_pitch_base = 0.0  # Сбрасываем базу каждый кадр, FSM установит нужную

        if mode == "TAKEOFF":
            target_altitude = FLIGHT_ALTITUDE
            if altitude >= FLIGHT_ALTITUDE - 0.3:
                mode = "PATROL"

        elif mode == "PATROL":
            target_altitude = FLIGHT_ALTITUDE
            camera_pitch_base = 0.0

            target_x, target_y = waypoints[current_wp]
            if math.hypot(target_x - gps_x, target_y - gps_y) < 3.0:
                current_wp = (current_wp + 1) % len(waypoints)
            else:
                target_yaw = math.atan2(target_y - gps_y, target_x - gps_x)
                yaw_error = target_yaw - yaw
                if yaw_error > math.pi:
                    yaw_error -= 2 * math.pi
                elif yaw_error < -math.pi:
                    yaw_error += 2 * math.pi
                yaw_disturbance = max(-1.5, min(1.5, yaw_error * DRONE_TURN_SPEED))
                target_pitch_disturbance = (
                    DRONE_MAX_SPEED if abs(yaw_error) < 0.4 else DRONE_MAX_SPEED * 0.3
                )

            if search_task == "FLOOD" and is_water:
                print("\n[ALERT] Наводнение! Обход контура.")
                mode = "FLOOD_ASCEND"
                target_altitude = max(altitude, FLIGHT_ALTITUDE)
                flood_track_start_gps = (gps_x, gps_y)
            elif search_task == "FIRE" and is_fire:
                print("\n[ALERT] Пожар!")
                mode = "SCAN"
            elif search_task == "LANDSLIDE" and is_landslide:
                print("\n[ALERT] Обвал!")
                mode = "SCAN"
            elif person_detected:
                print("\n[ALERT] Человек!")
                mode = "SCAN"

        elif mode == "FLOOD_ASCEND":
            target_pitch_disturbance = 0.0
            yaw_disturbance = 0.0
            camera_pitch_base = -0.5
            target_altitude = min(MAX_FLOOD_ALTITUDE, target_altitude + 0.05)

            if (
                len(current_wet_edges) <= 2
                or target_altitude >= MAX_FLOOD_ALTITUDE - 0.1
            ):
                print("[FLOOD] Граница видна. Обход.")
                mode = "FLOOD_TRACK"
                lost_water_frames = 0

        elif mode == "FLOOD_TRACK":
            target_altitude = FLIGHT_ALTITUDE
            camera_pitch_base = -0.5

            if is_water:
                lost_water_frames = 0
                target_pitch_disturbance = DRONE_MAX_SPEED
                yaw_error = 0.0
                if "right" in current_wet_edges:
                    yaw_error += 0.5
                if "left" in current_wet_edges:
                    yaw_error -= 0.5
                if "top" in current_wet_edges:
                    yaw_error += 1.0
                if len(current_wet_edges) >= 3:
                    yaw_error = 1.5
                yaw_disturbance = max(-1.5, min(1.5, yaw_error))
            else:
                lost_water_frames += 1
                target_pitch_disturbance = 0.0
                yaw_disturbance = 0.8

            if flood_track_start_gps:
                dist_to_start = math.hypot(
                    flood_track_start_gps[0] - gps_x, flood_track_start_gps[1] - gps_y
                )
                if dist_to_start < 5.0 and lost_water_frames == 0:
                    print("\n[FLOOD] Контур замкнут.")
                    mode = "PATROL"

            if lost_water_frames > 50:
                print("\n[FLOOD] Потеряли цель.")
                mode = "PATROL"

        elif mode == "SCAN":
            target_altitude = FLIGHT_ALTITUDE
            camera_pitch_base = 0.0
            target_pitch_disturbance = 0.0
            yaw_disturbance = 0.0
            if current_time - last_telemetry_time > 3.0:
                mode = "PATROL"

        # --- Единая точка управления мотором камеры ---
        if camera_pitch_motor:
            final_pitch = camera_pitch_base + camera_pitch_manual - 0.1 * pitch_velocity
            camera_pitch_motor.setPosition(max(-0.5, min(0.5, final_pitch)))

        # --- Сглаживание и моторы дрона ---
        smooth_pitch_disturbance = (
            smooth_pitch_disturbance * 0.95 + target_pitch_disturbance * 0.05
        )
        pitch_disturbance = smooth_pitch_disturbance

        roll_input = K_ROLL_P * max(-1.0, min(1.0, roll)) + roll_velocity
        pitch_input = (
            K_PITCH_P * max(-1.0, min(1.0, pitch)) + pitch_velocity + pitch_disturbance
        )
        yaw_input = yaw_disturbance

        clamped_diff_alt = max(
            -1.0, min(1.0, target_altitude - altitude + K_VERTICAL_OFFSET)
        )
        vertical_input = K_VERTICAL_P * math.pow(clamped_diff_alt, 3.0)

        fl_in = (
            K_VERTICAL_THRUST + vertical_input - roll_input + pitch_input - yaw_input
        )
        fr_in = (
            K_VERTICAL_THRUST + vertical_input + roll_input + pitch_input + yaw_input
        )
        rl_in = (
            K_VERTICAL_THRUST + vertical_input - roll_input - pitch_input + yaw_input
        )
        rr_in = (
            K_VERTICAL_THRUST + vertical_input + roll_input - pitch_input - yaw_input
        )

        fl.setVelocity(max(0.0, fl_in))
        fr.setVelocity(-max(0.0, fr_in))
        rl.setVelocity(-max(0.0, rl_in))
        rr.setVelocity(max(0.0, rr_in))

        t_control_end = time.perf_counter()

        # --- Визуализация ---
        if last_annotated is not None:
            cv2.putText(
                last_annotated,
                f"Mode: {mode}",
                (20, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            cv2.putText(
                last_annotated,
                f"Alt: {altitude:.1f}m",
                (20, 150),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            cv2.putText(
                last_annotated,
                f"Cam: {math.degrees(camera_pitch_manual):+.0f}deg [E/Q]",
                (20, 180),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 0),
                2,
            )

            try:
                vis_queue.put_nowait(last_annotated)
            except queue.Full:
                pass

        # --- Профайлер ---
        t_loop_end = time.perf_counter()
        profiler_buffer.append(
            [
                f"{current_time:.3f}",
                f"{(t_loop_end - t_loop_start)*1000:.2f}",
                f"{(t_step_end - t_loop_start)*1000:.2f}",
                f"{(t_vision_end - t_vision_start)*1000:.2f}",
                f"{(t_control_end - t_control_start)*1000:.2f}",
                mode,
                search_task,
            ]
        )
        if len(profiler_buffer) >= LOG_INTERVAL:
            with open(PROFILER_FILE, mode="a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(profiler_buffer)
            profiler_buffer.clear()

except (KeyboardInterrupt, SystemExit):
    print("\nЗавершение работы...")

finally:
    if profiler_buffer:
        with open(PROFILER_FILE, mode="a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(profiler_buffer)
    try:
        vis_queue.put_nowait(None)
    except queue.Full:
        pass
    try:
        frame_queue.put_nowait(None)
    except queue.Full:
        pass
    time.sleep(0.2)
    cv2.destroyAllWindows()
    print(f"✅ Профайлер сохранён в {PROFILER_FILE}")
