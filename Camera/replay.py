r"""Прогон записанных кадров через то же распознавание и трекер, что и в узле - без камеры.

    .venv\Scripts\python.exe replay.py --known "Е560КС977=ЗН-тест" \
        drive_in_day:3:0.9 8m_day:1:1.0 12m_day:1:1.0 drive_out_day:2:0.6

Каждый аргумент - папка из captures/dataset (по началу имени) : шаг (брать каждый N-й кадр)
: секунд между взятыми кадрами (виртуальное время). Серии идут одна за другой.
"""

import argparse
import sys
from pathlib import Path

import cv2

import bay_events as be
from bay_tracker import EMPTY, BayTracker, TrackerConfig
from read_log import ReadLog
from plate_pipeline import PlatePipeline

DATASET = be.ROOT / "captures" / "dataset"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("segments", nargs="+")
    parser.add_argument("--known", action="append", default=[], help="номер=ЗН, можно несколько раз")
    parser.add_argument("--roi", type=float, nargs=4)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--log-dir", type=Path, help="писать журнал чтения номера (см. read_log.py)")
    args = parser.parse_args()

    known = dict(item.split("=", 1) for item in args.known)
    from plates import normalize_read

    known = {normalize_read(k): v for k, v in known.items()}
    from plates import KnownPlates

    known = KnownPlates(known)
    pipeline = PlatePipeline(roi=args.roi)
    tracker = None
    t = 0.0
    readlog = ReadLog("replay", args.log_dir) if args.log_dir else None
    track = 0
    for segment in args.segments:
        label, step, dt = segment.split(":")
        folders = sorted(p for p in DATASET.iterdir() if p.name.startswith(label) and any(p.iterdir()))
        files = sorted(folders[-1].glob("*.jpg"))[:: int(step)]
        print(f"== {folders[-1].name}: {len(files)} кадров, шаг {dt} с")
        for path in files:
            frame = cv2.imread(str(path))
            if tracker is None:
                tracker = BayTracker(TrackerConfig(frame_width=frame.shape[1]), known=known)
            det = pipeline.detect(frame)
            if args.verbose:
                shown = f"w={det.width:.0f} conf={det.conf:.2f}" if det else "-"
                print(f"  t={t:6.1f} {tracker.state:8} {shown}")
            before = tracker.state
            events = tracker.update(t, det, frame)
            if before == EMPTY and tracker.state != EMPTY:
                track += 1
            if readlog and det is not None:
                readlog.read(track + (tracker.state == EMPTY), tracker.state, det)
            for event in events:
                if readlog:
                    readlog.decision(track, event)
                r = event.result
                print(
                    f"  >>> t={event.t:6.1f} {event.kind}: {r.plate} "
                    f"conf={r.confidence} по базе={r.matched} надёжно={r.reliable} {r.work_order_number or ''} | {r.summary}"
                )
            t += float(dt)
    print(f"итоговое состояние: {tracker.state if tracker else '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
