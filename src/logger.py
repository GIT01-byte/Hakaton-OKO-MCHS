# Logger.py
import csv
import json
import os
import time

TELEMETRY_FILE = "telemetry_log.csv"
REPORTS_FILE = "mission_reports.json"


class Logger:
    @staticmethod
    def init():
        """Инициализация файлов при старте."""
        # CSV для телеметрии
        with open(TELEMETRY_FILE, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Time_s", "X", "Y", "Z", "Mode", "Water_%", "Fire_Score"])

        # JSON для отчетов миссий
        if not os.path.exists(REPORTS_FILE):
            with open(REPORTS_FILE, mode="w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=4)

        print("[Logger] Файлы телеметрии и отчетов инициализированы.")

    @staticmethod
    def telemetry(t, x, y, z, mode, water, fire):
        """Сохраняет телеметрию в CSV. Не спамит в консоль."""
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
                    f"{fire:.1f}",
                ]
            )

    @staticmethod
    def event(event_type, data=None):
        """
        Единая точка для всех консольных сообщений.
        Принимает тип события и сырые данные, формирует красивые строки.
        """
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

        elif event_type == "WATER_DETECTED":
            x, y = data.get("x", 0), data.get("y", 0)
            ratio = data.get("ratio", 0.0) * 100
            print(
                f"\n🚨 [ALERT] Вода! (Заполнение: {ratio:.1f}%, X={x:.1f}, Y={y:.1f}). Включаю миссию."
            )

        elif event_type == "FIRE_DETECTED":
            score = data.get("score", 0)
            print(f"\n🔥 [ALERT] Пожар! (Контраст: {score:.1f}). Подлетаю.")

        elif event_type == "LANDSLIDE_DETECTED":
            print("\n⛰️ [ALERT] Оползень! Подлетаю.")

        elif event_type == "LANDFILL_DETECTED":
            print("\n🗑️ [ALERT] Свалка! Подлетаю.")

        elif event_type == "MISSION_RETURN":
            print("🏁 Миссия выполнена, возврат на базу.")

        elif event_type == "LANDING":
            print("✅ Дрон на базе. Приземление завершено.")

        elif event_type == "RESET":
            print("\n🔄 [RESET] Сброс дрона...")

        elif event_type == "CRASH":
            print("\n⚠️ Дрон упал! Аварийный сброс.")

    @staticmethod
    def report(mission_name, x, y, z, area_m2, evidence_filename, extra_data=None):
        """Сохраняет структурированный JSON отчет и выводит финальное сообщение."""
        report_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mission": mission_name,
            "coordinates": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
            "area_m2": round(area_m2, 1),
            "evidence": evidence_filename,
        }
        if extra_data:
            report_data.update(extra_data)

        # Читаем старые, добавляем новый, сохраняем
        try:
            with open(REPORTS_FILE, mode="r", encoding="utf-8") as f:
                reports = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            reports = []

        reports.append(report_data)

        with open(REPORTS_FILE, mode="w", encoding="utf-8") as f:
            json.dump(reports, f, ensure_ascii=False, indent=4)

        # Красивый вывод в консоль
        print(f"\n🚨 [ОТЧЕТ В ШТАБ] {mission_name} | X={x:.1f}, Y={y:.1f}")
        if area_m2 > 0:
            print(f"📐 Площадь: {area_m2:.1f} м²")
        print(f"📸 Файл: {evidence_filename}")
        print(f"📁 Все отчеты сохранены в {REPORTS_FILE}\n")
