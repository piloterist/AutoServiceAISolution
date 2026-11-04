"""Наблюдатель за камерой: поток -> номер -> трекер бокса -> события в облако ESP.

Один поток на камеру. Читает RTSP непрерывно (иначе буфер копит задержку), раз в
1/fps секунд распознаёт номер, ведёт BayTracker и отправляет подтверждённые въезды и
выезды на бэкенд (кадр события - JPEG в base64; бэкенд кладёт его на Яндекс.Диск).
События не теряются: недоставленные ждут в очереди, пока бэкенд не ответит.
"""

import base64
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

import bay_events as be
from bay_tracker import EMPTY, BayTracker, Event, TrackerConfig
from plate_pipeline import PlatePipeline, jpeg_bytes
from read_log import ReadLog
from stream_check import build_url, get_password, open_capture

KNOWN_REFRESH_SEC = 600
BAY_REFRESH_SEC = 60
RECONNECT_SEC = 5
MAX_OUTBOX = 200
FRAME_EVERY_SEC = 60  # свежий кадр бокса для страницы («Сейчас»), старый заменяется
FRAME_MAX_WIDTH = 1280  # для страницы хватает; полный кадр (1920) уходит только с событиями
FRAME_QUALITY = 75
WORK_MARGIN = timedelta(minutes=30)  # кадр шлём в рабочие часы цеха +- полчаса
HEARTBEAT_SEC = 30
CAMERA_STALE_SEC = 20  # кадров не было столько - камера считается недоступной
ACTIVE_HOLD_SEC = 5  # после номера или движения в боксе столько секунд держим полную частоту


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


class FrameReader(threading.Thread):
    """Вычитывает поток без остановки и хранит только последний кадр нужной частоты.

    Распознавание и отправка событий занимают от долей секунды до секунд (выгрузка кадра на
    Яндекс.Диск идёт внутри запроса к бэкенду). Если читать поток в том же цикле, камера
    копит пакеты, часть теряется - в логе `bad cseq`, битые кадры, обрыв потока.
    """

    def __init__(self, cap, fps: float):
        super().__init__(name="frame-reader", daemon=True)
        self.cap, self.fps = cap, fps
        self.alive = True
        self.last_grab = time.time()  # когда камера в последний раз отдала кадр
        self._latest: tuple[float, object] | None = None
        self._ready = threading.Condition()
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def take(self, timeout: float = 1.0) -> tuple[float, object] | None:
        with self._ready:
            if self._latest is None:
                self._ready.wait(timeout)
            item, self._latest = self._latest, None
            return item

    def run(self) -> None:
        last = 0.0
        while not self._stopped:
            if not self.cap.grab():
                self.alive = False
                with self._ready:
                    self._ready.notify_all()
                return
            now = time.time()
            self.last_grab = now
            if now - last < 1.0 / self.fps:
                continue
            last = now
            ok, frame = self.cap.retrieve()
            if ok and frame is not None:
                with self._ready:
                    self._latest = (now, frame)
                    self._ready.notify()


class CameraWatcher(threading.Thread):
    def __init__(self, camera: dict, defaults: dict, detection: dict, backend: str, headers: dict):
        super().__init__(name=f"watch-{camera['id']}", daemon=True)
        self.camera = camera
        self.fps = float(detection.get("fps", 3))
        # Пока в кадре нет номера и бокс пуст, достаточно редких проверок: это в разы дешевле.
        self.idle_fps = float(detection.get("idle_fps", 1))
        self.frame_every = float(detection.get("frame_every_sec", FRAME_EVERY_SEC))
        tracker_fields = {
            k: v for k, v in detection.items() if k in TrackerConfig.__dataclass_fields__
        }
        self.tracker_fields = {"exit_hold_sec": float(defaults.get("exit_hold_sec", 20)), **tracker_fields}
        self.roi = camera.get("detect_roi") or None
        self.backend, self.headers = backend, headers
        self.outbox: deque[dict] = deque(maxlen=MAX_OUTBOX)
        self.known: dict[str, str] = {}
        self.bay_id: str | None = None
        self.occupied_plate: str | None = None  # что бэкенд знает о боксе на старте
        self.schedule: dict | None = None  # рабочие часы цеха из карточки бокса
        self.tz = ZoneInfo(defaults.get("timezone", "Europe/Moscow"))
        self.reader: FrameReader | None = None
        self.stop_event = threading.Event()

    # ---- бэкенд ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        # trust_env=False: системные прокси не должны перехватывать обращения к бэкенду.
        return httpx.Client(base_url=self.backend, headers=self.headers, timeout=30.0, trust_env=False)

    def _find_bay(self, client: httpx.Client) -> dict | None:
        response = client.get("/api/v1/bays")
        response.raise_for_status()
        for bay in response.json()["bays"]:
            if bay.get("camera_code") == self.camera["id"] and bay.get("enabled", True):
                return bay
        return None

    def _refresh_known(self, client: httpx.Client) -> None:
        response = client.get("/api/v1/bays/known-plates")
        response.raise_for_status()
        self.known = {p["plate"]: p["work_order_number"] for p in response.json()["plates"]}
        log(f"{self.camera['id']}: известных номеров из заказ-нарядов: {len(self.known)}")

    def _flush(self, client: httpx.Client) -> None:
        while self.outbox:
            body = self.outbox[0]
            if self.bay_id is None:
                return
            response = client.post(f"/api/v1/bays/{self.bay_id}/events", json=body)
            response.raise_for_status()
            self.outbox.popleft()
            log(f"{self.camera['id']}: событие {body['event_type']} доставлено в ESP")

    def in_work_hours(self, now: float) -> bool:
        """Рабочие часы цеха (+- полчаса). Без расписания шлём всегда."""
        schedule = self.schedule
        if not schedule or not schedule.get("work_start") or not schedule.get("work_end"):
            return True
        local = datetime.fromtimestamp(now, self.tz)
        if schedule.get("work_days") and local.weekday() not in schedule["work_days"]:
            return False
        start = datetime.combine(local.date(), datetime.strptime(schedule["work_start"], "%H:%M:%S").time(), self.tz)
        end = datetime.combine(local.date(), datetime.strptime(schedule["work_end"], "%H:%M:%S").time(), self.tz)
        return start - WORK_MARGIN <= local <= end + WORK_MARGIN

    @property
    def camera_ok(self) -> bool:
        reader = self.reader
        return reader is not None and reader.alive and time.time() - reader.last_grab < CAMERA_STALE_SEC

    def _heartbeat_loop(self) -> None:
        """Раз в полминуты сообщает бэкенду: узел жив, камера отдаёт (не отдаёт) видео. Идёт в
        отдельном потоке: пока поток камеры не открывается (таймаут 30 с), узел всё равно виден."""
        code = self.camera["id"]
        with self._client() as client:
            while not self.stop_event.wait(HEARTBEAT_SEC):
                try:
                    client.post(
                        "/api/v1/bays/heartbeat",
                        json={"camera_code": code, "camera_ok": self.camera_ok},
                    ).raise_for_status()
                except (httpx.HTTPError, OSError):
                    pass  # бэкенд недоступен - следующая попытка через полминуты

    def _post_latest_frame(self, client: httpx.Client, frame) -> None:
        """Свежий кадр бокса раз в минуту: мастер видит, что в боксе происходит сейчас, и пропущенный
        выезд (бокс «занят», а на кадре пусто) заметен сразу."""
        jpeg = jpeg_bytes(frame, FRAME_MAX_WIDTH, FRAME_QUALITY)
        if not jpeg:
            return
        try:
            response = client.post(
                f"/api/v1/bays/{self.bay_id}/latest-frame",
                json={"snapshot_base64": base64.b64encode(jpeg).decode()},
            )
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            log(f"{self.camera['id']}: кадр бокса не отправлен ({type(exc).__name__})")

    # ---- события -----------------------------------------------------------------

    def _queue(self, event: Event, conn) -> None:
        result = event.result
        entry = event.kind == "entry_confirmed"
        note = result.summary
        if result.matched and result.work_order_number:
            fixed = " (номер исправлен по базе)" if result.raw and result.raw != result.plate else ""
            note = f"заказ-наряд {result.work_order_number}{fixed}; {note}"
        if not entry:
            note = f"выезд по треку номера; {note}"
        body = {
            "event_type": event.kind,
            "plate": result.plate,
            "ocr_confidence": min(max(result.confidence, 0.0), 1.0),
            "occurred_at": datetime.fromtimestamp(event.t).astimezone().isoformat(),
            "note": note[:500],
            "needs_review": entry and not result.reliable,
            "source": "auto",
        }
        jpeg = jpeg_bytes(event.frame) if event.frame is not None else None
        if jpeg:
            body["snapshot_base64"] = base64.b64encode(jpeg).decode()
        self.outbox.append(body)
        be.record_event(
            conn, bay_id=self.bay_id or self.camera["id"], camera_id=self.camera["id"],
            event_type=event.kind, plate_normalized=result.plate, ocr_confidence=result.confidence,
            review_status="needs_review" if body["needs_review"] else "auto", note=note,
        )  # fmt: skip
        log(
            f"{self.camera['id']}: {event.kind} номер {result.plate} "
            f"(по базе: {result.matched}, надёжно: {result.reliable}) - {result.summary}"
        )

    # ---- основной цикл -------------------------------------------------------------

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        cam = self.camera
        log(f"{cam['id']}: загружаю модели распознавания номера...")
        pipeline = PlatePipeline(roi=self.roi)
        conn = be.connect()
        readlog = ReadLog(cam["id"])
        threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True).start()
        track = 0  # номер «следа» машины для журнала чтения номера (см. read_log.py)
        url = build_url(
            cam["ip"], str(cam["rtsp_port"]), cam["user"], get_password(cam["user"]),
            cam["stream_path"], mask=False,
        )  # fmt: skip
        tracker: BayTracker | None = None
        last_refresh = {"known": 0.0, "bay": 0.0}
        failures = 0
        last_frame_post = 0.0
        last_processed = 0.0
        active_until = 0.0
        log(f"{cam['id']}: наблюдение запущено, {self.fps:g} кадр/с, область детектора: {self.roi or 'весь кадр'}")
        with self._client() as client:
            while not self.stop_event.is_set():
                cap = open_capture(url)
                if not cap.isOpened():
                    cap.release()
                    log(f"{cam['id']}: поток не открылся, повторяю через {RECONNECT_SEC} с")
                    time.sleep(RECONNECT_SEC)
                    continue
                reader = FrameReader(cap, self.fps)
                self.reader = reader
                reader.start()
                while not self.stop_event.is_set():
                    item = reader.take()
                    if item is None:
                        if not reader.alive:
                            log(f"{cam['id']}: поток оборвался, переподключаюсь")
                            break
                        continue
                    now, frame = item
                    if (
                        tracker is not None
                        and tracker.state == EMPTY
                        and now > active_until
                        and now - last_processed < 1.0 / self.idle_fps
                    ):
                        continue  # пустой бокс: распознаём реже
                    last_processed = now
                    try:
                        if now - last_refresh["bay"] > BAY_REFRESH_SEC or self.bay_id is None:
                            bay = self._find_bay(client)
                            last_refresh["bay"] = now
                            self.bay_id = bay["id"] if bay else None
                            self.schedule = bay
                            if bay is None:
                                log(f"{cam['id']}: в ESP нет бокса с кодом камеры {cam['id']} - события копятся")
                            elif tracker is None:
                                occupied = bay["plate"] if bay["state"] != "free" else None
                                self.occupied_plate = occupied
                        if now - last_refresh["known"] > KNOWN_REFRESH_SEC:
                            self._refresh_known(client)
                            last_refresh["known"] = now
                        if self.outbox:
                            self._flush(client)
                        if failures:
                            log(f"{cam['id']}: связь с бэкендом восстановлена")
                            failures = 0
                    except (httpx.HTTPError, OSError) as exc:
                        failures += 1
                        if failures in (1, 10) or failures % 100 == 0:
                            log(f"{cam['id']}: бэкенд недоступен ({type(exc).__name__}), события ждут в очереди")
                    if tracker is None:
                        occupied = self.occupied_plate
                        tracker = BayTracker(
                            TrackerConfig(frame_width=float(frame.shape[1]), **self.tracker_fields),
                            known=self.known,
                            occupied_plate=occupied,
                        )
                        log(f"{cam['id']}: трекер бокса запущен, бокс {'занят ' + occupied if occupied else 'свободен'}")
                    tracker.known = self.known
                    before = tracker.state
                    det = pipeline.detect(frame)
                    events = tracker.update(now, det, frame)
                    if before == EMPTY and tracker.state != EMPTY:
                        track += 1
                    if det is not None or tracker.state != EMPTY:
                        active_until = now + ACTIVE_HOLD_SEC
                    if det is not None:  # на любом расстоянии, до и после запуска следа
                        readlog.read(track + (tracker.state == EMPTY), tracker.state, det)
                    for event in events:
                        readlog.decision(track, event)
                        self._queue(event, conn)
                    if tracker.state != before:
                        log(f"{cam['id']}: состояние {before} -> {tracker.state}")
                    if (
                        now - last_frame_post >= self.frame_every
                        and self.bay_id is not None
                        and self.in_work_hours(now)
                    ):
                        last_frame_post = now
                        self._post_latest_frame(client, frame)
                reader.stop()
                reader.join(timeout=5)
                self.reader = None
                cap.release()
                time.sleep(RECONNECT_SEC)
