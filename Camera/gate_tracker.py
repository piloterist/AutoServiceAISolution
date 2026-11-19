"""Ворота кузовного цеха: машина проезжает под камерой, не останавливаясь.

Камера стоит перед воротами и смотрит на них (как слесарная камера). Заезд: машина едет к камере,
номер растёт в кадре и пропадает на большом размере (машина прошла под камерой). Выезд: номер
появляется крупным и уменьшается (машина удаляется к воротам). Остановки и состояния «бокс занят»
тут нет: каждый проезд - один «след» номера, итог которого - одно событие.

    след = подряд идущие детекции номера (разрыв больше gap_sec или скачок - новый след)
    след закончился (детекций нет gap_sec) -> решаем:
        детекций меньше min_samples                    -> ничего (случайный отблеск, мусор)
        номер вырос (последняя треть / первая >= grow_ratio)     -> entry_confirmed
        номер уменьшился (<= shrink_ratio)                       -> exit_confirmed
        иначе                                          -> ничего, но запоминаем «неясное направление»

Номер читается по ВСЕМ кадрам следа (сумма вероятностей символов с весом по размеру номера: крупный
номер надёжнее), как у слесарного бокса. Время события - середина следа; кадр - с самым крупным
номером. Событие отдаётся даже с нечитаемым или ненадёжным номером: проезд был, а номер человек
поправит руками (плата None или reliable=False -> needs_review в watcher).

Чистая логика: время и детекции подаёт вызывающий, кадры только передаются в события.
"""

from dataclasses import dataclass
from statistics import median

import cv2
import numpy as np

import plates
from bay_tracker import Detection, Event

EMPTY, TRACK = "EMPTY", "TRACK"


@dataclass
class GateConfig:
    frame_width: float = 2560.0
    min_conf: float = 0.35
    min_width: float = 60.0  # номер мельче - слишком далёкий, в след не берём
    gap_sec: float = 1.5  # столько секунд без детекций - след закончился
    min_samples: int = 3  # детекций в следе, чтобы вообще решать
    grow_ratio: float = 1.4  # (последняя треть / первая) >= - въезд
    shrink_ratio: float = 0.7  # <= - выезд
    jump_shift_frac: float = 0.25  # смещение номера между соседними кадрами (доля ширины кадра)
    jump_width_ratio: float = 2.0  # изменение ширины между соседними кадрами - другая машина
    # Номера, у которых нет вероятностей символов (или слишком мелкие), в чтение не идут.
    read_min_width: float = 80.0


@dataclass
class _Sample:
    t: float
    cx: float
    width: float
    conf: float
    frame: object | None


class GateTracker:
    def __init__(
        self,
        config: GateConfig,
        known: plates.KnownPlates | dict[str, str] | None = None,
    ):
        self.cfg = config
        self.known = known
        self.samples: list[_Sample] = []
        self.reads = plates.SlotReads()
        self.notes: list[str] = []  # следы без события: что сказать в журнал (watcher забирает)
        self.unclear = 0  # сколько следов закончилось неясным направлением
        self.too_short = 0

    # ---- служебное -------------------------------------------------------------

    @property
    def state(self) -> str:
        """Для журнала чтения номера и watcher: след идёт или кадр пуст."""
        return TRACK if self.samples else EMPTY

    def _known_index(self) -> plates.KnownPlates | None:
        if self.known is None or isinstance(self.known, plates.KnownPlates):
            return self.known
        cached = getattr(self, "_known_cache", None)
        if cached is None or cached[0] is not self.known or cached[1] != len(self.known):
            cached = (self.known, len(self.known), plates.KnownPlates(self.known))
            self._known_cache = cached
        return cached[2]

    def _is_jump(self, det: Detection) -> bool:
        last = self.samples[-1]
        if abs(det.cx - last.cx) > self.cfg.jump_shift_frac * self.cfg.frame_width:
            return True
        ratio = det.width / last.width if last.width else 1.0
        return ratio > self.cfg.jump_width_ratio or ratio < 1.0 / self.cfg.jump_width_ratio

    def _add(self, t: float, det: Detection, frame) -> None:
        self.samples.append(_Sample(t, det.cx, det.width, det.conf, frame))
        if det.probs is not None and det.width >= self.cfg.read_min_width:
            self.reads.add(det.probs, det.width / 100.0 * det.conf)

    def _reset(self) -> None:
        self.samples = []
        self.reads = plates.SlotReads()

    # ---- итог следа ------------------------------------------------------------

    def _direction(self, samples: list[_Sample]) -> str | None:
        widths = [s.width for s in samples]
        third = max(1, len(widths) // 3)
        first, last = median(widths[:third]), median(widths[-third:])
        ratio = last / first if first else 1.0
        if ratio >= self.cfg.grow_ratio:
            return "entry_confirmed"
        if ratio <= self.cfg.shrink_ratio:
            return "exit_confirmed"
        return None

    def _finish(self) -> list[Event]:
        samples = self.samples
        reads = self.reads
        self._reset()
        if len(samples) < self.cfg.min_samples:
            self.too_short += 1
            self.notes.append(f"проезд отброшен: детекций {len(samples)} < {self.cfg.min_samples}")
            return []
        kind = self._direction(samples)
        if kind is None:
            self.unclear += 1
            first, last = samples[0].width, samples[-1].width
            self.notes.append(
                f"проезд без ясного направления: номер {first:.0f} -> {last:.0f} px, "
                f"детекций {len(samples)}"
            )
            return []
        best = max(samples, key=lambda s: s.width * s.conf)
        result = plates.resolve_plate(reads, self._known_index())
        t = (samples[0].t + samples[-1].t) / 2
        return [Event(kind, t, result, best.frame)]

    # ---- основной шаг ----------------------------------------------------------

    def update(self, t: float, det: Detection | None, frame=None, vehicle=None) -> list[Event]:
        """vehicle не используется (проверка кадром для ворот не нужна), параметр - для
        совместимости с BayTracker."""
        if det is not None and (det.conf < self.cfg.min_conf or det.width < self.cfg.min_width):
            det = None
        if not self.samples:
            if det is not None:
                self._add(t, det, frame)
            return []
        gap = t - self.samples[-1].t
        if det is None:
            return self._finish() if gap >= self.cfg.gap_sec else []
        if gap > self.cfg.gap_sec or self._is_jump(det):
            events = self._finish()
            self._add(t, det, frame)
            return events
        self._add(t, det, frame)
        return []

    def flush(self) -> list[Event]:
        """Закончить идущий след сейчас (остановка узла, обрыв потока)."""
        return self._finish() if self.samples else []


class MotionGate:
    """Простой датчик движения: пока в кадре ничего не происходит, номер не ищем (экономит процессор).

    Среднее абсолютное изменение серого кадра 64x36 относительно прошлого кадра; threshold <= 0 -
    выключен (всегда «работаем»). После движения или найденного номера держим полную частоту
    hold_sec секунд: проезд длится 1-3 секунды, пропустить его нельзя."""

    def __init__(self, threshold: float = 0.0, hold_sec: float = 4.0):
        self.threshold = threshold
        self.hold_sec = hold_sec
        self.prev: np.ndarray | None = None
        self.hold_until = -1e18

    def active(self, t: float, frame) -> bool:
        if self.threshold <= 0:
            return True
        small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 36)).astype(np.int16)
        moved = self.prev is None or float(np.abs(small - self.prev).mean()) >= self.threshold
        self.prev = small
        if moved:
            self.hold_until = t + self.hold_sec
        return t <= self.hold_until

    def note_detection(self, t: float) -> None:
        """Номер найден - держим полную частоту ещё hold_sec."""
        self.hold_until = max(self.hold_until, t + self.hold_sec)
