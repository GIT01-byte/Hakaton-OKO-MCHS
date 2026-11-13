# logger.py
import csv
import json
import os
import time
import threading
import queue
import requests
from config import TELEMETRY_FILE, REPORTS_FILE

# --- Настройки сервера ---
API_URL = os.getenv("OKO_API_URL", "http://127.0.0.1:8000/api")
API_KEY = os.getenv("OKO_API_KEY", "oko-drone-key")
DRONE_ID = int(os.getenv("OKO_DRONE_ID", "1"))
HEADERS = {"X-API-Key": API_KEY}

_SEVERITY_MAP = {
    "critical": "high",
    "критическая": "high",
    "критический": "high",
    "high": "high",
    "высокая": "high",
    "высокий": "high",
    "medium": "medium",
    "средняя": "medium",
    "средний": "medium",
    "low": "low",
    "низкая": "low",
    "низкий": "low",
}


def _norm_sev(value) -> str:
    return _SEVERITY_MAP.get(str(value or "").strip().lower(), "medium")


# ==========================================
# ФОНОВЫЙ ПОТОК ДЛЯ СЕТЕВЫХ ЗАПРОСОВ
# ==========================================
_http_queue = queue.Queue(maxsize=200)


def _http_worker():
    """Фоновый поток: забирает задачи из очереди и отправляет на сервер."""
    while True:
        task = _http_queue.get()
        if task is None:
            break  # Сигнал завершения

        kind, url, kwargs = task
        try:
            if kind == "telemetry":
                res = requests.post(
                    url,
                    json=kwargs["json"],
                    headers=HEADERS,
                    timeout=kwargs.get("timeout", 1.0),
                )
                if res.status_code not in (200, 201):
                    print(
                        f"[API] ⚠️ Фоновая телеметрия {res.status_code}: {res.text[:100]}"
                    )
                else:
                    # Можно раскомментировать для отладки, но лучше не спамить в консоль
                    # print(f"[API] 📡 Фоновая телеметрия OK")
                    pass

            elif kind == "report":
                files = {}
                image_path = kwargs.get("image_path")
                if image_path and os.path.exists(image_path):
                    files["image"] = (
                        os.path.basename(image_path),
                        open(image_path, "rb"),
                        "image/jpeg",
                    )

                res = requests.post(
                    url,
                    data=kwargs["data"],
                    files=files,
                    headers=HEADERS,
                    timeout=kwargs.get("timeout", 3.0),
                )

                if "image" in files:
                    files["image"][1].close()  # Важно закрыть файл!

                if res.status_code in (200, 201):
                    merged = res.json().get("merged", False)
                    print(
                        f"[API] 📸 Фоновый инцидент #{res.json().get('id')} (merged={merged})"
                    )
                else:
                    print(
                        f"[API] ⚠️ Фоновый инцидент {res.status_code}: {res.text[:200]}"
                    )

        except requests.exceptions.RequestException:
            pass  # Сервер недоступен — молчим, чтобы не спамить
        except Exception as e:
            print(f"[API] ❌ Ошибка фонового потока: {e}")
        finally:
            _http_queue.task_done()


def _queue_put(task):
    """Безопасно кладёт задачу в очередь. Если очередь переполнена, дропает самую старую."""
    try:
        _http_queue.put_nowait(task)
    except queue.Full:
        try:
            _http_queue.get_nowait()  # Выкидываем старую задачу
            _http_queue.task_done()
        except queue.Empty:
            pass
        _http_queue.put_nowait(task)


class Logger:
    current_mission_id = None
    _worker_thread = None

    @staticmethod
    def init():
        """Инициализация файлов, запуск фонового потока и старт миссии."""
        # 1. Запуск фонового потока
        Logger._worker_thread = threading.Thread(target=_http_worker, daemon=True)
        Logger._worker_thread.start()

        # 2. Создаем CSV с заголовками
        with open(TELEMETRY_FILE, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Time_s",
                    "X",
                    "Y",
                    "Z",
                    "Mode",
                    "Water_%",
                    "Fire_Score",
                    "Avoid",
                    "Persons",
                ]
            )

        # 3. Создаем пустой JSON для отчетов
        if not os.path.exists(REPORTS_FILE):
            with open(REPORTS_FILE, mode="w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=4)

        print("[Logger] Файлы телеметрии инициализированы.")
        print(f"[Logger] CSV:  {os.path.abspath(TELEMETRY_FILE)}")
        print(f"[Logger] JSON: {os.path.abspath(REPORTS_FILE)}")

        # 4. Старт миссии (синхронно, чтобы получить ID)
        Logger.start_mission()

    @staticmethod
    def start_mission():
        try:
            response = requests.post(
                f"{API_URL}/missions",
                json={"drone_id": DRONE_ID},
                headers=HEADERS,
                timeout=2,
            )
            if response.status_code == 201:
                Logger.current_mission_id = response.json()["id"]
                print(
                    f"[API] ✅ Миссия создана на сервере. ID: {Logger.current_mission_id}"
                )
            else:
                print(f"[API] ⚠️ Ошибка создания миссии: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"[API] ❌ Сервер недоступен. Работаем только локально. ({e})")

    @staticmethod
    def finish_mission():
        if Logger.current_mission_id is not None:
            try:
                # Дожидаемся отправки всех накопленных задач перед завершением
                if Logger._worker_thread is not None:
                    print("[Logger] Ожидание отправки оставшихся данных...")
                    _http_queue.join()
                    _http_queue.put(None)  # Останавливаем поток
                    Logger._worker_thread.join(timeout=2.0)

                requests.post(
                    f"{API_URL}/missions/{Logger.current_mission_id}/finish",
                    headers=HEADERS,
                    timeout=2,
                )
                print("[API] 🏁 Миссия завершена на сервере.")
            except requests.exceptions.RequestException:
                pass

    @staticmethod
    def telemetry(t, x, y, z, mode, water, fire, yaw=0.0, avoid="", persons=0):
        """Мгновенно пишет в CSV и отправляет в фоновый поток."""
        # 1) ЛОКАЛЬНАЯ ЗАПИСЬ (быстро, не блокирует)
        with open(TELEMETRY_FILE, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    f"{t:.1f}",
                    f"{x:.2f}",
                    f"{y:.2f}",
                    f"{z:.2f}",
                    mode,
                    f"{water*100:.1f}",
                    f"{fire:.4f}",
                    avoid,
                    persons,
                ]
            )

        # 2) ОТПРАВКА В ОЧЕРЕДЬ (мгновенно)
        if Logger.current_mission_id is not None:
            payload = {
                "mission_id": Logger.current_mission_id,
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 2),
                "yaw": round(yaw, 2),
                "battery": 100.0,
                "state": mode,
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "water_pct": round(water * 100, 1),
                "fire_score": round(fire, 4),
                "avoid": avoid,
                "persons": persons,
            }
            _queue_put(
                ("telemetry", f"{API_URL}/telemetry", {"json": payload, "timeout": 0.5})
            )

    @staticmethod
    def event(event_type, data=None):
        """События (оставляем без изменений для консоли)"""
        if data is None:
            data = {}
        if event_type == "TAKEOFF_DONE":
            print("✅ Взлет завершен. Начинаю патрулирование.")
        elif event_type == "SQUARE_SCAN":
            print(f"🔍 Дрон в центре квадрата {data.get('id', 0)}. Сканирование 360°.")
        elif event_type == "SQUARE_EMPTY":
            c, m = data.get("count", 0), data.get("max", 3)
            print(f"📭 Квадрат пуст ({c}/{m}).")
            if c >= m:
                print("🛑 3 пустых квадрата подряд. Возврат на базу.")
        elif event_type == "SQUARE_KNOWN":
            print("✔️  Квадрат осмотрен: инциденты уже отправлены в штаб.")
        elif event_type == "WATER_DETECTED":
            print(
                f"\n🚨 [ALERT] Вода! ({data.get('ratio', 0)*100:.1f}%, X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f})."
            )
        elif event_type == "FIRE_DETECTED":
            print(
                f"\n🔥 [ALERT] Пожар! ({data.get('score', 0)*100:.2f}%, X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f})."
            )
        elif event_type == "FIRE_STEP":
            print(
                f"🔥 [FIRE] Шаг {data.get('step')}: {data.get('score', 0)*100:.2f}%, кадр: {data.get('file')}"
            )
        elif event_type == "FIRE_MAX_INFO":
            print(
                f"🔥 [FIRE] Максимум: шаг {data.get('step')}, {data.get('score', 0)*100:.2f}%, кадров: {data.get('frames')}"
            )
        elif event_type == "LANDSLIDE_DETECTED":
            print(
                f"\n⛰️ [ALERT] Оползень! (X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f})."
            )
        elif event_type == "LANDFILL_DETECTED":
            print(
                f"\n🗑️ [ALERT] Свалка! (X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f})."
            )
        elif event_type == "PERSON_DETECTED":
            print(
                f"\n🧍 [ALERT] Человек (conf={data.get('conf', 0):.2f}, X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f})."
            )
        elif event_type == "PERSON_FALSE_ALARM":
            print("❎ Человек не подтверждён — ложная тревога.")
        elif event_type == "INCIDENT_DONE":
            print("↩️  Инцидент обработан. Продолжаю патрулирование.")
        elif event_type == "AVOID":
            print(f"🚧 [AVOID] {data.get('from')} -> {data.get('to')}")
        elif event_type == "AVOID_INIT":
            print(
                f"🚧 [AVOID] дальномеры/лидар: {'да' if data.get('ranges') else 'нет, только зрение'}"
            )
        elif event_type == "BATTERY_LOW":
            print("🔋 Заряд на исходе. Возврат на базу.")
        elif event_type == "MISSION_RETURN":
            print("🏁 Все точки облетены. Возврат на базу.")
        elif event_type == "LANDING":
            print("✅ Дрон на базе. Приземление завершено.")
        elif event_type == "RESET":
            print("\n🔄 [RESET] Сброс дрона...")
        elif event_type == "CRASH":
            print("\n⚠️ Дрон упал! Аварийный сброс.")

    @staticmethod
    def report(mission_name, x, y, z, area_m2, evidence_filename, extra_data=None):
        """Сохраняет отчет локально и кидает в фоновый поток."""
        report_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mission": mission_name,
            "coordinates": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
            "area_m2": round(area_m2, 1),
            "evidence": evidence_filename,
        }
        if extra_data:
            report_data.update(extra_data)

        try:
            with open(REPORTS_FILE, mode="r", encoding="utf-8") as f:
                reports = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            reports = []
        reports.append(report_data)
        with open(REPORTS_FILE, mode="w", encoding="utf-8") as f:
            json.dump(reports, f, ensure_ascii=False, indent=4)

        print(f"\n🚨 [ОТЧЕТ В ШТАБ] {mission_name} | X={x:.1f}, Y={y:.1f}")

        if Logger.current_mission_id is not None:
            inc_type = mission_name.lower()
            severity = _norm_sev(
                extra_data.get("severity", "medium") if extra_data else "medium"
            )
            local_id = 0
            if extra_data:
                local_id = extra_data.get("id", 0) or report_data.get("id", 0)

            data = {
                "mission_id": Logger.current_mission_id,
                "type": inc_type,
                "severity": severity,
                "x": x,
                "y": y,
                "area_pct": area_m2,
                "note": f"Автоматический отчет {mission_name} (local_id={local_id})",
                "people_count": 0,
            }
            if extra_data and extra_data.get("subtype"):
                data["subtype"] = str(extra_data["subtype"])

            _queue_put(
                (
                    "report",
                    f"{API_URL}/incidents",
                    {"data": data, "image_path": evidence_filename, "timeout": 3.0},
                )
            )

        return report_data
