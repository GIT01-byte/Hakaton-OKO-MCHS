import asyncio
import cv2
from ultralytics import YOLO
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

# 1. Загружаем модель YOLO
model = YOLO("yolov8n.pt")


async def run():
    drone = System()
    await drone.connect(system_address="udp://:14540")  # Подключение к PX4 SITL

    print("Ожидание подключения к дрону...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("Дрон подключен!")
            break

    # 2. Создаем маршрут (пример: 3 точки)
    mission_items = [
        MissionItem(
            latitude_deg=47.397750,
            longitude_deg=8.545600,
            relative_altitude_m=20.0,
            speed_m_s=5.0,
            is_fly_through=True,
            gimbal_pitch_deg=0.0,
            gimbal_yaw_deg=0.0,
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=0.0,
            camera_photo_interval_s=0.0,
            acceptance_radius_m=1.0,
            yaw_deg=0.0,
            camera_photo_distance_m=0.0,
            vehicle_action=MissionItem.VehicleAction.NONE,
        ),
        MissionItem(
            latitude_deg=47.397800,
            longitude_deg=8.545700,
            relative_altitude_m=20.0,
            speed_m_s=5.0,
            is_fly_through=True,
            gimbal_pitch_deg=0.0,
            gimbal_yaw_deg=0.0,
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=0.0,
            camera_photo_interval_s=0.0,
            acceptance_radius_m=1.0,
            yaw_deg=0.0,
            camera_photo_distance_m=0.0,
            vehicle_action=MissionItem.VehicleAction.NONE,
        ),
        MissionItem(
            latitude_deg=47.397850,
            longitude_deg=8.545800,
            relative_altitude_m=20.0,
            speed_m_s=5.0,
            is_fly_through=True,
            gimbal_pitch_deg=0.0,
            gimbal_yaw_deg=0.0,
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=0.0,
            camera_photo_interval_s=0.0,
            acceptance_radius_m=1.0,
            yaw_deg=0.0,
            camera_photo_distance_m=0.0,
            vehicle_action=MissionItem.VehicleAction.NONE,
        ),
    ]
    mission_plan = MissionPlan(mission_items)

    print("Загрузка миссии...")
    await drone.mission.upload_mission(mission_plan)

    print("Взлет и старт миссии...")
    await drone.action.arm()
    await drone.mission.start_mission()

    # 3. Открываем камеру (в Gazebo это будет видеопоток, пока поставим вебку)
    cap = cv2.VideoCapture("./drone_footage_people.mp4")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Детекция YOLO
        results = model(
            frame, conf=0.45, classes=[0], verbose=False
        )  # Ищем только людей

        # Если нашли человека
        if len(results[0].boxes) > 0:
            print("🚨 ОБНАРУЖЕН ЧЕЛОВЕК! Отправка координат в штаб.")

            # Получаем текущие GPS координаты
            async for position in drone.telemetry.position():
                print(
                    f"Координаты: Широта {position.latitude_deg}, Долгота {position.longitude_deg}"
                )
                break

            # Дрон зависает
            await drone.action.hold()
            await asyncio.sleep(3)  # Ждем 3 секунды
            await drone.mission.start_mission()  # Продолжаем миссию

        # Показываем экран
        cv2.imshow("Drone Vision", results[0].plot())
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(run())
