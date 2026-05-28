"""Câmera (Raspberry Pi AI Camera / IMX500) + face detection opcional.

Wrapper sobre `picamera2`. Se nem picamera2 nem a câmera estiverem
disponíveis (caso típico: rodando no Windows pra dev), `is_available`
fica False e as telas mostram mensagem amigável.

Face detection: usa Haar cascade do OpenCV (rodado na CPU em ~10fps no
thread da câmera). Quando quiser usar o modelo on-sensor IMX500 real,
trocar a parte de detecção sem mexer na interface pública.

Setup no Pi:
    sudo apt install python3-picamera2 imx500-models python3-opencv
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import pygame

# ----- imports opcionais -----
HAS_PICAMERA = False
Picamera2 = None
try:
    from picamera2 import Picamera2 as _Picamera2  # type: ignore
    Picamera2 = _Picamera2
    HAS_PICAMERA = True
except Exception:
    pass

HAS_CV2 = False
_face_cascade = None
try:
    import cv2  # type: ignore
    _cascade_file = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if Path(_cascade_file).exists():
        _face_cascade = cv2.CascadeClassifier(_cascade_file)
        HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore


PREVIEW_W, PREVIEW_H = 320, 240
PREVIEW_SIZE = (PREVIEW_W, PREVIEW_H)
PREVIEW_FPS = 15
FACE_EVERY_N_FRAMES = 3   # detecção é cara — rodar a cada N frames


class CameraService:
    def __init__(self) -> None:
        self.preview_size = PREVIEW_SIZE
        self.is_available = False
        self.error = ""
        self._picam = None
        self._lock = threading.Lock()
        self._latest_frame: Optional[pygame.Surface] = None
        self._latest_faces: list[tuple[int, int, int, int]] = []
        self._stop_flag = False

        if not HAS_PICAMERA:
            self.error = "picamera2 nao instalada"
            return

        try:
            self._picam = Picamera2()
            config = self._picam.create_preview_configuration(
                main={"size": PREVIEW_SIZE, "format": "RGB888"}
            )
            self._picam.configure(config)
            self._picam.start()
            self.is_available = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        except Exception as e:
            self.error = f"camera: {str(e)[:40]}"

    # ---------- thread loop ----------

    def _loop(self) -> None:
        frame_dt = 1.0 / PREVIEW_FPS
        face_counter = 0
        while not self._stop_flag and self.is_available:
            t0 = time.time()
            try:
                arr = self._picam.capture_array("main")
                # picamera2 retorna (H, W, 3) — pygame.surfarray quer (W, H, 3)
                surf = pygame.surfarray.make_surface(arr.transpose([1, 0, 2]))
                with self._lock:
                    self._latest_frame = surf
                # face detection cada N frames
                face_counter += 1
                if HAS_CV2 and face_counter >= FACE_EVERY_N_FRAMES:
                    face_counter = 0
                    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                    faces = _face_cascade.detectMultiScale(
                        gray,
                        scaleFactor=1.2,
                        minNeighbors=4,
                        minSize=(28, 28),
                    )
                    with self._lock:
                        self._latest_faces = [tuple(map(int, f)) for f in faces]
            except Exception:
                pass
            elapsed = time.time() - t0
            wait = frame_dt - elapsed
            if wait > 0:
                time.sleep(wait)

    # ---------- API pública ----------

    def get_preview(self) -> Optional[pygame.Surface]:
        with self._lock:
            return self._latest_frame

    def get_faces(self) -> list[tuple[int, int, int, int]]:
        """Lista de (x, y, w, h) em coords do preview (320x240)."""
        with self._lock:
            return list(self._latest_faces)

    def capture_photo(self, target_dir: Path) -> Optional[Path]:
        """Captura uma foto em alta resolução. Retorna o Path ou None."""
        if not self.is_available or self._picam is None:
            return None
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = target_dir / f"photo_{int(time.time())}.jpg"
            self._picam.capture_file(str(filename))
            return filename
        except Exception:
            return None

    def stop(self) -> None:
        self._stop_flag = True
        if self._picam is not None:
            try:
                self._picam.stop()
            except Exception:
                pass
        self.is_available = False
