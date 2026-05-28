"""Câmera (Raspberry Pi AI Camera / IMX500) + face detection opcional.

Wrapper sobre `picamera2`. Se nem picamera2 nem a câmera estiverem
disponíveis (caso típico: rodando no Windows pra dev), `is_available`
fica False e as telas mostram mensagem amigável.

Truques importantes:
- picamera2 'RGB888' é na verdade BGR — inverte canais antes do pygame
- HFlip aplicado no ISP via libcamera.Transform (espelho tipo selfie cam)
- Face detection (Haar do OpenCV) só roda se alguém chamou get_faces()
  nos últimos FACE_REQUEST_TIMEOUT_S segundos — economiza CPU/calor quando
  ninguém tá olhando

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
Transform = None
try:
    from picamera2 import Picamera2 as _Picamera2  # type: ignore
    Picamera2 = _Picamera2
    HAS_PICAMERA = True
    try:
        from libcamera import Transform as _Transform  # type: ignore
        Transform = _Transform
    except Exception:
        Transform = None
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


# Preview em 800x480 — 1:1 com o display físico, sem perda na escala
PREVIEW_W, PREVIEW_H = 800, 480
PREVIEW_SIZE = (PREVIEW_W, PREVIEW_H)
PREVIEW_FPS = 15

# Detecção de rosto roda numa versão pequena pra ficar rápida
DETECT_W, DETECT_H = 320, 192

# Quanto tempo manter detecção ativa após a última chamada de get_faces().
# Se ninguém pede, cv2 nem é invocado → economiza CPU/calor.
FACE_REQUEST_TIMEOUT_S = 4.0


class CameraService:
    def __init__(self) -> None:
        self.preview_size = PREVIEW_SIZE
        self.is_available = False
        self.error = ""
        self.fps = 0.0
        self._picam = None
        self._lock = threading.Lock()
        self._latest_frame: Optional[pygame.Surface] = None
        self._latest_faces: list[tuple[int, int, int, int]] = []
        self._last_face_request = 0.0
        self._frame_count = 0
        self._fps_window_start = time.time()
        self._stop_flag = False

        if not HAS_PICAMERA:
            self.error = "picamera2 nao instalada"
            return

        try:
            self._picam = Picamera2()
            kwargs = dict(main={"size": PREVIEW_SIZE, "format": "RGB888"})
            if Transform is not None:
                kwargs["transform"] = Transform(hflip=True)
            config = self._picam.create_preview_configuration(**kwargs)
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
        face_skip = 0
        while not self._stop_flag and self.is_available:
            t0 = time.time()
            try:
                arr = self._picam.capture_array("main")
                # picamera2 'RGB888' é na verdade BGR — inverte canais
                # depois transpoe (H,W,3) → (W,H,3) pro pygame.surfarray
                surf = pygame.surfarray.make_surface(arr[:, :, ::-1].transpose([1, 0, 2]))
                with self._lock:
                    self._latest_frame = surf
                # FPS rolling 1s
                self._frame_count += 1
                now = time.time()
                window = now - self._fps_window_start
                if window >= 1.0:
                    self.fps = self._frame_count / window
                    self._frame_count = 0
                    self._fps_window_start = now
                # Face detection só se alguém pediu recentemente
                face_skip += 1
                wants_faces = (HAS_CV2
                               and time.time() - self._last_face_request < FACE_REQUEST_TIMEOUT_S)
                if wants_faces and face_skip >= 3:
                    face_skip = 0
                    # downscale pra detecção (mais rápido)
                    small = cv2.resize(arr, (DETECT_W, DETECT_H))
                    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                    faces = _face_cascade.detectMultiScale(
                        gray,
                        scaleFactor=1.2,
                        minNeighbors=4,
                        minSize=(28, 28),
                    )
                    sx = PREVIEW_W / DETECT_W
                    sy = PREVIEW_H / DETECT_H
                    scaled = [(int(x*sx), int(y*sy), int(w*sx), int(h*sy))
                              for (x, y, w, h) in faces]
                    with self._lock:
                        self._latest_faces = scaled
                elif not wants_faces:
                    with self._lock:
                        self._latest_faces = []
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
        """Lista de (x, y, w, h) em coords do preview. Marca interesse."""
        now = time.time()
        with self._lock:
            self._last_face_request = now
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

    @property
    def detector_status(self) -> str:
        """ACTIVE se cv2 tá rodando agora; IDLE se ngm pediu; OFF se sem cv2."""
        if not HAS_CV2:
            return "OFF (no cv2)"
        if time.time() - self._last_face_request > FACE_REQUEST_TIMEOUT_S:
            return "IDLE"
        return "ACTIVE"

    @property
    def hflip(self) -> bool:
        return Transform is not None
