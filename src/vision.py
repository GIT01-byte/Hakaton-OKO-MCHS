# vision.py
import os
import time
import cv2
import numpy as np
import math
import threading
import queue
from collections import deque
import config
import geo
import profiler

cv2.setNumThreads(1)

frame_queue = queue.Queue(maxsize=1)   # (кадр для YOLO, поза дрона)
result_queue = queue.Queue(maxsize=1)  # (детекции, поза)
vis_queue = queue.Queue(maxsize=1)
key_queue = queue.Queue(maxsize=10)


# ----------------------------------------------------------------------------
#  YOLO: люди / животные / мусор
# ----------------------------------------------------------------------------
def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def split_detections(raw):
    """
    raw: список (класс_COCO, уверенность, [x1,y1,x2,y2] нормированные).
    Разделяет на людей / животных / мусор и отсекает ложных "людей":
      - рамка пересекается с более уверенной рамкой животного -> это животное;
      - рамка занимает слишком большую часть кадра -> не человек.
    """
    persons, animals, trash = [], [], []
    for cls, conf, box in raw:
        if cls == config.COCO_PERSON and conf >= config.PERSON_CONF:
            persons.append({"box": box, "conf": conf})
        elif cls in config.COCO_ANIMALS and conf >= config.ANIMAL_CONF:
            animals.append({"box": box, "conf": conf, "label": config.COCO_ANIMALS[cls]})
        elif cls in config.COCO_TRASH:
            trash.append({"box": box, "conf": conf, "label": config.COCO_TRASH[cls]})

    real = []
    for p in persons:
        area = (p["box"][2] - p["box"][0]) * (p["box"][3] - p["box"][1])
        if area > config.PERSON_MAX_BOX_AREA:
            continue
        if any(_iou(p["box"], a["box"]) > 0.4 and a["conf"] >= p["conf"] for a in animals):
            continue
        real.append(p)
    return {"persons": real, "animals": animals, "trash": trash, "fire_ml": []}


def start_threads():
    def yolo_worker():
        from ultralytics import YOLO
        import torch
        torch.set_num_threads(max(1, (os.cpu_count() or 4) // 2))
        model = YOLO("yolov8n.pt")
        fire_model = None
        if config.FIRE_MODEL_PATH and os.path.exists(config.FIRE_MODEL_PATH):
            fire_model = YOLO(config.FIRE_MODEL_PATH)
        wanted = [config.COCO_PERSON] + list(config.COCO_ANIMALS) + list(config.COCO_TRASH)
        low_conf = min(config.PERSON_CONF, config.ANIMAL_CONF)

        while True:
            item = frame_queue.get()
            if item is None:
                break
            frame, pose = item
            imgsz = (config.YOLO_IMGSZ_CLOSE
                     if pose["alt"] < config.YOLO_CLOSE_ALT else config.YOLO_IMGSZ)
            with profiler.measure("yolo.inference"):
                res = model(frame, conf=low_conf, classes=wanted,
                            verbose=False, imgsz=imgsz)[0]
            with profiler.measure("yolo.postprocess"):
                raw = [(int(b.cls[0]), float(b.conf[0]), b.xyxyn[0].tolist()) for b in res.boxes]
                dets = split_detections(raw)

            if fire_model is not None:
                with profiler.measure("yolo.fire_inference"):
                    r2 = fire_model(frame, conf=0.4, verbose=False, imgsz=config.YOLO_IMGSZ)[0]
                    dets["fire_ml"] = [b.xyxyn[0].tolist() for b in r2.boxes]

            while True:
                try:
                    result_queue.get_nowait()
                except queue.Empty:
                    break
            result_queue.put((dets, pose))

    def vis_worker():
        cv2.namedWindow("Oko MCHS", cv2.WINDOW_NORMAL)
        min_interval = 1.0 / config.VIS_FPS_LIMIT
        last_render = 0.0
        while True:
            try:
                frame = vis_queue.get(timeout=1.0)
                if frame is None:
                    break
                while True:
                    try:
                        nxt = vis_queue.get_nowait()
                    except queue.Empty:
                        break
                    if nxt is None:
                        frame = None
                        break
                    frame = nxt
                if frame is None:
                    break
                now = time.perf_counter()
                if now - last_render < min_interval:
                    continue
                last_render = now
                with profiler.measure("vis.render"):
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


class PersonTracker:
    """
    Подтверждение человека по времени и по месту на земле.
    Человек подтверждён, если в K из последних N результатов YOLO есть детекция,
    проецирующаяся в одну и ту же точку земли (радиус PERSON_CLUSTER_RADIUS).
    Детекция выше линии горизонта (нет пересечения с землёй) отбрасывается:
    это не человек на земле (чаще всего - ложное срабатывание на дерево/столб).
    """

    def __init__(self):
        self.hist = deque(maxlen=config.PERSON_WINDOW)
        self.confirmed = False
        self.position = None
        self.conf = 0.0

    def update(self, persons, pose):
        frame_pts = []
        for p in persons:
            b = p["box"]
            w = geo.pixel_to_world((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, pose)
            if w is not None:
                frame_pts.append((w, p["conf"]))
        self.hist.append(frame_pts)

        self.confirmed, self.position, self.conf = False, None, 0.0
        if not frame_pts:
            return
        best = 0
        for w0, _ in frame_pts:
            pts, confs = [], []
            for fp in self.hist:
                near = [(w, c) for w, c in fp
                        if math.hypot(w[0] - w0[0], w[1] - w0[1]) < config.PERSON_CLUSTER_RADIUS]
                if near:
                    w, c = max(near, key=lambda t: t[1])
                    pts.append(w)
                    confs.append(c)
            if len(pts) >= config.PERSON_CONFIRM_FRAMES and len(pts) > best:
                best = len(pts)
                self.confirmed = True
                self.position = (float(np.median([p[0] for p in pts])),
                                 float(np.median([p[1] for p in pts])))
                self.conf = max(confs)


# ----------------------------------------------------------------------------
#  Вспомогательное
# ----------------------------------------------------------------------------
def _largest_blob(mask):
    """Доля кадра, занятая самым большим пятном, центр и рамка (нормированные)."""
    h, w = mask.shape
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return 0.0, None, None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = stats[i, cv2.CC_STAT_AREA]
    x, y, bw, bh = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]
    return (area / (h * w), (cents[i][0] / w, cents[i][1] / h),
            (x / w, y / h, (x + bw) / w, (y + bh) / h))


def _texture_var(gray, k=7):
    g = gray.astype(np.float32)
    mu = cv2.blur(g, (k, k))
    return cv2.blur(g * g, (k, k)) - mu * mu


# ----------------------------------------------------------------------------
#  Вода
# ----------------------------------------------------------------------------
def detect_flood_accurate(img, drone_pitch, camera_pitch):
    """Возвращает (доля воды, список краёв с водой, центр воды в нормированных координатах)."""
    total_pitch_rad = drone_pitch + camera_pitch
    total_pitch_deg = math.degrees(total_pitch_rad)

    # от 0 до 40 (смотрит вниз) -> защита от неба выключена; смотрит вверх/горизонт -> включена
    use_sky_protection = -40.0 <= total_pitch_deg <= 0.0

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([90, 50, 50]), np.array([130, 255, 200]))

    if config.ENABLE_MUDDY_WATER:
        # мутная вода: коричневая, но ГЛАДКАЯ (грунт/оползень - шероховатые)
        brown = cv2.inRange(hsv, np.array([5, 40, 50]), np.array([25, 160, 180]))
        smooth = (_texture_var(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)) < config.WATER_TEXTURE_VAR)
        mask = cv2.bitwise_or(mask, cv2.bitwise_and(brown, smooth.astype(np.uint8) * 255))

    h, w = mask.shape
    cut_y = 0

    if use_sky_protection:
        sky_cut_ratio = 0.10 + (0.45 - 0.10) * ((40.0 - total_pitch_deg) / 40.0)
        sky_cut_ratio = max(0.05, min(0.5, sky_cut_ratio))
        cut_y = int(h * sky_cut_ratio)
        mask[:cut_y, :] = 0
        mask_v_high = cv2.inRange(hsv, np.array([0, 0, 200]), np.array([255, 255, 255]))
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(mask_v_high))

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    valid_area = w * (h - cut_y)
    if valid_area <= 0:
        return 0.0, [], None
    ratio = cv2.countNonZero(mask) / valid_area

    edge_h, edge_w = h // 5, w // 5
    edges = []
    if cut_y < edge_h and cv2.countNonZero(mask[0:edge_h, :]) > (edge_h * w * 0.15):
        edges.append("top")
    if cv2.countNonZero(mask[h - edge_h:h, :]) > (edge_h * w * 0.15):
        edges.append("bottom")
    if cv2.countNonZero(mask[:, 0:edge_w]) > (h * edge_w * 0.15):
        edges.append("left")
    if cv2.countNonZero(mask[:, w - edge_w:w]) > (h * edge_w * 0.15):
        edges.append("right")

    centroid = None
    if ratio > 0.01:
        m = cv2.moments(mask, binaryImage=True)
        if m["m00"] > 0:
            centroid = (m["m10"] / m["m00"] / w, m["m01"] / m["m00"] / h)
    return ratio, edges, centroid


# ----------------------------------------------------------------------------
#  Огонь
# ----------------------------------------------------------------------------
class ContrastFireDetector:
    """
    Детектор огня по цвету и площади (ваша логика): яркие оранжево-красные пятна
    (высокие S и V), морфология, самый большой контур. score - доля кадра под ним.
    Добавлено: подтверждение по времени (3 кадра из 5), чтобы не срабатывать на
    блик/один шумный кадр, и центр пятна для геопозиции.
    """

    def __init__(self):
        self.votes = deque(maxlen=config.FIRE_CONFIRM[1])
        self.info = {"centroid": None}

    def detect(self, img):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, np.array([0, 150, 200]), np.array([35, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([160, 150, 200]), np.array([180, 255, 255]))
        fire_mask = cv2.bitwise_or(mask1, mask2)

        kernel = np.ones((5, 5), np.uint8)
        fire_mask = cv2.morphologyEx(fire_mask, cv2.MORPH_OPEN, kernel)
        fire_mask = cv2.morphologyEx(fire_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(fire_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        max_area, best = 0, None
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 10 and area > max_area:
                max_area, best = area, cnt

        h, w = img.shape[:2]
        score = float(max_area) / (h * w)
        self.info = {"centroid": None}
        if best is not None:
            m = cv2.moments(best)
            if m["m00"] > 0:
                self.info = {"centroid": (m["m10"] / m["m00"] / w, m["m01"] / m["m00"] / h)}

        self.votes.append(score > config.CONTRAST_THRESHOLD)
        return sum(self.votes) >= config.FIRE_CONFIRM[0], score


# ----------------------------------------------------------------------------
#  Оползень и свалка
# ----------------------------------------------------------------------------
def detect_landslide(img):
    """Оползень = ОДНО крупное связное пятно голого грунта. Россыпь коричневых пикселей не считается.
    Возвращает (флаг, доля самого большого пятна, центр)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([10, 40, 40]), np.array([35, 180, 180]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    ratio, centroid, _ = _largest_blob(mask)
    return ratio > config.LANDSLIDE_THRESHOLD, ratio, centroid


def detect_landfill(img, trash_count=0):
    """
    Свалка = участок без растительности с высокой плотностью границ и разнообразием цветов
    (пакеты, бутылки, плёнка). Лес тоже "рваный", но он зелёный и однотонный по оттенку.
    Дополнительно: >= N предметов мусора (бутылки, пакеты...) по YOLO.
    Возвращает (флаг, доля захламлённых ячеек, центр).
    Векторизовано: интегральные суммы по ячейкам + bincount по ячейкам*оттенкам.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160)
    green = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([85, 255, 255]))
    h, w = gray.shape
    rows, cols = 6, 10
    ch, cw = h // rows, w // cols
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]

    pts = []
    ys, xs = np.nonzero(sat > 60)
    grid_ok = (ys < rows * ch) & (xs < cols * cw)
    ys, xs = ys[grid_ok], xs[grid_ok]
    if ys.size:
        hs = hue[ys, xs]
        cell_idx = (ys // ch) * cols + (xs // cw)
        hist = np.bincount(cell_idx * 6 + hs // 30,
                           minlength=rows * cols * 6).reshape(rows, cols, 6)
        iy = cv2.integral(edges)
        ig = cv2.integral(green)
        ridx = np.arange(rows + 1) * ch
        cidx = np.arange(cols + 1) * cw
        se = iy[np.ix_(ridx, cidx)]
        sg = ig[np.ix_(ridx, cidx)]
        area = (np.diff(ridx)[:, None] * np.diff(cidx)[None, :]).astype(np.float64)
        edge_sum = (se[:-1, :-1] - se[1:, :-1] - se[:-1, 1:] + se[1:, 1:]) / 255.0
        green_sum = (sg[:-1, :-1] - sg[1:, :-1] - sg[:-1, 1:] + sg[1:, 1:]) / 255.0
        edge_ok = edge_sum / area >= 0.10
        green_ok = green_sum / area <= 0.35
        hue_ok = (hist / area[:, :, None] > 0.05).sum(axis=2) >= 3
        for r, c in zip(*np.nonzero(edge_ok & green_ok & hue_ok)):
            pts.append(((c + 0.5) * cw / w, (r + 0.5) * ch / h))

    ratio = len(pts) / (rows * cols)
    centroid = (float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))) if pts else None
    flag = ratio > config.LANDFILL_THRESHOLD or trash_count >= config.TRASH_OBJECTS_FOR_LANDFILL
    return flag, ratio, centroid
