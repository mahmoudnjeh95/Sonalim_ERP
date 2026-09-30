"""RapidOCR behind two methods: detection + recognition over a whole image (text boxes in
that image's pixels), and recognition alone over one cropped cell."""
from __future__ import annotations

import numpy as np
from rapidocr import RapidOCR

from app.locate import TextBox

# RapidOCR's own default text_score: the engine's cut for accepting a reading. The engine
# runs with no cut so the backend sees weak readings too, and flags those under this one.
ACCEPT_SCORE = 0.5


class Engine:
    def __init__(self) -> None:
        # RapidOCR 3.9.2 defaults (PP-OCRv6 small det/rec, bundled in the wheel); see README.md.
        self._ocr = RapidOCR(params={"Global.text_score": 0.0, "Global.log_level": "warning"})

    def detect(self, image: np.ndarray) -> list[TextBox]:
        # The use_* flags stick on the RapidOCR object between calls, so every call sets all three.
        # No angle classifier: the page is turned upright as a whole (pipeline._orientation), and
        # the classifier would also read upside-down lines, hiding a wrong rotation.
        result = self._ocr(image, use_det=True, use_cls=False, use_rec=True)
        if result.boxes is None:
            return []
        boxes = []
        for points, text, score in zip(result.boxes, result.txts, result.scores):
            xs, ys = points[:, 0], points[:, 1]
            boxes.append(TextBox(str(text), float(score), float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())))
        return boxes

    def recognize(self, crop: np.ndarray) -> tuple[str, float]:
        """The text of one cropped cell, read as a single line (no detection, no angle check)."""
        if crop.size == 0:
            return "", 0.0
        result = self._ocr(crop, use_det=False, use_cls=False, use_rec=True)
        if not getattr(result, "txts", None):
            return "", 0.0
        return str(result.txts[0]).strip(), float(result.scores[0])
