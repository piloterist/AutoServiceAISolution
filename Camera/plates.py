"""Российские госномера: чтение по вероятностям позиций, голосование по серии кадров,
сверка с номерами из заказ-нарядов 1С.

OCR-модель (fast-plate-ocr, cct-xs-v2) для каждой из 10 позиций выдаёт вероятности символов
алфавита `0-9A-Z_` (`_` - пусто). Строку из неё не собираем, а декодируем по шаблону
российского номера: Б Ц Ц Ц Б Б + регион 2-3 цифры. Буквы - только 12 кириллических,
похожих на латиницу (A B E K M H O P C T Y X), поэтому позиция «буква» не может оказаться
цифрой и наоборот, а пропущенный символ не сдвигает остальные. Регион проверить нельзя
(там бывает 2 и 3 цифры), поэтому надёжность номера определяют первые 6 символов.

Вероятности суммируются по кадрам серии (усреднение лучше голосования строками).
Чистая логика без камеры и сети - тестируется в test_plates.py.
"""

from dataclasses import dataclass

import numpy as np

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
SLOTS = 10
LAT_LETTERS = "ABEKMHOPCTYX"
CYR_LETTERS = "АВЕКМНОРСТУХ"  # в том же порядке, что и LAT_LETTERS
_LAT_TO_CYR = str.maketrans(LAT_LETTERS, CYR_LETTERS)
_CYR_TO_LAT = str.maketrans(CYR_LETTERS, LAT_LETTERS)

_INDEX = {char: i for i, char in enumerate(ALPHABET)}
_LET = [_INDEX[c] for c in LAT_LETTERS]
_DIG = [_INDEX[c] for c in "0123456789"]
_PAD = _INDEX["_"]
# Допустимые символы по позициям: Б Ц Ц Ц Б Б Ц Ц [Ц|пусто] пусто
CLASSES = [_LET, _DIG, _DIG, _DIG, _LET, _LET, _DIG, _DIG, _DIG + [_PAD], [_PAD]]
PREFIX_LEN = 6

# Надёжным считаем номер, у которого каждая из первых 6 позиций уверенно определена.
RELIABLE_MIN_CONFIDENCE = 0.80
# Известный номер принимается, если прочитанное ему соответствует в среднем не хуже этого
# и он заметно лучше следующего кандидата.
MATCH_MIN_SCORE = 0.70
MATCH_MARGIN = 0.08
# Регион читается хуже и значит меньше, чем 6 символов основной части.
REGION_WEIGHT = 0.5


def normalize_read(text: str | None) -> str:
    """Текст номера -> заглавная кириллица без пробелов (латинские двойники заменяются)."""
    cleaned = "".join((text or "").split()).upper().translate(_LAT_TO_CYR)
    return "".join(ch for ch in cleaned if ch.isalnum())


class SlotReads:
    """Взвешенная сумма матриц вероятностей (SLOTS x ALPHABET) по кадрам серии."""

    def __init__(self) -> None:
        self.total: np.ndarray | None = None
        self.weight = 0.0
        self.count = 0

    def add(self, probs: np.ndarray, weight: float) -> None:
        if weight <= 0:
            return
        self.total = probs * weight if self.total is None else self.total + probs * weight
        self.weight += weight
        self.count += 1

    def clear(self) -> None:
        self.total, self.weight, self.count = None, 0.0, 0

    def mean(self) -> np.ndarray | None:
        return None if self.total is None else self.total / self.weight


def decode(mean: np.ndarray) -> tuple[str, list[float]]:
    """Матрица вероятностей -> (номер кириллицей, уверенность по каждой позиции 0..1)."""
    chars, confidences = [], []
    for slot, allowed in enumerate(CLASSES):
        sub = mean[slot, allowed]
        k = int(sub.argmax())
        chars.append(ALPHABET[allowed[k]])
        confidences.append(float(sub[k] / max(float(sub.sum()), 1e-9)))
    return "".join(chars).replace("_", "").translate(_LAT_TO_CYR), confidences


@dataclass(frozen=True)
class PlateResult:
    plate: str | None
    confidence: float  # 0..1; у известного номера - соответствие прочитанному, иначе слабейшая из первых 6 позиций
    matched: bool  # номер найден среди известных (заказ-наряды 1С)
    work_order_number: str | None = None
    summary: str = ""  # что прочитано, для заметки к событию
    raw: str | None = None  # что прочитано камерой БЕЗ помощи базы (для сравнения с plate)

    @property
    def reliable(self) -> bool:
        """Не требует проверки человеком: известный номер или уверенные первые 6 символов."""
        return self.plate is not None and (self.matched or self.confidence >= RELIABLE_MIN_CONFIDENCE)


class KnownPlates:
    """Номера из заказ-нарядов в виде индексов алфавита - сверка сразу по всем номерам."""

    def __init__(self, plates: dict[str, str] | None = None) -> None:
        items = [(p, n) for p, n in (plates or {}).items() if _valid_known(p)]
        self.plates = [p for p, _ in items]
        self.numbers = [n for _, n in items]
        self.index = np.zeros((len(items), 9), dtype=np.int64)
        self.weights = np.zeros((len(items), 9))
        for row, (plate, _) in enumerate(items):
            lat = plate.translate(_CYR_TO_LAT)
            for slot in range(9):
                char = lat[slot] if slot < len(lat) else "_"
                self.index[row, slot] = _INDEX[char]
                self.weights[row, slot] = 1.0 if slot < PREFIX_LEN else REGION_WEIGHT

    def __len__(self) -> int:
        return len(self.plates)

    def best(self, mean: np.ndarray) -> tuple[float, float, int] | None:
        """(лучшая оценка, оценка второго, индекс лучшего) или None, если база пуста."""
        if not self.plates:
            return None
        per_slot = mean[np.arange(9), self.index]  # (N, 9)
        scores = (per_slot * self.weights).sum(axis=1) / self.weights.sum(axis=1)
        order = np.argsort(scores)[::-1]
        best = int(order[0])
        second = float(scores[order[1]]) if len(order) > 1 else 0.0
        return float(scores[best]), second, best


def _valid_known(plate: str) -> bool:
    lat = plate.translate(_CYR_TO_LAT)
    if len(lat) not in (8, 9) or any(ch not in _INDEX for ch in lat):
        return False
    return all(
        lat[slot] in "0123456789" if slot in (1, 2, 3, 6, 7, 8) else lat[slot] in LAT_LETTERS
        for slot in range(len(lat))
    )


def resolve_plate(reads: SlotReads, known: KnownPlates | None = None) -> PlateResult:
    """Итоговый номер по серии кадров.

    1) Если известный номер подходит под прочитанное - берём его (matched=True).
    2) Иначе - то, что декодировано по шаблону; надёжность - по первым 6 символам.
    """
    mean = reads.mean()
    if mean is None:
        return PlateResult(None, 0.0, False, summary="номер не прочитан")
    text, confidences = decode(mean)
    prefix_confidence = min(confidences[:PREFIX_LEN])
    summary = (
        f"прочитано: {text} (первые 6 символов: {prefix_confidence:.0%}, "
        f"кадров: {reads.count})"
    )
    if known is not None:
        found = known.best(mean)
        if found is not None:
            score, second, row = found
            if score >= MATCH_MIN_SCORE and score - second >= MATCH_MARGIN:
                return PlateResult(
                    known.plates[row], round(score, 3), True, known.numbers[row], summary, text
                )
    return PlateResult(text, round(prefix_confidence, 3), False, None, summary, text)
