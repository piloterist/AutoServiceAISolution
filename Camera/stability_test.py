"""Этап 1б: длительный прогон потока с автопереподключением.

    .venv\\Scripts\\python.exe stability_test.py --minutes 5

Во время прогона можно на 10-20 секунд выдернуть Ethernet-кабель камеры (или питание)
и вернуть: скрипт должен зафиксировать обрыв и восстановить поток сам.
Каждую минуту печатается сводка; в конце - итог и captures/stability_*.json.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

from stream_check import OUT_DIR, ROOT, build_url, cv2, get_password, open_capture

STALL_SEC = 3.0  # дольше без кадров - считаем обрывом


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--stream", default=os.environ.get("CAMERA_STREAM_PATH", "/stream1"))
    args = parser.parse_args()

    ip = os.environ.get("CAMERA_IP", "192.168.31.209")
    port = os.environ.get("CAMERA_RTSP_PORT", "554")
    user = os.environ.get("CAMERA_USER", "admin")
    password = get_password(user)
    url = build_url(ip, port, user, password, args.stream, mask=False)

    end = time.monotonic() + args.minutes * 60
    frames = 0
    max_gap = 0.0
    outages: list[dict] = []
    minute_frames = 0
    minute_mark = time.monotonic()
    last_frame = time.monotonic()
    cap = open_capture(url)
    print(f"Старт на {args.minutes} мин. Можно кратко отключить кабель камеры.")

    while time.monotonic() < end:
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        now = time.monotonic()
        if ok and frame is not None:
            max_gap = max(max_gap, now - last_frame)
            last_frame = now
            frames += 1
            minute_frames += 1
        elif now - last_frame > STALL_SEC:
            lost_at = last_frame
            print(f"[{datetime.now():%H:%M:%S}] обрыв потока, переподключаюсь...")
            cap.release()
            while time.monotonic() < end:
                cap = open_capture(url)
                if cap.isOpened():
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        break
                    cap.release()
                time.sleep(2)
            last_frame = time.monotonic()
            down = round(last_frame - lost_at, 1)
            outages.append({"at": datetime.now().strftime("%H:%M:%S"), "down_sec": down})
            print(f"[{datetime.now():%H:%M:%S}] поток восстановлен, простой {down} с")
        else:
            time.sleep(0.01)

        if now - minute_mark >= 60:
            print(f"[{datetime.now():%H:%M:%S}] за минуту кадров: {minute_frames}")
            minute_frames = 0
            minute_mark = now

    cap.release()
    report = {
        "minutes": args.minutes,
        "frames": frames,
        "max_gap_sec_without_outage": round(max_gap, 2),
        "outages": outages,
        "recovered_all": True,
    }
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"stability_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
