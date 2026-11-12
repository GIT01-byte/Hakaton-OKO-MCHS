# profiler.py
"""Лёгкий секционный профайлер.

Использование:
    with profiler.measure("vision.detect_flood"):
        ...

Вкл/выкл - config.PROFILING_ENABLED. Когда выключено, measure() ничего не делает.
Отчёт: profiler.dump() - таблица секций (вызовы, всего/среднее/макс время, доля).
Потокобезопасно: секции можно замерять из разных потоков (main, YOLO, визуализация).
"""
import threading
import time
from contextlib import contextmanager

import config

_lock = threading.Lock()
_stats = {}  # name -> [вызовы, суммарное_время_с, максимальное_время_с]
_window_start = 0.0


@contextmanager
def measure(name):
    if not config.PROFILING_ENABLED:
        yield
        return
    global _window_start
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        with _lock:
            if not _stats:
                _window_start = t0
            s = _stats.get(name)
            if s is None:
                _stats[name] = [1, dt, dt]
            else:
                s[0] += 1
                s[1] += dt
                if dt > s[2]:
                    s[2] = dt


def dump(title="Замер производительности", reset_after=False):
    """Печатает таблицу замеров. reset_after=True обнуляет статистику после вывода."""
    if not config.PROFILING_ENABLED:
        return
    with _lock:
        snapshot = {name: tuple(s) for name, s in _stats.items()}
        wall = time.perf_counter() - _window_start if snapshot else 0.0
        if reset_after:
            _stats.clear()

    if not snapshot:
        print(f"[PROFILER] {title}: нет данных.")
        return

    loop = snapshot.get("loop.total")
    base = loop[1] if loop else sum(s[1] for s in snapshot.values())

    print(f"\n[PROFILER] === {title} | окно {wall:.1f} с ===")
    print(
        f"[PROFILER] {'Секция':<24}{'Вызовы':>8}{'Всего,мс':>11}"
        f"{'Сред,мс':>9}{'Макс,мс':>9}{'Доля':>8}"
    )
    for name, (count, total_s, max_s) in sorted(snapshot.items(), key=lambda kv: -kv[1][1]):
        avg_ms = total_s / count * 1000.0
        share = total_s / base * 100.0 if base > 0 else 0.0
        print(
            f"[PROFILER] {name:<24}{count:>8}{total_s * 1000.0:>11.1f}"
            f"{avg_ms:>9.2f}{max_s * 1000.0:>9.2f}{share:>7.1f}%"
        )
    if loop:
        rate = f" (~{loop[0] / wall:.1f} цикл/с)" if wall > 0 else ""
        print(
            f"[PROFILER] Циклов: {loop[0]}, среднее время цикла: "
            f"{loop[1] / loop[0] * 1000.0:.2f} мс{rate}"
        )
    print()
