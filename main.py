import cv2
from ultralytics import YOLO
import time

model = YOLO("yolov8n.pt")
# Укажи путь к видео или 0 для веб-камеры
cap = cv2.VideoCapture(0)  # или "video.mp4"

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # Ищем людей, снижаем порог и увеличиваем разрешение
    results = model(frame, conf=0.6, imgsz=1280, classes=[0], verbose=False)

    annotated_frame = results[0].plot()

    # Если кого-то нашли — отправляем "алерт" в консоль
    if len(results[0].boxes) > 0:
        print(
            f"\n🚨 [ШТАБ] Получен пакет данных с дрона! Обнаружено объектов: {len(results[0].boxes)}"
        )
        for i, box in enumerate(results[0].boxes):
            conf = float(box.conf[0])
            # Имитация GPS координат (добавляем случайное смещение к базовой точке)
            lat = 55.7558 + (i * 0.0001)
            lon = 37.6173 + (i * 0.0001)

            print(
                f"   └ Пострадавший #{i+1}: Уверенность {conf:.0%} | Координаты: Ш={lat:.4f}, Д={lon:.4f} | Фото прикреплено"
            )

        # Чтобы консоль не спамила слишком быстро
        time.sleep(1)

    cv2.imshow("Drone Vision - Search & Rescue", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
