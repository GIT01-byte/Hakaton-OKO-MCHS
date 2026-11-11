from controller import Robot
import cv2
import numpy as np
from ultralytics import YOLO
import math
import time

print("=== ЗАПУСК СИСТЕМЫ МОНИТОРИНГА ===")
robot = Robot()
timestep = int(robot.getBasicTimeStep())

imu = robot.getDevice("inertial unit")
imu.enable(timestep)
gps = robot.getDevice("gps")
gps.enable(timestep)
gyro = robot.getDevice("gyro")
gyro.enable(timestep)
camera = robot.getDevice("camera")
camera.enable(timestep)

camera_pitch_motor = robot.getDevice("camera pitch")
if camera_pitch_motor:
    camera_pitch_motor.setPosition(0.0)

fl = robot.getDevice("front left propeller")
fr = robot.getDevice("front right propeller")
rl = robot.getDevice("rear left propeller")
rr = robot.getDevice("rear right propeller")

for m in [fl, fr, rl, rr]:
    m.setPosition(float("inf"))
    m.setVelocity(0.0)

model = YOLO("yolov8n.pt")

k_vertical_thrust = 68.5
k_vertical_offset = 0.6
k_vertical_p = 3.0
k_roll_p = 50.0
k_pitch_p = 30.0

target_altitude = 2.5
CRUISE_SPEED = -8.0
TURN_SPEED = 3.0

waypoints = []
y = 0
for i in range(20):
    if i % 2 == 0:
        waypoints.append((100.0, y))
    else:
        waypoints.append((0.0, y))
    y += 5.0

current_wp = 0
mode = "PATROL"
last_report_time = 0
max_blue_ratio = 0.0


def check_flood(img_bgr):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([90, 50, 50])
    upper_blue = np.array([130, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    blue_ratio = cv2.countNonZero(mask) / (img_bgr.shape[0] * img_bgr.shape[1])
    return blue_ratio > 0.8, blue_ratio


print("Взлетаем...")

while robot.step(timestep) != -1:
    current_time = robot.getTime()
    roll = imu.getRollPitchYaw()[0]
    pitch = imu.getRollPitchYaw()[1]
    yaw = imu.getRollPitchYaw()[2]
    gps_x = gps.getValues()[0]
    gps_y = gps.getValues()[1]
    altitude = gps.getValues()[2]
    roll_velocity = gyro.getValues()[0]
    pitch_velocity = gyro.getValues()[1]

    raw_image = camera.getImage()
    annotated = None
    is_flood_now = False
    blue_ratio = 0.0

    if raw_image:
        image = np.frombuffer(raw_image, np.uint8).reshape(
            (camera.getHeight(), camera.getWidth(), 4)
        )
        bgr_image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        if mode in ["FLOOD_ASCEND", "REPORT"]:
            is_flood_now, blue_ratio = check_flood(bgr_image)
            if blue_ratio > max_blue_ratio:
                max_blue_ratio = blue_ratio
            cv2.putText(
                bgr_image,
                f"Water: {blue_ratio*100:.1f}%",
                (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 0, 0),
                2,
            )
        else:
            results = model(bgr_image, conf=0.6, classes=[0], verbose=False)
            bgr_image = results[0].plot()
            is_flood_now, blue_ratio = check_flood(bgr_image)

        annotated = bgr_image

    pitch_disturbance = 0.0
    yaw_disturbance = 0.0

    if altitude > 1.0:
        if mode == "PATROL":
            target_x, target_y = waypoints[current_wp]
            distance = math.sqrt((target_x - gps_x) ** 2 + (target_y - gps_y) ** 2)

            if distance < 3.0:
                current_wp = (current_wp + 1) % len(waypoints)
                print(f"[NAV] Достигнута точка. Следующая: {waypoints[current_wp]}")

            target_yaw = math.atan2(target_y - gps_y, target_x - gps_x)
            yaw_error = target_yaw - yaw
            if yaw_error > math.pi:
                yaw_error -= 2 * math.pi
            elif yaw_error < -math.pi:
                yaw_error += 2 * math.pi

            if abs(yaw_error) > 0.3:
                yaw_disturbance = yaw_error * TURN_SPEED
                pitch_disturbance = 0.0
            else:
                yaw_disturbance = 0.0
                pitch_disturbance = CRUISE_SPEED

            if is_flood_now:
                print(
                    f"[ALERT] Наводнение! Заполнение кадра: {blue_ratio*100:.1f}%. Остановка XY, подъем Z+."
                )
                max_blue_ratio = blue_ratio
                mode = "FLOOD_ASCEND"
                if camera_pitch_motor:
                    camera_pitch_motor.setPosition(-1.57)
            else:
                if camera_pitch_motor:
                    camera_pitch_motor.setPosition(0.0)

        elif mode == "FLOOD_ASCEND":
            pitch_disturbance = 0.0
            yaw_disturbance = 0.0
            target_altitude += 0.03

            if not is_flood_now:
                print(
                    f"[INFO] Достигнута граница (высота {altitude:.1f}м). Фиксация масштаба."
                )
                mode = "REPORT"

        elif mode == "REPORT":
            pitch_disturbance = 0.0
            yaw_disturbance = 0.0
            target_altitude = 2.5

            if current_time - last_report_time > 3.0:
                print("========================================")
                print("📄 ОТЧЕТ О НАВОДНЕНИИ")
                print(f"Координаты: X={gps_x:.2f}, Y={gps_y:.2f}")
                print(f"Высота сканирования: {altitude:.2f} м")
                print(f"Макс. заполнение кадра водой: {max_blue_ratio*100:.1f}%")
                print("========================================")

                last_report_time = current_time
                mode = "PATROL"
                if camera_pitch_motor:
                    camera_pitch_motor.setPosition(0.0)
    else:
        pitch_disturbance = 0.0
        yaw_disturbance = 0.0

    roll_input = k_roll_p * max(-1.0, min(1.0, roll)) + roll_velocity
    pitch_input = (
        k_pitch_p * max(-1.0, min(1.0, pitch)) + pitch_velocity + pitch_disturbance
    )
    yaw_input = yaw_disturbance

    clamped_diff_alt = max(
        -1.0, min(1.0, target_altitude - altitude + k_vertical_offset)
    )
    vertical_input = k_vertical_p * math.pow(clamped_diff_alt, 3.0)

    fl_input = k_vertical_thrust + vertical_input - roll_input + pitch_input - yaw_input
    fr_input = k_vertical_thrust + vertical_input + roll_input + pitch_input + yaw_input
    rl_input = k_vertical_thrust + vertical_input - roll_input - pitch_input + yaw_input
    rr_input = k_vertical_thrust + vertical_input + roll_input - pitch_input - yaw_input

    fl.setVelocity(fl_input)
    fr.setVelocity(-fr_input)
    rl.setVelocity(-rl_input)
    rr.setVelocity(rr_input)

    if annotated is not None:
        cv2.putText(
            annotated,
            f"Mode: {mode} | Alt: {altitude:.1f} | X:{gps_x:.1f} Y:{gps_y:.1f}",
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.imshow("Scanner Drone", annotated)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
