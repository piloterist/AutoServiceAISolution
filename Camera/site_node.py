"""Узел видеоконтроля на площадке: связывает камеры в локальной сети с облаком ESP.

Умеет два дела:
1. Отвечать на кнопку «Получить кадр» на странице «Боксы»: раз в несколько секунд
   спрашивает бэкенд (исходящий HTTPS/HTTP, входящих портов не нужно), нет ли запросов
   кадра; для каждого снимает кадр с камеры бокса и загружает его.
2. Следить за камерами с detect = true в bays.toml: распознавать номер, определять въезд и
   выезд и отправлять события с кадрами в ESP (см. watcher.py). Отключить: --no-detect.

    .venv\\Scripts\\python.exe site_node.py                         # бэкенд из ESP_BACKEND_URL
    .venv\\Scripts\\python.exe site_node.py --backend http://localhost:8001

Настройки: ESP_BACKEND_URL (или --backend), токен API - в Диспетчере учётных данных
Windows (.venv\\Scripts\\python.exe save_backend_token.py) либо в переменной ESP_API_TOKEN.
Камеры берутся из bays.toml по коду камеры бокса (поле «Камера» у бокса на странице).
Остановка: Ctrl+C.
"""

import argparse
import base64
import os
import sys
import time
from datetime import datetime

import cv2
import httpx
import keyring
from dotenv import load_dotenv

import bay_events as be
from stream_check import build_url, get_password, open_capture

BACKEND_KEYRING_SERVICE = "esp-backend"
BACKEND_KEYRING_USER = "api"
POLL_SECONDS = 3.0
WARMUP_FRAMES = 15  # первые кадры после подключения бывают битыми/серыми
MAX_WIDTH = 1920  # снимок для страницы уменьшаем: полный 2560x1440 не нужен
JPEG_QUALITY = 85


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def backend_token() -> str:
    token = os.environ.get("ESP_API_TOKEN") or keyring.get_password(
        BACKEND_KEYRING_SERVICE, BACKEND_KEYRING_USER
    )
    if not token:
        sys.exit(
            "Нет токена API бэкенда. Сохраните: .venv\\Scripts\\python.exe save_backend_token.py"
        )
    return token


def describe_error(exc: Exception) -> str:
    """Тип ошибки плюс, для HTTP-ответа, адрес, код и начало тела (без заголовков и токена)."""
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        body = response.text.strip().replace("\n", " ")[:200]
        return f"{response.request.method} {response.request.url} -> {response.status_code} {body}"
    return f"{type(exc).__name__}: {exc}"


def grab_jpeg(camera: dict) -> bytes | None:
    """Один кадр с камеры, уменьшенный и закодированный в JPEG; None при неудаче."""
    password = get_password(camera["user"])
    url = build_url(
        camera["ip"], str(camera["rtsp_port"]), camera["user"], password, camera["stream_path"],
        mask=False,
    )  # fmt: skip
    cap = open_capture(url)
    frame = None
    try:
        if not cap.isOpened():
            return None
        for _ in range(WARMUP_FRAMES):
            ok, candidate = cap.read()
            if ok and candidate is not None:
                frame = candidate
    finally:
        cap.release()
    if frame is None:
        return None
    height, width = frame.shape[:2]
    if width > MAX_WIDTH:
        frame = cv2.resize(frame, (MAX_WIDTH, round(height * MAX_WIDTH / width)))
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return encoded.tobytes() if ok else None


def handle_request(client: httpx.Client, cameras: dict[str, dict], request: dict) -> None:
    request_id = request["id"]
    code = request.get("camera_code")
    camera = cameras.get(code or "")
    result: dict
    if camera is None:
        log(f"запрос {request_id[:8]}: у бокса нет известной камеры (код {code!r})")
        result = {"failed": True}
    else:
        started = time.monotonic()
        image = grab_jpeg(camera)
        if image is None:
            log(f"запрос {request_id[:8]}: камера {code} не отдала кадр")
            result = {"failed": True}
        else:
            log(f"запрос {request_id[:8]}: кадр с {code}, {len(image) // 1024} КБ, "
                f"{time.monotonic() - started:.1f} с")  # fmt: skip
            result = {"snapshot_base64": base64.b64encode(image).decode()}
    response = client.post(f"/api/v1/bays/snapshot-requests/{request_id}/result", json=result)
    response.raise_for_status()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(be.ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--backend", default=os.environ.get("ESP_BACKEND_URL"))
    parser.add_argument("--poll", type=float, default=POLL_SECONDS, help="секунд между опросами")
    parser.add_argument("--no-detect", action="store_true", help="не распознавать номера")
    args = parser.parse_args()
    if not args.backend:
        sys.exit("Укажите адрес бэкенда: --backend http://localhost:8001 или ESP_BACKEND_URL")

    config = be.load_config()
    cameras = {c["id"]: c for c in config["camera"]}
    headers = {"Authorization": f"Bearer {backend_token()}"}
    if not args.no_detect:
        from watcher import CameraWatcher  # тяжёлые модели грузим только если нужны

        for camera in cameras.values():
            if camera.get("detect"):
                CameraWatcher(
                    camera, config.get("defaults", {}), config.get("detection", {}),
                    args.backend, headers,
                ).start()  # fmt: skip
    log(f"узел запущен, бэкенд {args.backend}, камеры: {', '.join(cameras)}")

    failures = 0
    # trust_env=False: системные прокси (корпоративный VPN/Cisco) не должны перехватывать
    # обращения узла к бэкенду; при необходимости прокси можно будет сделать настройкой.
    with httpx.Client(
        base_url=args.backend, headers=headers, timeout=30.0, trust_env=False
    ) as client:
        while True:
            try:
                pending = client.get("/api/v1/bays/snapshot-requests/pending")
                pending.raise_for_status()
                for request in pending.json()["requests"]:
                    handle_request(client, cameras, request)
                if failures:
                    log("связь с бэкендом восстановлена")
                    failures = 0
            except (httpx.HTTPError, OSError) as exc:
                failures += 1
                if failures in (1, 10) or failures % 100 == 0:
                    log(f"ошибка связи с бэкендом, повторяю: {describe_error(exc)}")
            time.sleep(args.poll)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("остановлен")
