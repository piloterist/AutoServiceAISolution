"""Этап 2, подготовка: сбор тестового набора кадров для проверки распознавания номеров.

    .venv\\Scripts\\python.exe collect_frames.py --label 5m_day --minutes 3 --every 1.0

Сохраняет кадр раз в --every секунд в captures/dataset/<метка>_<время>/ в полном
разрешении. Метка - произвольная пометка сцены, например 3m_day, 5m_evening, 8m_headlights.
Подсказка по сбору: заезжайте медленно, на каждом расстоянии останавливайтесь на несколько
секунд. Кадры могут содержать номера и людей: в git и публичные места их не выкладывать
(папка captures/ уже в .gitignore).
Остановка раньше срока: Ctrl+C (уже сохранённые кадры остаются).
"""

import argparse
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

from stream_check import OUT_DIR, ROOT, build_url, cv2, get_password, open_capture


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="пометка сцены, например 5m_day")
    parser.add_argument("--minutes", type=float, default=3)
    parser.add_argument("--every", type=float, default=1.0, help="секунд между кадрами")
    parser.add_argument("--stream", default=os.environ.get("CAMERA_STREAM_PATH", "/stream1"))
    args = parser.parse_args()

    ip = os.environ.get("CAMERA_IP", "192.168.31.209")
    port = os.environ.get("CAMERA_RTSP_PORT", "554")
    user = os.environ.get("CAMERA_USER", "admin")
    password = get_password(user)
    url = build_url(ip, port, user, password, args.stream, mask=False)

    target = OUT_DIR / "dataset" / f"{args.label}_{datetime.now():%Y%m%d_%H%M%S}"
    target.mkdir(parents=True)
    cap = open_capture(url)
    if not cap.isOpened():
        print("Не удалось открыть поток (проверьте пароль/путь потока).")
        return 1

    end = time.monotonic() + args.minutes * 60
    next_save = 0.0
    saved = 0
    print(f"Сохраняю в {target}. Ctrl+C - остановить.")
    try:
        while time.monotonic() < end:
            ok, frame = cap.read()  # читаем непрерывно, чтобы не копился буфер
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            now = time.monotonic()
            if now >= next_save:
                name = target / f"{datetime.now():%H%M%S_%f}"[:-3]
                cv2.imwrite(str(name) + ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved += 1
                next_save = now + args.every
                if saved % 20 == 0:
                    print(f"  сохранено кадров: {saved}")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
    print(f"Готово: {saved} кадров в {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
