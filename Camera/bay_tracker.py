"""Состояние бокса по номеру автомобиля в кадре: въезд и выезд.

Камера смотрит на автомобиль спереди, и номер виден и при заезде, и при выезде задним
ходом (машина удаляется, номер уменьшается). Поэтому всё решается по одному «следу»
номера - его размеру (расстояние) и положению:

    EMPTY    -> номер появился и достаточно крупный              -> APPROACH
    APPROACH -> номер крупный, стоит на месте несколько секунд   -> PARKED  (entry_confirmed)
                номер пропал, не став на месте                   -> EMPTY   (проезд мимо)
    PARKED   -> номер заметно уменьшился или сместился вбок      -> LEAVING
                номер пропал без этого (человек, подъёмник)      -> остаёмся PARKED
    LEAVING  -> номера нет exit_hold_sec секунд                  -> EMPTY   (exit_confirmed)
                машина снова стоит на месте (переставили)        -> PARKED  (или выезд+въезд, если номер другой)

Правила проекта:
- выезд никогда не выводится из простого исчезновения номера - нужно увидеть, что машина
  уходит; кадр выезда - самый дальний, где номер ещё виден (машина у ворот), чтобы было видно,
  что она уехала, а не сдвинулась в боксе;
- номер читается только по кадрам, когда машина уже стоит (при движении кадры смазаны), а при
  выезде не перечитывается: уезжает та же машина, что заехала;
- вертикальное смещение номера игнорируется (подъёмник).

Чистая логика: время и детекции подаёт вызывающий, кадры только передаются в события.
"""

from collections import deque
from dataclasses import dataclass
from statistics import median

import numpy as np

import plates

EMPTY, APPROACH, PARKED, LEAVING = "EMPTY", "APPROACH", "PARKED", "LEAVING"
LEAVE_VOTES = 3  # подряд кадров «уезжает», чтобы не реагировать на один сбой детектора
FAR_FRAME_GAP_SEC = 5.0  # пауза без номера дольше этой: появившийся номер - другая машина, снимок выезда не трогаем


@dataclass
class Detection:
    cx: float  # центр номера, пиксели кадра
    cy: float
    width: float  # ширина номера, пиксели кадра
    conf: float  # уверенность детектора
    probs: np.ndarray | None = None  # вероятности символов по позициям (plates.SLOTS x ALPHABET)


@dataclass
class TrackerConfig:
    frame_width: float = 2560.0
    min_conf: float = 0.35
    approach_min_width: float = 100.0  # меньше - номер ещё слишком мелкий, не считаем
    park_min_width: float = 150.0  # номер должен быть не мельче (машина у подъёмника)
    park_still_sec: float = 4.0
    still_shift_frac: float = 0.012  # допустимое смещение по горизонтали (доля ширины кадра)
    still_width_ratio: float = 0.12  # допустимое изменение размера номера
    # Чтение номера идёт только по кадрам неподвижной машины: заметное смещение сбрасывает серию.
    move_reset_frac: float = 0.008
    move_reset_ratio: float = 0.08
    leave_width_ratio: float = 0.75  # номер мельче этой доли от стояночного - уезжает
    leave_shift_frac: float = 0.06
    exit_hold_sec: float = 20.0  # номера нет столько секунд после «уезжает» - выезд
    # Выезд подтверждается, только если перед пропажей номер успел сильно уменьшиться (машина
    # уехала вдаль), а не исчез на большом размере (номер закрыли руками, подъёмник, сбой): меньше
    # этой доли от стояночного размера. Иначе ждём дольше и подтверждаем выезд лишь через
    # exit_hold_max_sec без номера.
    exit_far_ratio: float = 0.55
    exit_hold_max_sec: float = 600.0
    # Второй голос при выезде: детектор машин (vehicle_presence.py). Когда по номеру выезд пора
    # подтверждать, проверяем кадр: машина всё ещё в боксе - выезд ложный. Подтверждаем, только
    # когда подряд vehicle_empty_checks проверок (раз в несколько секунд) не нашли машину;
    # нашли машину vehicle_back_sec подряд - возвращаемся в PARKED. Нет ответов проверки
    # vehicle_wait_sec - работаем как без неё, чтобы сбой модели ничего не блокировал.
    vehicle_check: bool = False
    vehicle_empty_checks: int = 3
    vehicle_back_sec: float = 30.0
    vehicle_wait_sec: float = 120.0
    lost_timeout_sec: float = 6.0
    min_reads: int = 5  # сколько прочтений неподвижной машины нужно для решения о въезде
    # Если номер за park_still_sec не стал надёжным, ждём ещё столько секунд (больше кадров),
    # и только потом подтверждаем въезд с пометкой «нужна проверка».
    extra_read_sec: float = 8.0


@dataclass
class Event:
    kind: str  # entry_confirmed / exit_confirmed
    t: float
    result: plates.PlateResult
    frame: object | None
    extra: str = ""  # пометка для журнала события (например, выезд подтверждён проверкой кадра)


class BayTracker:
    def __init__(
        self,
        config: TrackerConfig,
        known: plates.KnownPlates | dict[str, str] | None = None,
        occupied_plate: str | None = None,
    ):
        self.cfg = config
        self.known = known
        self.state = EMPTY
        self.parked: plates.PlateResult | None = None
        self.ref: tuple[float, float] | None = None  # (cx, width) машины на месте
        self._reset_track()
        if occupied_plate:  # узел перезапустили, а бокс уже занят - второй въезд не пишем
            self.state = PARKED
            self.parked = plates.PlateResult(occupied_plate, 1.0, True)

    # ---- служебное -------------------------------------------------------------

    def _known_index(self) -> plates.KnownPlates | None:
        if self.known is None or isinstance(self.known, plates.KnownPlates):
            return self.known
        cached = getattr(self, "_known_cache", None)
        if cached is None or cached[0] is not self.known or cached[1] != len(self.known):
            cached = (self.known, len(self.known), plates.KnownPlates(self.known))
            self._known_cache = cached
        return cached[2]

    def _reset_track(self) -> None:
        self.history: deque[tuple[float, float, float]] = deque()  # (t, cx, width)
        self.reads = plates.SlotReads()
        self.still_since: float | None = None  # когда машина встала (последнее заметное движение)
        self.prev: tuple[float, float] | None = None  # (cx, width) прошлого кадра
        self.last_seen: float | None = None
        self.best_frame = None
        self.best_score = 0.0
        self.leave_votes = 0
        self.leave_t: float | None = None
        self.leave_frame = None
        self.far_width = float("inf")
        self.far_frame = None
        self.far_closed = False  # снимок выезда закрыт: номер снова виден после паузы - другая машина
        self._reset_vehicle()

    def _reset_vehicle(self) -> None:
        self.empty_checks = 0
        self.vehicle_since: float | None = None  # с какого момента проверки видят машину
        self.exit_ready_since: float | None = None

    def _observe(self, t: float, det: Detection, frame) -> None:
        self.last_seen = t
        self.history.append((t, det.cx, det.width))
        horizon = t - self.cfg.park_still_sec - 1.0
        while self.history and self.history[0][0] < horizon:
            self.history.popleft()
        moved = self.prev is not None and (
            abs(det.cx - self.prev[0]) > self.cfg.move_reset_frac * self.cfg.frame_width
            or abs(det.width - self.prev[1]) > self.cfg.move_reset_ratio * self.prev[1]
        )
        if moved or self.still_since is None:
            self.reads.clear()
            self.still_since = t
            self.best_frame, self.best_score = None, 0.0
        self.prev = (det.cx, det.width)
        if det.probs is not None and det.width >= self.cfg.approach_min_width:
            self.reads.add(det.probs, det.width / 100.0 * det.conf)
        score = det.width * det.conf
        if frame is not None and score > self.best_score:
            self.best_score, self.best_frame = score, frame

    def _still(self, t: float, det: Detection) -> bool:
        window = [h for h in self.history if h[0] >= t - self.cfg.park_still_sec]
        covers = bool(window) and t - self.history[0][0] >= self.cfg.park_still_sec * 0.9
        if not covers or len(window) < 3:
            return False
        shift = self.cfg.still_shift_frac * self.cfg.frame_width
        return all(
            abs(cx - det.cx) <= shift
            and abs(w - det.width) <= self.cfg.still_width_ratio * det.width
            for _, cx, w in window
        )

    def _set_reference(self, t: float) -> None:
        window = [h for h in self.history if h[0] >= t - self.cfg.park_still_sec] or list(
            self.history
        )
        self.ref = (median(h[1] for h in window), median(h[2] for h in window))

    def _read_result(self, t: float) -> plates.PlateResult | None:
        """Номер по кадрам неподвижной машины, когда его пора подтверждать; иначе None."""
        assert self.still_since is not None
        if self.reads.count < self.cfg.min_reads:
            return None
        result = plates.resolve_plate(self.reads, self._known_index())
        waited = t - self.still_since
        if result.reliable or waited >= self.cfg.park_still_sec + self.cfg.extra_read_sec:
            return result
        return None

    def _entry(self, t: float, result: plates.PlateResult) -> Event:
        self.state = PARKED
        self.parked = result
        self._set_reference(t)
        frame = self.best_frame
        self.leave_votes, self.leave_t, self.leave_frame = 0, None, None
        return Event("entry_confirmed", t, result, frame)

    # ---- основной шаг ----------------------------------------------------------

    def update(
        self, t: float, det: Detection | None, frame=None, vehicle: bool | None = None
    ) -> list[Event]:
        """vehicle: итог свежей проверки «в боксе есть машина» (True - есть, False - нет); None -
        новой проверки нет (её просят, когда exit_check_due())."""
        if det is not None and det.conf < self.cfg.min_conf:
            det = None
        if self.state == EMPTY:
            return self._update_empty(t, det, frame)
        if self.state == APPROACH:
            return self._update_approach(t, det, frame)
        if self.state == PARKED:
            return self._update_parked(t, det, frame)
        return self._update_leaving(t, det, frame, vehicle)

    def _update_empty(self, t, det, frame) -> list[Event]:
        if det is not None and det.width >= self.cfg.approach_min_width:
            self._reset_track()
            self.state = APPROACH
            self._observe(t, det, frame)
        return []

    def _update_approach(self, t, det, frame) -> list[Event]:
        if det is None:
            if self.last_seen is not None and t - self.last_seen > self.cfg.lost_timeout_sec:
                self.state = EMPTY  # проезд мимо или номер потерян, не встав на месте
                self._reset_track()
            return []
        self._observe(t, det, frame)
        if det.width >= self.cfg.park_min_width and self._still(t, det):
            result = self._read_result(t)
            if result is not None:
                return [self._entry(t, result)]
        return []

    def _is_leaving(self, det: Detection) -> bool:
        assert self.ref is not None
        ref_cx, ref_w = self.ref
        return (
            det.width < ref_w * self.cfg.leave_width_ratio
            or abs(det.cx - ref_cx) > self.cfg.leave_shift_frac * self.cfg.frame_width
        )

    def _update_parked(self, t, det, frame) -> list[Event]:
        if det is None or det.width < self.cfg.approach_min_width * 0.4:
            return []  # номер не виден (человек, подъёмник): выезд из этого не выводим
        if self.ref is None:  # после перезапуска узла: первое наблюдение - эталон
            if det.width >= self.cfg.approach_min_width:
                self.ref = (det.cx, det.width)
            return []
        if not self._is_leaving(det):
            self.leave_votes, self.leave_frame = 0, None
            return []
        if self.leave_votes == 0:
            self.leave_frame = frame
        self.leave_votes += 1
        if self.leave_votes >= LEAVE_VOTES:
            self.state = LEAVING
            self.leave_t = t
            self.leave_votes = 0
            self.history.clear()
            self.reads.clear()
            self.still_since, self.prev = None, None
            self.last_seen = t
            self.best_frame, self.best_score = None, 0.0
            self.far_width, self.far_frame = det.width, frame
            self.far_closed = False
            self._reset_vehicle()
        return []

    def _went_far(self) -> bool:
        """Номер перед пропажей стал мелким - машина уехала вдаль, а не пропал на месте."""
        if self.ref is None:
            return True
        return self.far_width <= self.ref[1] * self.cfg.exit_far_ratio

    def _exit_frame(self):
        """Самый дальний кадр с номером: машина у ворот, а не просто сдвинулась в боксе."""
        return self.far_frame if self.far_frame is not None else self.leave_frame

    def exit_check_due(self, t: float) -> bool:
        """Номера нет, и выезд по номеру пора подтверждать: нужна проверка «машина в боксе»."""
        if not self.cfg.vehicle_check or self.state != LEAVING or self.last_seen is None:
            return False
        return self._exit_ready(t - self.last_seen)

    def _exit_ready(self, absent: float) -> bool:
        return absent >= self.cfg.exit_hold_sec and (
            self._went_far() or absent >= self.cfg.exit_hold_max_sec
        )

    def _vehicle_blocks_exit(self, t: float, vehicle: bool | None) -> bool:
        """True - выезд пока подтверждать нельзя (ждём проверку или машина ещё в боксе)."""
        if not self.cfg.vehicle_check:
            return False
        if self.exit_ready_since is None:
            self.exit_ready_since = t
        if vehicle is None:  # проверки нет: ждём, но не бесконечно
            return t - self.exit_ready_since < self.cfg.vehicle_wait_sec
        self.exit_ready_since = t  # проверка отвечает - ожидание с начала
        if vehicle:
            self.empty_checks = 0
            if self.vehicle_since is None:
                self.vehicle_since = t
            return True
        self.vehicle_since = None
        self.empty_checks += 1
        return self.empty_checks < self.cfg.vehicle_empty_checks

    def _back_to_parked(self) -> None:
        """Машина всё это время стояла в боксе: «уезжает» было ложным."""
        self.state = PARKED  # эталон (положение и размер номера на месте) остаётся прежним
        self.history.clear()
        self.still_since, self.prev = None, None
        self.leave_votes, self.leave_t, self.leave_frame = 0, None, None
        self.far_width, self.far_frame = float("inf"), None
        self.far_closed = False
        self._reset_vehicle()

    def _update_leaving(self, t, det, frame, vehicle=None) -> list[Event]:
        if det is None:
            assert self.last_seen is not None and self.leave_t is not None
            absent = t - self.last_seen
            if self._exit_ready(absent):
                if self._vehicle_blocks_exit(t, vehicle):
                    if self.vehicle_since is not None and (
                        t - self.vehicle_since >= self.cfg.vehicle_back_sec
                    ):
                        self._back_to_parked()
                    return []
                event = Event(
                    "exit_confirmed",
                    self.last_seen,
                    self.parked,
                    self._exit_frame(),
                    extra="машины в боксе нет (проверка кадром)" if vehicle is False else "",
                )
                self.state = EMPTY
                self.parked, self.ref = None, None
                self._reset_track()
                return [event]
            return []
        self._reset_vehicle()  # номер снова виден: проверки машины начинаются заново
        if self.last_seen is not None and t - self.last_seen > FAR_FRAME_GAP_SEC:
            # Номер пропадал надолго: это уже другая машина. Её кадры не должны подменять
            # снимок выезда уехавшей (2026-11-20: на фото выезда Peugeot стояла вошедшая Audi).
            self.far_closed = True
        self._observe(t, det, frame)
        if not self.far_closed and det.width <= self.far_width:
            self.far_width = det.width
            if frame is not None:
                self.far_frame = frame
        if det.width >= self.cfg.park_min_width and self._still(t, det):
            result = self._read_result(t)
            if result is None:
                return []
            # Сравниваем серию и цифры без региона: по базе номер мог быть дополнен («К679ОО777»),
            # а перечитанный остаётся «К679ОО77». Иначе та же машина давала бы ложные выезд+въезд.
            # Ненадёжное чтение другого номера (закрыт капотом, людьми, плохой ракурс) - это не новая
            # машина: выезд и въезд «другой» записываем, только если номер считан уверенно.
            same_car = (
                self.parked is None
                or result.plate[:6] == self.parked.plate[:6]
                or not result.reliable
            )
            if same_car:
                self.state = PARKED  # переставили на другое место того же бокса
                self._set_reference(t)
                self.leave_votes, self.leave_t, self.leave_frame = 0, None, None
                self.far_width, self.far_frame = float("inf"), None
                self.far_closed = False
                return []
            exit_event = Event("exit_confirmed", self.leave_t, self.parked, self._exit_frame())
            self.parked = None
            return [exit_event, self._entry(t, result)]
        return []
