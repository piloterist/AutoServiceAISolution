"""Этап 1: подключение к RTSP камеры, кадр, короткий ролик, статистика потока.

Запуск (из папки Camera):
    .venv\\Scripts\\python.exe stream_check.py                # кадр + 10 с статистики + ролик
    .venv\\Scripts\\python.exe stream_check.py --stream /stream2 --seconds 5

Настройки берутся из переменных окружения или файла .env (см. .env.example).
Если CAMERA_PASSWORD не задан - пароль запрашивается скрыто (getpass).
Пароль нигде не печатается и не пишется в файлы.
"""

import argparse
import getpass
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")

import cv2  # noqa: E402
import keyring  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "captures"


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    pattern = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin\ffmpeg.exe"
    )
    matches = glob.glob(pattern, recursive=True)
    return matches[0] if matches else None


KEYRING_SERVICE = "vigi-c440-rtsp"


def get_password(user: str) -> str:
    """Пароль: переменная CAMERA_PASSWORD -> Диспетчер учётных данных Windows -> скрытый ввод.

    Сохранить в хранилище один раз: .venv\\Scripts\\python.exe save_password.py
    """
    password = os.environ.get("CAMERA_PASSWORD")
    if password:
        return password
    try:
        stored = keyring.get_password(KEYRING_SERVICE, user)
    except keyring.errors.KeyringError:
        stored = None
    return stored or getpass.getpass(f"Пароль камеры для {user} (ввод скрыт): ")


def build_url(ip: str, port: str, user: str, password: str, path: str, mask: bool) -> str:
    secret = "****" if mask else quote(password, safe="")
    return f"rtsp://{quote(user, safe='')}:{secret}@{ip}:{port}{path}"


def open_capture(url: str) -> cv2.VideoCapture:
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG)


def grab_stats(cap: cv2.VideoCapture, seconds: float) -> dict:
    """Читает поток `seconds` секунд и считает реальный FPS, паузы между кадрами, обрывы."""
    first_frame = None
    frames = 0
    gaps = []
    failures = 0
    last = None
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        ok, frame = cap.read()
        now = time.monotonic()
        if not ok or frame is None:
            failures += 1
            if failures > 30:
                break
            continue
        if first_frame is None:
            first_frame = frame
        if last is not None:
            gaps.append(now - last)
        last = now
        frames += 1
    elapsed = (last - started) if last else 0.0
    return {
        "frame": first_frame,
        "frames": frames,
        "read_failures": failures,
        "measured_fps": round(frames / elapsed, 2) if elapsed > 0 else 0.0,
        "max_gap_ms": round(max(gaps) * 1000) if gaps else None,
        "frames_over_500ms_gap": sum(1 for g in gaps if g > 0.5),
    }


def record_clip(ffmpeg: str, url: str, seconds: int, target: Path) -> tuple[bool, str]:
    """Пишет ролик БЕЗ перекодирования (-c copy): то, что реально отдаёт камера."""
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-rtsp_transport", "tcp", "-i", url,
        "-t", str(seconds), "-c", "copy", "-an", str(target),
    ]  # fmt: skip
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 30)
    return result.returncode == 0 and target.exists() and target.stat().st_size > 0, result.stderr


def probe_metadata(ffmpeg: str, url: str) -> dict | None:
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe"))
    if not Path(ffprobe).exists():
        return None
    cmd = [
        ffprobe, "-v", "error", "-rtsp_transport", "tcp", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,profile,width,height,avg_frame_rate,r_frame_rate,bit_rate,pix_fmt",
        "-of", "json", url,
    ]  # fmt: skip
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None
    streams = json.loads(result.stdout).get("streams", [])
    return streams[0] if streams else None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--stream", default=os.environ.get("CAMERA_STREAM_PATH", "/stream1"))
    parser.add_argument("--seconds", type=int, default=10, help="длительность статистики и ролика")
    parser.add_argument("--no-clip", action="store_true", help="только кадр и статистика")
    args = parser.parse_args()

    ip = os.environ.get("CAMERA_IP", "192.168.31.209")
    port = os.environ.get("CAMERA_RTSP_PORT", "554")
    user = os.environ.get("CAMERA_USER", "admin")
    password = get_password(user)
    if not password:
        print("Пароль не задан.")
        return 2

    url = build_url(ip, port, user, password, args.stream, mask=False)
    print(f"Подключение: {build_url(ip, port, user, password, args.stream, mask=True)}")

    cap = open_capture(url)
    if not cap.isOpened():
        print(
            "НЕ УДАЛОСЬ ОТКРЫТЬ ПОТОК. Возможные причины:\n"
            "  - неверный логин/пароль RTSP (в VIGI RTSP использует «учётную запись камеры»,\n"
            "    возможно, не совпадающую с паролем веб-интерфейса - проверьте в настройках);\n"
            "  - неверный путь потока (попробуйте --stream /stream2);\n"
            "  - RTSP отключён или ограничен по IP в настройках камеры."
        )
        return 1

    reported_fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    stats = grab_stats(cap, args.seconds)
    cap.release()

    frame = stats.pop("frame")
    if frame is None:
        print("Поток открылся, но кадры не приходят:", stats)
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot = OUT_DIR / f"snapshot_{stamp}.jpg"
    cv2.imwrite(str(snapshot), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])

    report = {
        "time": stamp,
        "stream_path": args.stream,
        "resolution_opencv": f"{width}x{height}",
        "fps_reported": reported_fps,
        **stats,
        "snapshot": str(snapshot),
    }

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        print("FFmpeg не найден: ролик и метаданные кодека пропущены.")
    else:
        report["ffprobe"] = probe_metadata(ffmpeg, url)
        if not args.no_clip:
            clip = OUT_DIR / f"clip_{stamp}.mp4"
            ok, err = record_clip(ffmpeg, url, args.seconds, clip)
            report["clip"] = str(clip) if ok else None
            if ok:
                report["clip_size_mb"] = round(clip.stat().st_size / 1_048_576, 2)
            else:
                report["clip_error"] = err.replace(quote(password, safe=""), "****").strip()[-500:]

    (OUT_DIR / f"report_{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
