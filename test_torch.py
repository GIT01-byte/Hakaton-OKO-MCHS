import sys
import platform


def test_stack():
    print(f"=== СИСТЕМНЫЙ ТЕСТ СТЕКА ===")
    print(f"ОС: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Путь к Python: {sys.executable}\n")

    # 1. Проверка PyTorch
    try:
        import torch

        print(f"✅ PyTorch: {torch.__version__}")
        print(f"   CUDA (GPU) доступна: {torch.cuda.is_available()}")
    except ImportError as e:
        print(f"❌ PyTorch не установлен: {e}")

    # 2. Проверка OpenCV
    try:
        import cv2

        print(f"✅ OpenCV: {cv2.__version__}")
    except ImportError as e:
        print(f"❌ OpenCV не установлен: {e}")

    # 3. Проверка Ultralytics (YOLO)
    try:
        import ultralytics

        print(f"✅ Ultralytics YOLO: {ultralytics.__version__}")

        # Быстрый тест инференса
        from ultralytics import YOLO

        model = YOLO("yolov8n.pt")  # Загрузит веса, если их нет
        print("   ✅ Загрузка модели YOLO прошла успешно.")
    except ImportError as e:
        print(f"❌ Ultralytics не установлен: {e}")
    except Exception as e:
        print(f"⚠️ Ошибка при тесте YOLO: {e}")

    # 4. Проверка MAVSDK
    try:
        import mavsdk

        print(f"✅ MAVSDK: {mavsdk.__version__}")
    except ImportError as e:
        print(f"❌ MAVSDK не установлен: {e}")

    # 5. Проверка Numpy (нужен для всего)
    try:
        import numpy as np

        print(f"✅ NumPy: {np.__version__}")
    except ImportError as e:
        print(f"❌ NumPy не установлен: {e}")

    print("\n=== ТЕСТ ЗАВЕРШЕН ===")


if __name__ == "__main__":
    test_stack()
