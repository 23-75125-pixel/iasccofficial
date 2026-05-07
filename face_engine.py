import base64
import binascii
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, cast


class FaceEngineError(Exception):
    """Raised when a face image cannot be used safely."""


class FaceEngineUnavailable(FaceEngineError):
    """Raised when the OpenCV recognition backend is not installed."""


class FaceEngine:
    FACE_SIZE = (200, 200)
    MAX_IMAGE_BYTES = 7 * 1024 * 1024
    MIN_VALID_REGISTRATION_FACES = 3
    MIN_FACE_AREA_RATIO = 0.012
    MIN_FACE_SHARPNESS = 18.0
    MIN_FACE_BRIGHTNESS = 35.0
    MAX_FACE_BRIGHTNESS = 225.0

    def __init__(self, instance_path, threshold=88.0):
        self.instance_path = Path(instance_path)
        self.threshold = float(threshold)
        self.samples_dir = self.instance_path / "faces" / "students"
        self.snapshots_dir = self.instance_path / "faces" / "attendance"
        self.model_dir = self.instance_path / "models"
        self.model_path = self.model_dir / "lbph_model.yml"
        self.labels_path = self.model_dir / "labels.json"
        self._backend_checked = False
        self._backend_error: str | None = None
        self.cv2: Any | None = None
        self.np: Any | None = None
        self.face_cascade: Any | None = None

    def status(self):
        self._load_backend(raise_on_error=False)
        return {
            "available": self._backend_error is None,
            "message": self._backend_error,
            "model_trained": self.model_path.exists() and self.labels_path.exists(),
            "threshold": self._effective_threshold(),
            "detector": "OpenCV Haar cascade",
            "recognizer": "OpenCV LBPH",
        }

    def _effective_threshold(self):
        if not self.labels_path.exists():
            return self.threshold
        try:
            labels_payload = json.loads(self.labels_path.read_text(encoding="utf-8"))
            return float(labels_payload.get("threshold", self.threshold))
        except (OSError, ValueError, TypeError):
            return self.threshold

    def _load_backend(self, raise_on_error=True):
        if self._backend_checked:
            if self._backend_error and raise_on_error:
                raise FaceEngineUnavailable(self._backend_error)
            return

        self._backend_checked = True
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            self._backend_error = (
                "OpenCV is not installed. Install project requirements with "
                "pip install -r requirements.txt."
            )
            if raise_on_error:
                raise FaceEngineUnavailable(self._backend_error) from exc
            return

        cv2_module = cast(Any, cv2)
        np_module = cast(Any, np)

        if not hasattr(cv2_module, "face"):
            self._backend_error = (
                "The OpenCV face recognizer module is missing. Install "
                "opencv-contrib-python from requirements.txt."
            )
            if raise_on_error:
                raise FaceEngineUnavailable(self._backend_error)
            return

        cascade_path = Path(cv2_module.data.haarcascades) / "haarcascade_frontalface_default.xml"
        face_cascade = cv2_module.CascadeClassifier(str(cascade_path))
        if face_cascade.empty():
            self._backend_error = "OpenCV could not load the frontal face detector."
            if raise_on_error:
                raise FaceEngineUnavailable(self._backend_error)
            return

        self.cv2 = cv2_module
        self.np = np_module
        self.face_cascade = face_cascade
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def _cv2(self):
        self._load_backend()
        if self.cv2 is None:
            raise FaceEngineUnavailable("OpenCV backend is not available.")
        return self.cv2

    def _np(self):
        self._load_backend()
        if self.np is None:
            raise FaceEngineUnavailable("NumPy backend is not available.")
        return self.np

    def _cascade(self):
        self._load_backend()
        if self.face_cascade is None:
            raise FaceEngineUnavailable("OpenCV face detector is not available.")
        return self.face_cascade

    def _create_recognizer(self):
        cv2 = self._cv2()
        face_module = getattr(cv2, "face", None)
        factory = getattr(face_module, "LBPHFaceRecognizer_create", None)
        if factory is None:
            raise FaceEngineUnavailable(
                "The OpenCV LBPH recognizer is missing. Install opencv-contrib-python."
            )
        return factory()

    def decode_image(self, image_data):
        cv2 = self._cv2()
        np = self._np()
        if not isinstance(image_data, str) or not image_data.strip():
            raise FaceEngineError("Image data is required.")

        payload = image_data.split(",", 1)[1] if "," in image_data else image_data
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise FaceEngineError("Image data is not valid base64.") from exc

        if not raw or len(raw) > self.MAX_IMAGE_BYTES:
            raise FaceEngineError("Image file is empty or too large.")

        image_array = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if image is None:
            raise FaceEngineError("Image could not be decoded.")
        return image

    def extract_face(self, image, strict=True, require_quality=False):
        face, _box, _backend = self._extract_face_with_box(
            image,
            strict=strict,
            require_quality=require_quality,
        )
        return face

    def _extract_face_with_box(self, image, strict=True, require_quality=False):
        cv2 = self._cv2()
        face_cascade = self._cascade()
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        detection_gray = cv2.equalizeHist(gray)
        image_height, image_width = gray.shape[:2]

        faces = face_cascade.detectMultiScale(
            detection_gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(80, 80),
        )
        if len(faces) == 0:
            faces = face_cascade.detectMultiScale(
                detection_gray,
                scaleFactor=1.05,
                minNeighbors=4,
                minSize=(60, 60),
            )
        boxes = [
            (int(x), int(y), int(x + width), int(y + height))
            for x, y, width, height in faces
        ]
        backend = "OpenCV Haar cascade"

        if len(boxes) == 0:
            raise FaceEngineError("No face was detected. Face the camera clearly and try again.")

        if strict and len(boxes) > 1:
            raise FaceEngineError("More than one face was detected. Capture one person at a time.")

        x1, y1, x2, y2 = sorted(
            boxes,
            key=lambda box: (box[2] - box[0]) * (box[3] - box[1]),
            reverse=True,
        )[0]
        width = x2 - x1
        height = y2 - y1
        pad_x = int(width * 0.42)
        top_pad = int(height * 0.78)
        bottom_pad = int(height * 0.35)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - top_pad)
        x2 = min(image_width, x2 + pad_x)
        y2 = min(image_height, y2 + bottom_pad)

        face = gray[y1:y2, x1:x2]
        if face.size == 0:
            raise FaceEngineError("Detected face area was invalid. Try again.")
        if require_quality:
            self._validate_face_quality(face, image_width, image_height)
        face = self._normalize_face(face)
        return face, (x1, y1, x2, y2), backend

    def _normalize_face(self, face):
        cv2 = self._cv2()
        face = cv2.resize(face, self.FACE_SIZE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        face = clahe.apply(face)
        return cv2.GaussianBlur(face, (3, 3), 0)

    def _validate_face_quality(self, face, image_width, image_height):
        cv2 = self._cv2()
        face_area_ratio = face.size / float(image_width * image_height)
        brightness = float(face.mean())
        sharpness = float(cv2.Laplacian(face, cv2.CV_64F).var())

        if face_area_ratio < self.MIN_FACE_AREA_RATIO:
            raise FaceEngineError("Face is too small in the frame. Move closer to the camera.")
        if brightness < self.MIN_FACE_BRIGHTNESS:
            raise FaceEngineError("Face is too dark. Move toward better lighting.")
        if brightness > self.MAX_FACE_BRIGHTNESS:
            raise FaceEngineError("Face is overexposed. Reduce bright backlight or glare.")
        if sharpness < self.MIN_FACE_SHARPNESS:
            raise FaceEngineError("Face image is blurry. Hold still and capture again.")

    def prepare_registration_faces(self, image_data_list):
        faces = []
        errors = []
        for index, image_data in enumerate(image_data_list, start=1):
            image = self.decode_image(image_data)
            try:
                faces.append(self.extract_face(image, strict=True, require_quality=True))
            except FaceEngineError as exc:
                errors.append(f"Capture {index}: {exc}")
        if len(faces) < self.MIN_VALID_REGISTRATION_FACES:
            details = " ".join(errors[:3])
            raise FaceEngineError(
                f"Only {len(faces)} valid face sample(s) were detected. "
                f"Keep at least {self.MIN_VALID_REGISTRATION_FACES} clear captures. {details}"
            )
        return faces

    def save_face_sample(self, student_number, face_image):
        cv2 = self._cv2()
        student_folder = self.samples_dir / self._safe_slug(student_number)
        student_folder.mkdir(parents=True, exist_ok=True)
        path = student_folder / f"{uuid.uuid4().hex}.jpg"
        if not cv2.imwrite(str(path), face_image):
            raise FaceEngineError("Could not save the face sample.")
        return self._relative(path)

    def save_attendance_snapshot(self, student_number, image_data, recorded_at):
        cv2 = self._cv2()
        image = self.decode_image(image_data)
        day_folder = self.snapshots_dir / recorded_at.strftime("%Y-%m-%d")
        day_folder.mkdir(parents=True, exist_ok=True)
        path = day_folder / f"{self._safe_slug(student_number)}-{uuid.uuid4().hex}.jpg"
        if not cv2.imwrite(str(path), image):
            raise FaceEngineError("Could not save attendance snapshot.")
        return self._relative(path)

    def train(self, sample_rows):
        cv2 = self._cv2()
        np = self._np()
        faces = []
        labels = []
        source_sample_count = 0
        label_by_student_id = {}

        for row in sample_rows:
            student_db_id = int(row["student_id"])
            label = label_by_student_id.setdefault(student_db_id, len(label_by_student_id) + 1)
            image_path = self.instance_path / row["image_path"]
            face = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if face is None:
                continue
            face = self._normalize_face(face)
            source_sample_count += 1
            for variant in self._training_variants(face):
                faces.append(variant)
                labels.append(label)

        if not faces:
            self.clear_model()
            return {"trained": False, "sample_count": 0, "student_count": 0}

        recognizer = self._create_recognizer()
        recognizer.train(faces, np.array(labels, dtype=np.int32))
        calibrated_threshold = self._calibrate_threshold(recognizer, faces, labels)

        temp_model = self.model_path.with_suffix(".tmp.yml")
        temp_labels = self.labels_path.with_suffix(".tmp.json")
        recognizer.write(str(temp_model))
        temp_labels.write_text(
            json.dumps(
                {
                    "labels": {str(label): student_id for student_id, label in label_by_student_id.items()},
                    "threshold": calibrated_threshold,
                    "base_threshold": self.threshold,
                    "trained_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temp_model.replace(self.model_path)
        temp_labels.replace(self.labels_path)
        return {
            "trained": True,
            "sample_count": source_sample_count,
            "augmented_sample_count": len(faces),
            "student_count": len(label_by_student_id),
            "threshold": calibrated_threshold,
        }

    def _training_variants(self, face):
        cv2 = self._cv2()
        return [
            face,
            cv2.flip(face, 1),
            cv2.convertScaleAbs(face, alpha=1.08, beta=8),
            cv2.convertScaleAbs(face, alpha=0.92, beta=-8),
        ]

    def _recognition_variants(self, face):
        cv2 = self._cv2()
        return [
            face,
            cv2.convertScaleAbs(face, alpha=1.06, beta=6),
            cv2.convertScaleAbs(face, alpha=0.94, beta=-6),
        ]

    def _calibrate_threshold(self, recognizer, faces, labels):
        distances = []
        for face, expected_label in zip(faces, labels):
            predicted_label, distance = recognizer.predict(face)
            if int(predicted_label) == int(expected_label):
                distances.append(float(distance))
        if not distances:
            return self.threshold

        mean_distance = sum(distances) / len(distances)
        max_distance = max(distances)
        calibrated = max(self.threshold, mean_distance + 28.0, max_distance + 18.0)
        return round(min(calibrated, 115.0), 2)

    def recognize(self, image_data):
        if not self.model_path.exists() or not self.labels_path.exists():
            raise FaceEngineError("Recognition model is not trained yet. Register a student first.")

        image = self.decode_image(image_data)
        face, box, detection_backend = self._extract_face_with_box(image, strict=False)
        recognizer = self._create_recognizer()
        recognizer.read(str(self.model_path))

        label, confidence = self._predict_best_match(recognizer, face)
        labels_payload = json.loads(self.labels_path.read_text(encoding="utf-8"))
        student_db_id = labels_payload.get("labels", {}).get(str(label))
        threshold = float(labels_payload.get("threshold", self.threshold))
        confidence = float(confidence)
        detection_payload = {
            "box": {
                "x1": int(box[0]),
                "y1": int(box[1]),
                "x2": int(box[2]),
                "y2": int(box[3]),
            },
            "image_size": {
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
            },
            "detection_backend": detection_backend,
        }

        if student_db_id is None or confidence > threshold:
            return {
                "matched": False,
                "confidence": round(confidence, 2),
                "threshold": threshold,
                **detection_payload,
            }

        return {
            "matched": True,
            "student_id": int(student_db_id),
            "confidence": round(confidence, 2),
            "threshold": threshold,
            **detection_payload,
        }

    def _predict_best_match(self, recognizer, face):
        predictions = [recognizer.predict(variant) for variant in self._recognition_variants(face)]
        return min(predictions, key=lambda prediction: float(prediction[1]))

    def clear_model(self):
        for path in (self.model_path, self.labels_path):
            if path.exists():
                path.unlink()

    def delete_relative_file(self, relative_path):
        if not relative_path:
            return
        path = (self.instance_path / relative_path).resolve()
        try:
            path.relative_to(self.instance_path.resolve())
        except ValueError:
            return
        try:
            if path.exists():
                path.unlink()
        except OSError:
            return

    def _relative(self, path):
        return path.relative_to(self.instance_path).as_posix()

    def _safe_slug(self, value):
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
        return slug.strip("-") or uuid.uuid4().hex
