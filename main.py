from controller import Supervisor
import cv2
import numpy as np
from ultralytics import YOLO
import math

# ==========================================
# ⚙️ БЛОК НАСТРОЕК (УПРАВЛЯЙ ВСЕМ ЗДЕСЬ)
# ==========================================

# --- Скорость и высота ---
DRONE_MAX_SPEED = -3.0  # Наклон вперед (-2.0 медленно, -5.0 быстро)
DRONE_TURN_SPEED = 1.5  # Скорость поворота
FLIGHT_ALTITUDE = 20.0  # 🎯 РАБОЧАЯ ВЫСОТА ПАТРУЛИРОВАНИЯ (меняй здесь)


#
START_X = 118.0  # Высота, на которую сбрасывается дрон при падении
START_Y = -16.0  # Высота, на которую сбрасывается дрон при падении
START_Z = 20.0  # Высота, на которую сбрасывается дрон при падении

# --- Коэффициенты PID ---
K_VERTICAL_THRUST = 68.5
K_VERTICAL_OFFSET = 0.6
K_VERTICAL_P = 3.0
K_ROLL_P = 40.0
K_PITCH_P = 25.0

# --- Настройки ИИ и оптимизации ---
YOLO_CONFIDENCE = 0.5
FRAME_SKIP = 5
TELEMETRY_INTERVAL = 3.0
REPORT_INTERVAL = 3.0

# ==========================================
# 🚁 ИНИЦИАЛИЗАЦИЯ
# ==========================================
print("Инициализация...")
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
if drone_node is None:
    print("❌ ОШИБКА: Дрон с именем 'DRONE' не найден!")

model = YOLO("yolov8n.pt")


# ==========================================
# 🧠 ФУНКЦИИ
# ==========================================
def detect_flood(img, pitch):
    if pitch < -0.15:
        return False, 0.0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([90, 50, 50]), np.array([130, 255, 255]))
    ratio = cv2.countNonZero(mask) / (img.shape[0] * img.shape[1])
    return ratio > 0.6, ratio


def detect_fire(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 150, 150]), np.array([35, 255, 255]))
    ratio = cv2.countNonZero(mask) / (img.shape[0] * img.shape[1])
    return ratio > 0.15, ratio


def reset_drone():
    print("\n🔄 [RESET] Сброс дрона...")
    if drone_node:
        fl.setVelocity(0)
        fr.setVelocity(0)
        rl.setVelocity(0)
        rr.setVelocity(0)
        drone_node.getField("translation").setSFVec3f([START_X, START_Y, START_Z])
        drone_node.getField("rotation").setSFRotation([0.0, 0.0, 1.0, 0.0])
        drone_node.setVelocity([0.0] * 6)
        drone_node.resetPhysics()
        if camera_pitch_motor:
            camera_pitch_motor.setPosition(0.0)
        if camera_roll_motor:
            camera_roll_motor.setPosition(0.0)
        supervisor.step(timestep)
        print("✅ [RESET] Применен.")


# ==========================================
# 🗺️ ПЕРЕМЕННЫЕ И РЕЖИМЫ
# ==========================================
waypoints = []
y = 0
for i in range(10):
    if i % 2 == 0:
        waypoints.append((30.0, y))
    else:
        waypoints.append((0.0, y))
    y += 10.0
current_wp = 0

# Начинаем с режима ВЗЛЕТА
mode = "TAKEOFF"
target_altitude = FLIGHT_ALTITUDE

last_telemetry_time = 0.0
last_report_time = 0.0
frame_count = 0
last_annotated = None
person_detected, is_fire, is_flood = False, False, False
alert_type = "NONE"
smooth_pitch_disturbance = 0.0

print(f"Система 'Око МЧС' запущена. Взлетаем на {FLIGHT_ALTITUDE} метров...")

# ==========================================
# 🔄 ГЛАВНЫЙ ЦИКЛ
# ==========================================
while supervisor.step(timestep) != -1:
    current_time = supervisor.getTime()

    roll, pitch, yaw = imu.getRollPitchYaw()
    gps_x, gps_y, altitude = gps.getValues()
    roll_velocity, pitch_velocity = gyro.getValues()[0], gyro.getValues()[1]

    # Автосброс при падении
    if altitude < 0.5 and current_time > 3.0:
        reset_drone()
        target_altitude = FLIGHT_ALTITUDE
        mode = "TAKEOFF"  # После сброса снова взлетаем!
        smooth_pitch_disturbance = 0.0
        continue

    # Камера
    if camera_roll_motor:
        camera_roll_motor.setPosition(max(-0.5, min(0.5, -0.05 * roll_velocity)))
    if camera_pitch_motor:
        camera_pitch_motor.setPosition(max(-0.5, min(0.5, -0.05 * pitch_velocity)))

    # Телеметрия
    if current_time - last_telemetry_time >= TELEMETRY_INTERVAL:
        print(
            f"[ТЕЛЕМЕТРИЯ {current_time:.1f}s] X={gps_x:.1f}, Y={gps_y:.1f} | Высота: {altitude:.1f}м | {mode}"
        )
        last_telemetry_time = current_time

    # Зрение
    if frame_count % FRAME_SKIP == 0:
        raw_image = camera.getImage()
        if raw_image:
            image = np.frombuffer(raw_image, np.uint8).reshape(
                (camera.getHeight(), camera.getWidth(), 4)
            )
            bgr_image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            small_img = cv2.resize(bgr_image, (320, 240))

            results = model(
                small_img, conf=YOLO_CONFIDENCE, classes=[0], verbose=False, imgsz=320
            )
            person_detected = len(results[0].boxes) > 0

            is_fire, fire_ratio = detect_fire(small_img)
            is_flood, blue_ratio = detect_flood(small_img, pitch)

            last_annotated = bgr_image.copy()
            if person_detected:
                for box in results[0].boxes:
                    x1, y1, x2, y2 = [int(v * 2) for v in box.xyxy[0].tolist()]
                    cv2.rectangle(last_annotated, (x1, y1), (x2, y2), (255, 0, 0), 2)

            if is_fire:
                cv2.putText(
                    last_annotated,
                    f"FIRE: {fire_ratio*100:.1f}%",
                    (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 0, 255),
                    2,
                )
            if is_flood:
                cv2.putText(
                    last_annotated,
                    f"FLOOD: {blue_ratio*100:.1f}%",
                    (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 0, 0),
                    2,
                )

    frame_count += 1

    # ==========================================
    # 🤖 ЛОГИКА FSM (КОНЕЧНЫЙ АВТОМАТ)
    # ==========================================
    target_pitch_disturbance = 0.0
    yaw_disturbance = 0.0

    # 1. НОВЫЙ РЕЖИМ: ВЗЛЕТ
    if mode == "TAKEOFF":
        target_altitude = FLIGHT_ALTITUDE
        target_pitch_disturbance = 0.0  # Строго вверх, без наклона вперед
        yaw_disturbance = 0.0

        # Если набрали нужную высоту (с погрешностью 0.3 м), начинаем патруль
        if altitude >= FLIGHT_ALTITUDE - 0.3:
            print(
                f"✅ Взлет завершен (Высота: {altitude:.1f}м). Начинаю патрулирование!"
            )
            mode = "PATROL"

    # 2. ПАТРУЛИРОВАНИЕ (Работает только если мы уже на высоте)
    elif mode == "PATROL":
        if altitude > 1.0:
            target_x, target_y = waypoints[current_wp]
            distance = math.sqrt((target_x - gps_x) ** 2 + (target_y - gps_y) ** 2)

            if distance < 3.0:
                current_wp = (current_wp + 1) % len(waypoints)
                print(f"[NAV] Точка достигнута. Следующая: {waypoints[current_wp]}")

            target_yaw = math.atan2(target_y - gps_y, target_x - gps_x)
            yaw_error = target_yaw - yaw
            if yaw_error > math.pi:
                yaw_error -= 2 * math.pi
            elif yaw_error < -math.pi:
                yaw_error += 2 * math.pi

            yaw_disturbance = max(-1.5, min(1.5, yaw_error * DRONE_TURN_SPEED))

            if abs(yaw_error) < 0.4:
                target_pitch_disturbance = DRONE_MAX_SPEED
            else:
                target_pitch_disturbance = DRONE_MAX_SPEED * 0.3

            if person_detected or is_fire or is_flood:
                alert_type = (
                    "PERSON" if person_detected else ("FIRE" if is_fire else "FLOOD")
                )
                print(f"\n[ALERT] Обнаружено: {alert_type}.")
                mode = "FLOOD_ASCEND" if is_flood else "SCAN"

    # 3. ПОДЪЕМ ПРИ НАВОДНЕНИИ (Чтобы замерить масштаб)
    elif mode == "FLOOD_ASCEND":
        target_altitude += 0.05
        if not is_flood:
            mode = "SCAN"

    # 4. СКАНИРОВАНИЕ И ОТПРАВКА ОТЧЕТА
    elif mode == "SCAN":
        target_altitude = FLIGHT_ALTITUDE
        if current_time - last_report_time > REPORT_INTERVAL:
            filename = f"alert_{alert_type}_{int(current_time)}.jpg"
            if last_annotated is not None:
                cv2.imwrite(filename, last_annotated)
            print(f"🚨 [ШТАБ] {alert_type} | X={gps_x:.1f}, Y={gps_y:.1f}")
            mode = "COOLDOWN"
            last_report_time = current_time

    # 5. ПЕРЕРЫВ (Чтобы не спамить)
    elif mode == "COOLDOWN":
        target_pitch_disturbance = DRONE_MAX_SPEED
        if current_time - last_report_time > 5.0:
            mode = "PATROL"

    # Сглаживание наклона (Чтобы дрон не дергался)
    smooth_pitch_disturbance = (
        smooth_pitch_disturbance * 0.95 + target_pitch_disturbance * 0.05
    )
    pitch_disturbance = smooth_pitch_disturbance

    # ==========================================
    # ⚙️ PID РЕГУЛЯТОР И МОТОРЫ
    # ==========================================
    roll_input = K_ROLL_P * max(-1.0, min(1.0, roll)) + roll_velocity
    pitch_input = (
        K_PITCH_P * max(-1.0, min(1.0, pitch)) + pitch_velocity + pitch_disturbance
    )
    yaw_input = yaw_disturbance

    # Ограничитель подъема (чтобы не улетел в космос)
    clamped_diff_alt = max(
        -1.0, min(1.0, target_altitude - altitude + K_VERTICAL_OFFSET)
    )
    vertical_input = K_VERTICAL_P * math.pow(clamped_diff_alt, 3.0)

    fl_in = K_VERTICAL_THRUST + vertical_input - roll_input + pitch_input - yaw_input
    fr_in = K_VERTICAL_THRUST + vertical_input + roll_input + pitch_input + yaw_input
    rl_in = K_VERTICAL_THRUST + vertical_input - roll_input - pitch_input + yaw_input
    rr_in = K_VERTICAL_THRUST + vertical_input + roll_input - pitch_input - yaw_input

    # Защита от минуса
    fl.setVelocity(max(0, fl_in))
    fr.setVelocity(-max(0, fr_in))
    rl.setVelocity(-max(0, rl_in))
    rr.setVelocity(max(0, rr_in))

    # ==========================================
    # 📺 ВИЗУАЛИЗАЦИЯ
    # ==========================================
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
            f"Alt: {altitude:.1f}m / Target: {FLIGHT_ALTITUDE}m",
            (20, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.imshow("Oko MCHS", last_annotated)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == ord("й"):
            break
        elif key == ord("r") or key == ord("к"):
            reset_drone()
            mode = "TAKEOFF"  # Ручной сброс тоже возвращает в режим взлета
            target_altitude = FLIGHT_ALTITUDE

cv2.destroyAllWindows()
