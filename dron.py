from controller import Robot
import cv2
import numpy as np
from ultralytics import YOLO

print("Инициализация...")
robot = Robot()
timestep = int(robot.getBasicTimeStep())

camera = robot.getDevice("camera")
camera.enable(timestep)

# Подключаем моторы
fl_motor = robot.getDevice("front left propeller")
fr_motor = robot.getDevice("front right propeller")
rl_motor = robot.getDevice("rear left propeller")
rr_motor = robot.getDevice("rear right propeller")

print("Загрузка YOLO...")
model = YOLO("yolov8n.pt")

# --- НАСТРОЙКИ ПОЛЕТА ---
# Если дрон не взлетает, УВЕЛИЧЬ ЭТО ЧИСЛО (например, до 80 или 90)
HOVER_THRUST = 68.0
# Разница скоростей для наклона вперед
TILT_FORWARD = 5.0

print("Подключено! Даю команду на взлет...")

while robot.step(timestep) != -1:
    # 1. Читаем камеру
    raw_image = camera.getImage()
    if raw_image:
        image = np.frombuffer(raw_image, np.uint8).reshape(
            (camera.getHeight(), camera.getWidth(), 4)
        )
        bgr_image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        # 2. Нейросеть
        results = model(bgr_image, conf=0.4, classes=[0], verbose=False)
        annotated = results[0].plot()

        # 3. Логика управления
        if len(results[0].boxes) > 0:
            # ВИДИМ ЧЕЛОВЕКА - ЗАВИСАЕМ
            print("🚨 Человек найден! Зависаю.")
            fl_motor.setVelocity(HOVER_THRUST)
            fr_motor.setVelocity(HOVER_THRUST)
            rl_motor.setVelocity(HOVER_THRUST)
            rr_motor.setVelocity(HOVER_THRUST)

            cv2.putText(
                annotated,
                "ALERT: PERSON",
                (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                2,
            )
        else:
            # НИКОГО НЕТ - ЛЕТИМ ВПЕРЕД (наклоняемся)
            # Передние крутятся чуть медленнее, задние чуть быстрее
            fl_motor.setVelocity(HOVER_THRUST - TILT_FORWARD)
            fr_motor.setVelocity(HOVER_THRUST - TILT_FORWARD)
            rl_motor.setVelocity(HOVER_THRUST + TILT_FORWARD)
            rr_motor.setVelocity(HOVER_THRUST + TILT_FORWARD)

        # 4. Показ
        cv2.imshow("Webots + YOLO", annotated)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

# Остановка при выходе
fl_motor.setVelocity(0)
fr_motor.setVelocity(0)
rl_motor.setVelocity(0)
rr_motor.setVelocity(0)
