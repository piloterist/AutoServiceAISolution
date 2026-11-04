r"""Журнал чтения номера кадр за кадром и отчёт о точности.

Зачем: у входящих машин номер часто находится по заказ-наряду даже при неточном чтении, и по
итоговому событию не видно, стала ли модель читать лучше или ей помогла база. Поэтому узел
пишет в captures/reads/<дата>.jsonl каждое прочтение (на 12, 8, 5, 3 м) БЕЗ помощи базы, плюс
решение о въезде/выезде: что прочитано (`raw`) и что в итоге записано (`plate`, matched).

Отчёт: .venv\Scripts\python.exe read_log.py [--date 2026-11-04] [--truth Е560КС977]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

import bay_events as be
import plates

LOG_DIR = be.ROOT / "captures" / "reads"
TOP_PER_SLOT = 3
# Размер номера в кадре -> примерное расстояние (4 мм объектив, по замерам 2026-11-04).
BUCKETS = [(260, "3 м (>=260 px)"), (160, "5 м (160-260)"), (105, "8 м (105-160)"), (0, "12 м (<105)")]
ROLLING = 5  # окно для «накопленного» чтения: последние N кадров


def bucket(width: float) -> str:
    return next(label for limit, label in BUCKETS if width >= limit)


class ReadLog:
    def __init__(self, camera_id: str, directory: Path = LOG_DIR):
        self.camera_id, self.directory = camera_id, directory
        directory.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict) -> None:
        record["cam"] = self.camera_id
        record["ts"] = datetime.now().astimezone().isoformat(timespec="milliseconds")
        path = self.directory / f"{datetime.now():%Y-%m-%d}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(self, track: int, state: str, det) -> None:
        record = {
            "type": "read", "track": track, "state": state, "w": round(det.width, 1),
            "cx": round(det.cx), "cy": round(det.cy), "dconf": round(det.conf, 3),
            "text": None, "c6": None, "top": None,
        }  # fmt: skip
        if det.probs is not None:
            text, confidences = plates.decode(det.probs)
            record["text"], record["c6"] = text, round(min(confidences[: plates.PREFIX_LEN]), 3)
            record["top"] = [
                [[plates.ALPHABET[i], round(float(row[i]), 3)] for i in np.argsort(row)[::-1][:TOP_PER_SLOT]]
                for row in det.probs
            ]  # fmt: skip
        self._write(record)

    def decision(self, track: int, event) -> None:
        r = event.result
        self._write(
            {
                "type": "decision", "track": track, "kind": event.kind, "plate": r.plate,
                "raw": r.raw, "matched": r.matched, "wo": r.work_order_number,
                "confidence": r.confidence, "reliable": r.reliable,
            }
        )  # fmt: skip


# ---- отчёт -------------------------------------------------------------------


def _matrix(top: list) -> np.ndarray:
    matrix = np.zeros((plates.SLOTS, len(plates.ALPHABET)))
    for slot, items in enumerate(top):
        for char, prob in items:
            matrix[slot, plates.ALPHABET.index(char)] = prob
    return matrix


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _drop_stale_prelude(reads: list[dict]) -> list[dict]:
    """Прочтения до начала следа (машина ещё далеко, трекер не запущен) принадлежат следу,
    только если они не старше минуты до первого кадра в состоянии не EMPTY."""
    started = next((r for r in reads if r["state"] != "EMPTY"), None)
    if started is None:
        return []
    limit = datetime.fromisoformat(started["ts"]).timestamp() - 60
    return [r for r in reads if r["state"] != "EMPTY" or datetime.fromisoformat(r["ts"]).timestamp() >= limit]


def report(records: list[dict], truth: str | None = None) -> str:
    tracks: dict[int, list[dict]] = defaultdict(list)
    for rec in records:
        tracks[rec["track"]].append(rec)
    lines = []
    for track, recs in sorted(tracks.items()):
        decisions = [r for r in recs if r["type"] == "decision"]
        reads = [r for r in recs if r["type"] == "read"]
        reads = _drop_stale_prelude(reads)
        entries = [d for d in decisions if d["kind"] == "entry_confirmed"]
        expected = plates.normalize_read(truth) if truth else (entries[0]["plate"] if entries else None)
        if not reads or expected is None:
            continue
        lines.append(f"\n=== след {track}: {reads[0]['ts'][11:19]} - {reads[-1]['ts'][11:19]}, эталон {expected}")
        stats: dict[str, list] = {label: [0, 0, 0, 0] for _, label in BUCKETS}  # кадров, first6, полностью, накопл.first6
        window: list[np.ndarray] = []
        for rec in reads:
            if rec["top"] is None:
                continue
            row = stats[bucket(rec["w"])]
            row[0] += 1
            row[1] += rec["text"][: plates.PREFIX_LEN] == expected[: plates.PREFIX_LEN]
            row[2] += rec["text"] == expected
            window = (window + [_matrix(rec["top"])])[-ROLLING:]
            aggregated = plates.decode(np.mean(window, axis=0))[0]
            row[3] += aggregated[: plates.PREFIX_LEN] == expected[: plates.PREFIX_LEN]
        lines.append(f"{'расстояние':18s} {'кадров':>7s} {'первые 6':>9s} {'номер целиком':>14s} {'накопл. (5 кадров) первые 6':>28s}")
        for _, label in BUCKETS:
            n, first6, full, rolling = stats[label]
            if n:
                lines.append(f"{label:18s} {n:7d} {first6 * 100 // n:8d}% {full * 100 // n:13d}% {rolling * 100 // n:27d}%")
        for d in decisions:
            assisted = d["matched"] and d["raw"] != d["plate"]
            lines.append(
                f"  решение {d['kind']}: записано {d['plate']}, прочитано без базы {d['raw']}, "
                f"по базе: {'да' if d['matched'] else 'нет'}"
                + (f" (ЗН {d['wo']})" if d["wo"] else "")
                + (" - НОМЕР ИСПРАВЛЕН БАЗОЙ" if assisted else "")
            )
    return "\n".join(lines) if lines else "Нет данных для отчёта."


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--date", default=f"{datetime.now():%Y-%m-%d}")
    parser.add_argument("--truth", help="правильный номер (иначе - записанный во въезде)")
    parser.add_argument("--dir", type=Path, default=LOG_DIR, help="папка журнала")
    args = parser.parse_args()
    path = args.dir / f"{args.date}.jsonl"
    if not path.exists():
        print(f"Нет журнала за {args.date}: {path}")
        return 1
    print(report(load(path), args.truth))
    return 0


if __name__ == "__main__":
    sys.exit(main())
