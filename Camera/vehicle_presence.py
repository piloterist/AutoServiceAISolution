"""Есть ли в боксе автомобиль: детектор YOLOX-s (COCO, ONNX, лицензия Apache-2.0), на CPU.

Нужен как «второй голос» при подтверждении выезда: номер пропал и перестал читаться, но номер
закрывают руками, капотом, подъёмником. Если на кадре в боксе всё ещё стоит машина, выезд ложный.
Человек, инструмент и стеллажи машиной не считаются (проверено на кадрах двора и бокса).

Модель (~36 МБ) скачивается один раз в папку models/ рядом со скриптами и проверяется по
контрольной сумме. Нет модели или она сломалась - проверка отключается (check() даёт None), и узел
работает как раньше: ничего не блокируется.
"""

import hashlib
import os
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODEL_FILE = "yolox_s.onnx"
MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx"
MODEL_SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
DOWNLOAD_BUDGET_SEC = 900.0  # общий лимит на скачивание модели за одну попытку
INPUT_SIZE = 640
VEHICLE_CLASSES = {2: "car", 5: "bus", 7: "truck"}  # номера классов COCO (с нуля)
STRIDES = (8, 16, 32)
# Почти чёрный кадр (свет выключен, камера слепая): «машины нет» тут ничего не значит, поэтому
# такой кадр не доказывает пустой бокс и выезд по нему не подтверждается.
DARK_MEAN = 15.0


def models_dir() -> Path:
    return Path(os.environ.get("ESP_MODELS_DIR") or Path(__file__).resolve().parent / "models")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(download: bool = True) -> Path | None:
    """Путь к модели; при необходимости скачивает её. None - модели нет и скачать не вышло."""
    path = models_dir() / MODEL_FILE
    if path.exists() and _sha256(path) == MODEL_SHA256:
        return path
    if not download:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".part")
    os.close(fd)
    tmp = Path(tmp_name)
    deadline = time.monotonic() + DOWNLOAD_BUDGET_SEC
    try:
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "esp-camera-node"})
        with urllib.request.urlopen(request, timeout=30) as response, tmp.open("wb") as out:
            while chunk := response.read(1 << 18):
                out.write(chunk)
                if time.monotonic() > deadline:
                    return None  # слишком медленный канал: не держим узел, повторим позже
        if _sha256(tmp) != MODEL_SHA256:
            return None
        tmp.replace(path)
        return path
    except OSError:
        return None
    finally:
        tmp.unlink(missing_ok=True)


@dataclass
class Presence:
    present: bool
    score: float = 0.0  # уверенность лучшей найденной машины
    area: float = 0.0  # её доля площади кадра
    dark: bool = False  # кадр слишком тёмный: present=True лишь потому, что проверить нельзя


def _grid() -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for stride in STRIDES:
        n = INPUT_SIZE // stride
        xs, ys = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xs, ys), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), stride))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)


class VehiclePresence:
    """check(кадр) -> Presence; None, если проверить не удалось (тогда узел её не учитывает).

    Машиной считается рамка класса car/bus/truck с уверенностью не ниже min_score, занимающая
    не меньше min_area кадра, с центром внутри zone (доли кадра [x1, y1, x2, y2]). Порог площади
    отсекает машины за окном и уехавшую к воротам: нужна именно машина на месте бокса."""

    def __init__(
        self,
        model_path: Path,
        min_score: float = 0.25,
        min_area: float = 0.10,
        zone: list[float] | None = None,
    ):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1  # как и остальные модели: камеры не мешают друг другу
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.min_score, self.min_area = min_score, min_area
        self.zone = zone if zone and len(zone) == 4 else None
        self._grid, self._strides = _grid()

    def check(self, frame) -> Presence | None:
        try:
            return self._check(frame)
        except Exception:  # noqa: BLE001 - любой сбой модели не должен ронять наблюдение
            return None

    def _check(self, frame) -> Presence:
        height, width = frame.shape[:2]
        if float(cv2.resize(frame, (64, 36)).mean()) < DARK_MEAN:
            return Presence(True, dark=True)
        ratio = min(INPUT_SIZE / height, INPUT_SIZE / width)
        new_h, new_w = int(round(height * ratio)), int(round(width * ratio))
        canvas = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, np.uint8)
        canvas[:new_h, :new_w] = cv2.resize(frame, (new_w, new_h))
        x = canvas.transpose(2, 0, 1)[None].astype(np.float32)  # BGR, 0..255, без нормализации
        out = self.session.run(None, {self.input_name: x})[0][0]
        centers = (out[:, :2] + self._grid) * self._strides
        sizes = np.exp(out[:, 2:4]) * self._strides
        objectness = out[:, 4]
        best = Presence(False)
        for class_id in VEHICLE_CLASSES:
            scores = objectness * out[:, 5 + class_id]
            for i in np.where(scores >= self.min_score)[0]:
                area = float(sizes[i, 0] * sizes[i, 1]) / (ratio * ratio) / (height * width)
                cx = float(centers[i, 0]) / ratio / width
                cy = float(centers[i, 1]) / ratio / height
                if area < self.min_area:
                    continue
                if self.zone and not (
                    self.zone[0] <= cx <= self.zone[2] and self.zone[1] <= cy <= self.zone[3]
                ):
                    continue
                if scores[i] > best.score:
                    best = Presence(True, float(scores[i]), area)
        return best
