"""Face detection and smooth camera tracking.

MediaPipe BlazeFace (short range) is used when installed; the OpenCV Haar
cascade is a dependency-light fallback. Both feed the same smoothing tracker
(deadzone + jitter gate + snap on speaker change).
"""

import os
import urllib.request

_detector_cache = {}


def _ensure_mediapipe_model(cfg) -> str:
    path = getattr(cfg, "file_mediapipe_model", None) or os.path.abspath(
        "blaze_face_short_range_v1.tflite"
    )
    if not os.path.exists(path) or os.path.getsize(path) < 10000:
        url = getattr(
            cfg,
            "url_mediapipe_model",
            "https://storage.googleapis.com/mediapipe-models/face_detector/"
            "blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
        )
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            urllib.request.urlretrieve(url, path)
        except Exception as exc:
            print(f"      Face model download skipped: {exc}")
    return path


def get_face_detector(cfg):
    """Return a callable(frame_bgr) -> list[(x, y, w, h, score)]."""
    kind = str(getattr(cfg, "face_detector", "mediapipe")).lower()
    if kind in _detector_cache:
        return _detector_cache[kind]

    detector = None
    if kind == "mediapipe":
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            model_path = _ensure_mediapipe_model(cfg)
            if os.path.exists(model_path):
                base = mp_python.BaseOptions(model_asset_path=model_path)
                options = mp_vision.FaceDetectorOptions(
                    base_options=base,
                    running_mode=mp_vision.RunningMode.IMAGE,
                    min_detection_confidence=float(getattr(cfg, "track_conf", 0.55) or 0.55),
                )
                mp_detector = mp_vision.FaceDetector.create_from_options(options)
                mp_image_cls = mp.Image
                mp_format = mp.ImageFormat.SRGB

                def detect_mp(frame):
                    rgb = frame[:, :, ::-1]
                    image = mp_image_cls(image_format=mp_format, data=rgb)
                    result = mp_detector.detect(image)
                    boxes = []
                    h, w = frame.shape[:2]
                    for det in result.detections or []:
                        bbox = det.bounding_box
                        score = det.categories[0].score if det.categories else 0.0
                        boxes.append((bbox.origin_x, bbox.origin_y, bbox.width, bbox.height, score))
                    return boxes

                detector = detect_mp
        except Exception as exc:
            print(f"      MediaPipe face detector unavailable ({exc}); using OpenCV Haar.")

    if detector is None:
        import cv2

        cascade = cv2.CascadeClassifier(
            os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        )

        def detect_haar(frame):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(60, 60))
            h, w = frame.shape[:2]
            return [
                (int(x), int(y), int(fw), int(fh), 1.0)
                for (x, y, fw, fh) in (faces if faces is not None else [])
                if fw * fh < w * h * 0.6
            ]

        detector = detect_haar

    _detector_cache[kind] = detector
    return detector


class FaceTracker:
    """Smooth horizontal camera target with deadzone and anti-jitter."""

    def __init__(self, cfg):
        self.step = float(getattr(cfg, "track_step", None) or 0.25)
        self.deadzone = float(
            getattr(cfg, "track_deadzone", None)
            if getattr(cfg, "track_deadzone", None) is not None else 0.15
        )
        self.smooth = float(
            getattr(cfg, "track_smooth", None)
            if getattr(cfg, "track_smooth", None) is not None else 0.30
        )
        self.jitter = int(
            getattr(cfg, "track_jitter", None)
            if getattr(cfg, "track_jitter", None) is not None else 5
        )
        self.snap = float(
            getattr(cfg, "track_snap", None)
            if getattr(cfg, "track_snap", None) is not None else 0.25
        )
        self.box_face = bool(getattr(cfg, "box_face_detection", False))
        self.track_lines = bool(getattr(cfg, "track_lines", False))
        self.target = None
        self.last_detect = -99.0
        self._static = bool(getattr(cfg, "static_crop", False))
        self._detector = None if self._static else get_face_detector(cfg)
        self._last_boxes = []

    def update(self, frame, t: float, crop_w: int):
        """Return the crop center-x for this frame, and boxes for overlays."""
        h, w = frame.shape[:2]
        if self._static or self._detector is None:
            self.target = w / 2 if self.target is None else self.target
            return self.target, []

        if t - self.last_detect >= self.step:
            self.last_detect = t
            try:
                boxes = self._detector(frame)
            except Exception:
                boxes = []
            boxes = [b for b in boxes if b[4] >= 0.4 and b[2] > 0 and b[3] > 0]
            self._last_boxes = boxes
            if boxes:
                faces = []
                for (x, y, bw, bh, score) in boxes:
                    area = bw * bh
                    faces.append((x + bw / 2, area, score))
                faces.sort(key=lambda f: (f[1] * f[2]), reverse=True)
                new_target = faces[0][0]
                if self.target is None:
                    self.target = new_target
                else:
                    jump = abs(new_target - self.target) / max(1, w)
                    if jump >= self.snap:
                        self.target = new_target  # cut / speaker change
                    elif abs(new_target - self.target) > self.jitter:
                        self.target += (new_target - self.target) * 0.6

        if self.target is None:
            self.target = w / 2

        # deadzone: only move when the subject leaves the centre band
        band = crop_w * self.deadzone
        if self.target < w / 2 - band:
            self.target += (w / 2 - band - self.target) * 0.15
        elif self.target > w / 2 + band:
            self.target += (w / 2 + band - self.target) * 0.15

        self.target = max(crop_w / 2, min(w - crop_w / 2, self.target))
        return self.target, self._last_boxes

    def draw_overlays(self, frame, crop_x, crop_w, boxes):
        import cv2

        for (x, y, bw, bh, _score) in boxes:
            if self.box_face:
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (52, 245, 168), 2)
        if self.track_lines:
            h, w = frame.shape[:2]
            cx = int(crop_x + crop_w / 2)
            cv2.line(frame, (cx, 0), (cx, h), (52, 245, 168), 1)
        return frame
