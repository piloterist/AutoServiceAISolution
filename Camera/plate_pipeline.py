"""Кадр -> номер: детектор номера (YOLOv9, ONNX) + OCR (CCT-xs-v2, ONNX), оба на CPU.

Берётся самый крупный номер в кадре. Детектор можно ограничить областью кадра
(detect_roi, доли 0..1: [x1, y1, x2, y2]) - так далёкие номера крупнее для сети.
OCR отдаёт не строку, а вероятности символов по позициям (plates.py декодирует их по шаблону
российского номера и суммирует по кадрам). На размеченных кадрах эта модель с плотной
вырезкой читала первые 6 символов в 93-100% кадров на 3-5 м (прежняя cct-s-v1 - в 3-70%).
Модели скачиваются при первом запуске в кэш библиотек.
"""

import logging
import warnings

import cv2
import numpy as np

import plates
from bay_tracker import Detection

DETECTOR_MODEL = "yolo-v9-t-640-license-plate-end2end"
OCR_MODEL = "cct-xs-v2-global-model"
OCR_MIN_WIDTH = 80  # мельче номер не читаем: OCR на нём только шумит
# Доли ширины/высоты номера, добавляемые к рамке детектора. Плотная вырезка читалась лучше
# широкой; усредняем два варианта.
CROP_PADS = (0.0, 0.05)


class PlatePipeline:
    def __init__(self, roi: list[float] | None = None, detector_model: str = DETECTOR_MODEL):
        warnings.filterwarnings("ignore")
        logging.disable(logging.WARNING)
        import onnxruntime as ort

        ort.set_default_logger_severity(4)  # без шума про «merge shape info»
        from fast_plate_ocr import LicensePlateRecognizer
        from open_image_models import create_detector

        # По умолчанию onnxruntime берёт все ядра и крутит их вхолостую: на ноутбуке кадр стоил
        # ~2 с процессорного времени вместо ~0,12 с. Один поток без холостого ожидания: так и
        # быстрее в сумме, и камеры (по потоку на камеру) не мешают друг другу.
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.roi = roi if roi and len(roi) == 4 else None
        self.detector = create_detector(detector_model, sess_options=options)
        self.ocr = LicensePlateRecognizer(OCR_MODEL, sess_options=options)

    def _probs(self, rgb_crop) -> np.ndarray:
        # Внутренние функции библиотеки (версия закреплена в requirements.txt): нужны сырые
        # вероятности, а публичный run() отдаёт только готовую строку.
        from fast_plate_ocr.inference.plate_recognizer import (
            _load_image_from_source,
            preprocess_image,
        )

        x = preprocess_image(_load_image_from_source(rgb_crop, self.ocr.config))
        out = self.ocr.model.run([self.ocr.plate_output_name], {"input": x})[0]
        return np.asarray(out).reshape(self.ocr.config.max_plate_slots, len(plates.ALPHABET))

    def detect(self, frame) -> Detection | None:
        height, width = frame.shape[:2]
        x0 = y0 = 0
        view = frame
        if self.roi:
            x0, y0 = int(self.roi[0] * width), int(self.roi[1] * height)
            view = frame[y0 : int(self.roi[3] * height), x0 : int(self.roi[2] * width)]
        results = self.detector.predict(view)
        if not results:
            return None
        best = max(results, key=lambda r: (r.bounding_box.x2 - r.bounding_box.x1) * r.confidence)
        box = best.bounding_box
        plate_w, plate_h = box.x2 - box.x1, box.y2 - box.y1
        probs = None
        if plate_w >= OCR_MIN_WIDTH:
            vh, vw = view.shape[:2]
            variants = []
            for pad in CROP_PADS:
                pad_x, pad_y = int(pad * plate_w), int(pad * plate_h)
                crop = view[
                    max(0, box.y1 - pad_y) : min(vh, box.y2 + pad_y),
                    max(0, box.x1 - pad_x) : min(vw, box.x2 + pad_x),
                ]
                if crop.size:
                    variants.append(self._probs(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
            if variants:
                probs = np.mean(variants, axis=0)
        return Detection(
            cx=x0 + (box.x1 + box.x2) / 2,
            cy=y0 + (box.y1 + box.y2) / 2,
            width=float(plate_w),
            conf=float(best.confidence),
            probs=probs,
        )


def jpeg_bytes(frame, max_width: int = 1920, quality: int = 85) -> bytes | None:
    """Кадр в JPEG для отправки, уменьшенный до max_width."""
    height, width = frame.shape[:2]
    if width > max_width:
        frame = cv2.resize(frame, (max_width, round(height * max_width / width)))
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return encoded.tobytes() if ok else None
