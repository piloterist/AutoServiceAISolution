"""Проверка компьютера на площадке: потянет ли он узел видеоконтроля с камерами.

Запуск (из каталога Camera, в её виртуальном окружении):
    python pc_check.py --camera-ip 192.168.31.209 --backend https://<адрес бэкенда>

Что делает (ничего не меняет и не отправляет, кроме GET /health):
  1. показывает процессор, память, ОС;
  2. проверяет, что камера отвечает по RTSP-порту и бэкенд - по HTTPS;
  3. если задан пароль камеры (переменная CAMERA_PASSWORD или ввод): 20 секунд читает поток и
     замеряет, сколько процессорного времени уходит на декодирование одной камеры;
  4. замеряет распознавание (детектор номера + OCR) на этом компьютере;
  5. оценивает, сколько камер он потянет.
Результат печатается в консоль и сохраняется в pc_check_report.txt - пришлите его файлом.
"""

import argparse
import ctypes
import getpass
import os
import platform
import socket
import sys
import time

REPORT = []


def say(text: str = "") -> None:
    print(text)
    REPORT.append(text)


def memory_gb() -> float | None:
    if sys.platform != "win32":
        return None

    class Status(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            ("total", ctypes.c_ulonglong),
            ("avail", ctypes.c_ulonglong),
            ("total_page", ctypes.c_ulonglong),
            ("avail_page", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("avail_virtual", ctypes.c_ulonglong),
            ("avail_ext", ctypes.c_ulonglong),
        ]

    status = Status()
    status.length = ctypes.sizeof(Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.total / 1024**3


def cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor() or "неизвестно"


def hardware() -> None:
    say("== Компьютер ==")
    say(f"ОС:        {platform.platform()}")
    say(f"Процессор: {cpu_name()}")
    say(f"Потоков:   {os.cpu_count()}")
    ram = memory_gb()
    say(f"Память:    {ram:.1f} ГБ" if ram else "Память:    не определена")
    say(f"Python:    {platform.python_version()} ({platform.architecture()[0]})")


def check_camera(ip: str, port: int) -> None:
    say("\n== Камера ==")
    try:
        with socket.create_connection((ip, port), timeout=5):
            say(f"RTSP {ip}:{port}: порт открыт - ОК")
    except OSError as exc:
        say(f"RTSP {ip}:{port}: НЕТ СОЕДИНЕНИЯ ({exc})")


def check_backend(url: str | None) -> None:
    say("\n== Бэкенд ==")
    if not url:
        say("адрес не задан (--backend), пропускаю")
        return
    import httpx

    started = time.time()
    try:
        reply = httpx.get(url.rstrip("/") + "/health", timeout=10)
        say(f"{url}/health: {reply.status_code}, {time.time() - started:.2f} с - "
            f"{'ОК' if reply.status_code == 200 else 'ПРОБЛЕМА'}")
    except Exception as exc:  # noqa: BLE001 - любая сетевая ошибка важна для отчёта
        say(f"{url}: НЕТ СВЯЗИ ({exc})")


def bench_decode(ip: str, port: int, user: str, path: str, password: str, seconds: int = 20):
    import cv2

    say("\n== Декодирование потока камеры ==")
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    cap = cv2.VideoCapture(f"rtsp://{user}:{password}@{ip}:{port}{path}", cv2.CAP_FFMPEG)
    if not cap.isOpened():
        say("поток не открылся (проверьте пароль и путь)")
        return None
    frames, failures = 0, 0
    wall0, cpu0 = time.time(), time.process_time()
    size = None
    while time.time() - wall0 < seconds:
        ok, frame = cap.read()
        if ok:
            frames += 1
            size = frame.shape[1], frame.shape[0]
        else:
            failures += 1
    wall, cpu = time.time() - wall0, time.process_time() - cpu0
    cap.release()
    say(f"кадр {size[0]}x{size[1]}, {frames / wall:.1f} кадр/с, сбоев чтения: {failures}")
    say(f"процессорное время декодирования: {cpu / wall:.2f} ядра на камеру")
    return cpu / wall


def bench_recognition(runs: int = 15):
    import numpy as np

    say("\n== Распознавание номера (детектор + OCR) ==")
    from plate_pipeline import PlatePipeline

    pipeline = PlatePipeline(roi=[0.25, 0.10, 0.80, 0.75])  # как в bays.toml
    frame = np.random.default_rng(1).integers(0, 255, (1440, 2560, 3), dtype=np.uint8)
    pipeline.detect(frame)  # прогрев
    wall0, cpu0 = time.time(), time.process_time()
    for _ in range(runs):
        pipeline.detect(frame)
    wall, cpu = (time.time() - wall0) / runs, (time.process_time() - cpu0) / runs
    say(f"детектор (область кадра как в боксе): {wall * 1000:.0f} мс (процессор {cpu * 1000:.0f} мс)")
    say("(OCR добавляет ещё ~5-15 мс, когда номер найден)")
    return cpu + 0.015


def estimate(decode_cpu: float | None, detect_cpu: float | None, threads: int, fps: float = 3.0) -> None:
    say("\n== Оценка ==")
    if detect_cpu is None:
        return
    decode = decode_cpu if decode_cpu is not None else 0.10
    suffix = "" if decode_cpu is not None else " (декодирование взято ~0,10 - не замерено)"
    busy = decode + detect_cpu * fps  # камера с машиной в боксе
    idle = decode + detect_cpu * 1.0  # пустой бокс, 1 кадр/с
    usable = threads * 0.5  # держим загрузку не выше половины ради запаса
    say(f"одна камера с машиной в боксе (3 кадра/с): ~{busy:.2f} ядра{suffix}")
    say(f"одна камера, бокс пуст (1 кадр/с):         ~{idle:.2f} ядра")
    say(f"камер при загрузке не выше 50%: {usable / busy:.0f} (все с машинами) ... "
        f"{usable / idle:.0f} (все пусты)")
    say("Оценка грубая: настоящую цифру даёт пилот с живой камерой.")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--camera-ip", default="192.168.31.209")
    parser.add_argument("--camera-port", type=int, default=554)
    parser.add_argument("--camera-user", default="admin")
    parser.add_argument("--camera-path", default="/stream1")
    parser.add_argument("--backend", default=os.environ.get("ESP_BACKEND_URL"))
    parser.add_argument("--no-decode", action="store_true", help="не читать поток камеры")
    args = parser.parse_args()

    hardware()
    check_camera(args.camera_ip, args.camera_port)
    check_backend(args.backend)

    decode_cpu = None
    if not args.no_decode:
        password = os.environ.get("CAMERA_PASSWORD") or getpass.getpass(
            "\nПароль камеры (Enter - пропустить замер потока): "
        )
        if password:
            decode_cpu = bench_decode(
                args.camera_ip, args.camera_port, args.camera_user, args.camera_path, password
            )

    detect_cpu = None
    try:
        detect_cpu = bench_recognition()
    except Exception as exc:  # noqa: BLE001
        say(f"распознавание не запустилось: {exc}")

    estimate(decode_cpu, detect_cpu, os.cpu_count() or 1)

    with open("pc_check_report.txt", "w", encoding="utf-8") as report:
        report.write("\n".join(REPORT) + "\n")
    print("\nОтчёт сохранён: pc_check_report.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
