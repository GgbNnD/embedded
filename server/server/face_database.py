from __future__ import annotations

from pathlib import Path

import cv2
import face_recognition
import numpy as np


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def discover_known_face_images(known_face_dir: Path) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []

    for path in sorted(known_face_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            entries.append((path.stem, path))
        elif path.is_dir():
            person_name = path.name
            for image_path in sorted(path.iterdir()):
                if image_path.is_file() and image_path.suffix.lower() in IMAGE_SUFFIXES:
                    entries.append((person_name, image_path))

    return entries


def load_known_face_database(known_face_dir: Path, logger=None) -> tuple[list[np.ndarray], list[str]]:
    if not known_face_dir.exists():
        raise FileNotFoundError(f"Known face directory not found: {known_face_dir}")

    encodings: list[np.ndarray] = []
    names: list[str] = []

    for person_name, image_path in discover_known_face_images(known_face_dir):
        image = face_recognition.load_image_file(str(image_path))
        face_encodings = face_recognition.face_encodings(image)

        if not face_encodings:
            if logger is not None:
                logger.warn(f"No face found in known image, skipped: {image_path}")
            continue

        if len(face_encodings) > 1 and logger is not None:
            logger.warn(f"Multiple faces found in known image, using the first one: {image_path}")

        encodings.append(face_encodings[0])
        names.append(person_name)

    return encodings, names


def recognize_faces(
    image_bgr: np.ndarray,
    known_encodings: list[np.ndarray],
    known_names: list[str],
    *,
    tolerance: float,
    detection_model: str,
    unknown_label: str,
) -> list[dict[str, object]]:
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(image_rgb, model=detection_model)
    face_encodings = face_recognition.face_encodings(image_rgb, face_locations)
    results: list[dict[str, object]] = []

    for (top, right, bottom, left), encoding in zip(face_locations, face_encodings):
        name = unknown_label
        distance = None

        if known_encodings:
            distances = face_recognition.face_distance(known_encodings, encoding)
            best_match_index = int(np.argmin(distances))
            best_distance = float(distances[best_match_index])
            if best_distance <= tolerance:
                name = known_names[best_match_index]
            distance = best_distance

        results.append(
            {
                "name": name,
                "distance": distance,
                "box": {
                    "top": int(top),
                    "right": int(right),
                    "bottom": int(bottom),
                    "left": int(left),
                },
            }
        )

    return results


def annotate_faces(image_bgr: np.ndarray, results: list[dict[str, object]]) -> np.ndarray:
    annotated = image_bgr.copy()
    for result in results:
        box = result["box"]
        left = int(box["left"])
        top = int(box["top"])
        right = int(box["right"])
        bottom = int(box["bottom"])
        name = str(result["name"])

        cv2.rectangle(annotated, (left, top), (right, bottom), (0, 255, 0), 2)
        cv2.rectangle(annotated, (left, max(top - 28, 0)), (right, top), (0, 255, 0), cv2.FILLED)
        cv2.putText(
            annotated,
            name,
            (left + 4, max(top - 8, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    return annotated
