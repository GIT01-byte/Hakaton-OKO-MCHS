# Logger.py
import csv
import json
import os
import time
import requests  # Библиотека для HTTP-запросов (pip install requests)

TELEMETRY_FILE = "telemetry_log.csv"
REPORTS_FILE = "mission_reports.json"

# Настройки подключения к API
API_URL = "http://127.0.0.1:8000/api"
DRONE_ID = 1  # ID дрона в базе данных бэкенда (по умолчанию создается Mavic-1)


class Logger:
    current_mission_id = None  # Сюда сохранится ID миссии с сервера

    @staticmethod
    def init():
        """Инициализация файлов при старте и создание миссии на сервере."""
        # 1. Локальные файлы
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

        if not os.path.exists(REPORTS_FILE):
            with open(REPORTS_FILE, mode="w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=4)

        print("[Logger] Файлы телеметрии и отчетов инициализированы.")

        # 2. Создаем миссию на бэкенде
        Logger.start_mission()

    @staticmethod
    def start_mission():
        """Создает новую миссию на бэкенде."""
        try:
            response = requests.post(
                f"{API_URL}/missions", json={"drone_id": DRONE_ID}, timeout=2
            )
            if response.status_code == 201:
                Logger.current_mission_id = response.json()["id"]
                print(
                    f"[API] ✅ Миссия успешно создана на сервере. ID: {Logger.current_mission_id}"
                )
            else:
                print(
                    f"[API] ⚠️ Ошибка создания миссии: {response.status_code} {response.text}"
                )
        except requests.exceptions.RequestException as e:
            print(f"[API] ❌ Сервер недоступен (миссия не создана): {e}")

    @staticmethod
    def finish_mission():
        """Завершает миссию на бэкенде."""
        if Logger.current_mission_id is not None:
            try:
                requests.post(
                    f"{API_URL}/missions/{Logger.current_mission_id}/finish", timeout=2
                )
                print("[API] 🏁 Миссия завершена на сервере.")
            except requests.exceptions.RequestException:
                pass

    @staticmethod
    def telemetry(t, x, y, z, mode, water, fire, yaw=0.0, avoid="", persons=0):
        """Сохраняет телеметрию в CSV и отправляет на сервер."""
        # 1. Локальное сохранение (CSV)
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

        # 2. Отправка на сервер (JSON)
        if Logger.current_mission_id is not None:
            payload = {
                "mission_id": Logger.current_mission_id,
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 2),
                "yaw": round(yaw, 2),
                "battery": 100.0,  # Заглушка (если нет датчика батареи)
                "state": mode,
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            try:
                # Таймаут 0.5 сек, чтобы не тормозить основной цикл дрона
                requests.post(f"{API_URL}/telemetry", json=payload, timeout=0.5)
            except requests.exceptions.RequestException:
                pass  # Игнорируем ошибки сети, чтобы не ронять дрон

    @staticmethod
    def event(event_type, data=None):
        """Единая точка для всех консольных сообщений."""
        if data is None:
            data = {}

        if event_type == "TAKEOFF_DONE":
            print("✅ Взлет завершен. Начинаю патрулирование по сетке.")
        elif event_type == "SQUARE_SCAN":
            print(f"🔍 Дрон в центре квадрата {data.get('id', 0)}. Сканирование 360°.")
        elif event_type == "SQUARE_EMPTY":
            count = data.get("count", 0)
            max_count = data.get("max", 3)
            print(f"📭 Квадрат пуст ({count}/{max_count}).")
            if count >= max_count:
                print("🛑 3 пустых квадрата подряд. Возврат на базу.")
        elif event_type == "SQUARE_KNOWN":
            print("✔️  Квадрат осмотрен: инциденты в нём уже отправлены в штаб.")
        elif event_type == "WATER_DETECTED":
            x, y = data.get("x", 0), data.get("y", 0)
            ratio = data.get("ratio", 0.0) * 100
            print(
                f"\n🚨 [ALERT] Вода! (Заполнение: {ratio:.1f}%, X={x:.1f}, Y={y:.1f}). Включаю миссию."
            )
        elif event_type == "FIRE_DETECTED":
            score = data.get("score", 0)
            print(
                f"\n🔥 [ALERT] Пожар! (Доля кадра: {score*100:.2f}%, "
                f"X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f}). Подлетаю."
            )
        elif event_type == "LANDSLIDE_DETECTED":
            print(
                f"\n⛰️ [ALERT] Оползень! (X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f}). Подлетаю."
            )
        elif event_type == "LANDFILL_DETECTED":
            print(
                f"\n🗑️ [ALERT] Свалка! (X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f}). Подлетаю."
            )
        elif event_type == "PERSON_DETECTED":
            print(
                f"\n🧍 [ALERT] Возможно человек (conf {data.get('conf', 0):.2f}, "
                f"X={data.get('x', 0):.1f}, Y={data.get('y', 0):.1f}). Снижаюсь для проверки."
            )
        elif event_type == "PERSON_FALSE_ALARM":
            print("❎ Человек не подтверждён с малой высоты - ложная тревога.")
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
        """Сохраняет структурированный JSON отчет локально и отправляет на сервер с фото."""
        # 1. Формируем локальный отчет
        report_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mission": mission_name,
            "coordinates": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
            "area_m2": round(area_m2, 1),
            "evidence": evidence_filename,
        }
        if extra_data:
            report_data.update(extra_data)

        # Запись в JSON
        try:
            with open(REPORTS_FILE, mode="r", encoding="utf-8") as f:
                reports = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            reports = []
        reports.append(report_data)
        with open(REPORTS_FILE, mode="w", encoding="utf-8") as f:
            json.dump(reports, f, ensure_ascii=False, indent=4)

        # 2. Вывод в консоль
        sev = report_data.get("severity")
        print(
            f"\n🚨 [ОТЧЕТ В ШТАБ] {mission_name}"
            + (f" [{sev}]" if sev else "")
            + f" | X={x:.1f}, Y={y:.1f}"
        )
        if area_m2 > 0:
            print(f"📐 Площадь: {area_m2:.1f} м²")
        print(f"📸 Файл: {evidence_filename}")
        print(f"📁 Все отчеты сохранены в {REPORTS_FILE}\n")

        # 3. Отправка на сервер (multipart/form-data)
        if Logger.current_mission_id is not None:
            # Извлекаем severity из extra_data, если он есть, иначе ставим MEDIUM
            severity = extra_data.get("severity", "MEDIUM") if extra_data else "MEDIUM"

            # Формируем Form-данные
            data = {
                "mission_id": Logger.current_mission_id,
                "type": mission_name,
                "severity": severity,
                "x": x,
                "y": y,
                "area_pct": area_m2,  # Передаем площадь в поле area_pct
                "note": f"Автоматический отчет {mission_name}",
            }

            # Прикрепляем фото, если файл существует
            files = {}
            if evidence_filename and os.path.exists(evidence_filename):
                files["image"] = (
                    os.path.basename(evidence_filename),
                    open(evidence_filename, "rb"),
                    "image/jpeg",
                )

            try:
                response = requests.post(
                    f"{API_URL}/incidents", data=data, files=files, timeout=3
                )
                if response.status_code in [200, 201]:
                    print(
                        f"[API] 📸 Инцидент успешно отправлен на сервер (Status: {response.status_code})"
                    )
                else:
                    print(f"[API] ⚠️ Ошибка отправки инцидента: {response.text}")
            except requests.exceptions.RequestException as e:
                print(f"[API] ❌ Не удалось отправить инцидент: {e}")
            finally:
                # Обязательно закрываем файл после отправки
                if "image" in files:
                    files["image"][1].close()

        return report_data
