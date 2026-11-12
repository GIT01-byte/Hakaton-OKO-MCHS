# vision.py
import cv2
import numpy as np
import math
import threading
import queue
from collections import deque
from ultralytics import YOLO
import config

cv2.setNumThreads(1)

frame_queue = queue.Queue(maxsize=1)
result_queue = queue.Queue(maxsize=1)
vis_queue = queue.Queue(maxsize=1)
key_queue = queue.Queue(maxsize=10)


def start_threads():
    def yolo_worker():
        model = YOLO("yolov8n.pt")
        while True:
            frame = frame_queue.get()
            if frame is None:
                break
            results = model(
                frame,
                conf=config.YOLO_CONFIDENCE,
                classes=[0],
                verbose=False,
                imgsz=320,
            )
            detected = len(results[0].boxes) > 0
            boxes = [b.xyxy[0].tolist() for b in results[0].boxes]
            while True:
                try:
                    result_queue.get_nowait()
                except queue.Empty:
                    break
            result_queue.put((detected, boxes))

    def vis_worker():
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
    threading.Thread(target=vis_worker, daemon=True).start()


def detect_flood_accurate(img, drone_pitch, camera_pitch):
    total_pitch_rad = drone_pitch + camera_pitch
    total_pitch_deg = math.degrees(total_pitch_rad)

    use_sky_protection = False
    if -40.0 <= total_pitch_deg <= 0.0:
        use_sky_protection = True

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([90, 50, 50]), np.array([130, 255, 200]))
    h, w = mask.shape
    cut_y = 0

    if use_sky_protection:
        sky_cut_ratio = 0.10 + (0.45 - 0.10) * ((40.0 - total_pitch_deg) / 40.0)
        sky_cut_ratio = max(0.05, min(0.5, sky_cut_ratio))
        cut_y = int(h * sky_cut_ratio)
        mask[:cut_y, :] = 0

        hsv_sky = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask_v_high = cv2.inRange(
            hsv_sky, np.array([0, 0, 200]), np.array([255, 255, 255])
        )
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(mask_v_high))

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    valid_area = w * (h - cut_y)
    if valid_area <= 0:
        return 0.0, []
    ratio = cv2.countNonZero(mask) / valid_area

    edge_h, edge_w = h // 5, w // 5
    edges = []
    if cut_y < edge_h:
        if cv2.countNonZero(mask[0:edge_h, :]) > (edge_h * w * 0.15):
            edges.append("top")
    if cv2.countNonZero(mask[h - edge_h : h, :]) > (edge_h * w * 0.15):
        edges.append("bottom")
    if cv2.countNonZero(mask[:, 0:edge_w]) > (h * edge_w * 0.15):
        edges.append("left")
    if cv2.countNonZero(mask[:, w - edge_w : w]) > (h * edge_w * 0.15):
        edges.append("right")

    return ratio, edges


class ContrastFireDetector:
    def __init__(self):
        pass

    def detect(self, img):
        # Перевод в HSV для выделения ярких цветов
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 1. Маска для оранжевого/желтого пламени
        mask1 = cv2.inRange(hsv, np.array([0, 150, 200]), np.array([35, 255, 255]))

        # 2. Маска для красного пламени (замыкается вокруг 180 градусов)
        mask2 = cv2.inRange(hsv, np.array([160, 150, 200]), np.array([180, 255, 255]))

        fire_mask = cv2.bitwise_or(mask1, mask2)

        # 3. Морфология для очистки от шума (мелких пикселей)
        kernel = np.ones((5, 5), np.uint8)
        fire_mask = cv2.morphologyEx(fire_mask, cv2.MORPH_OPEN, kernel)
        fire_mask = cv2.morphologyEx(fire_mask, cv2.MORPH_CLOSE, kernel)

        # 4. Поиск контуров
        contours, _ = cv2.findContours(
            fire_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        max_area = 0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 10 and area > max_area:
                max_area = area

        # 5. Вычисление score (доля площади огня от всего экрана)
        img_area = img.shape[0] * img.shape[1]
        score = float(max_area) / img_area

        is_fire = score > config.CONTRAST_THRESHOLD
        return is_fire, score


def detect_landslide(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([10, 40, 40]), np.array([35, 180, 180]))
    return (
        cv2.countNonZero(mask) / (img.shape[0] * img.shape[1])
    ) > config.LANDSLIDE_THRESHOLD


def detect_landfill(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([20, 20, 20]), np.array([80, 100, 120]))
    return (
        cv2.countNonZero(mask) / (img.shape[0] * img.shape[1])
    ) > config.LANDFILL_THRESHOLD
