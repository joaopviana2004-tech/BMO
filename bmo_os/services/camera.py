"""Câmera (Raspberry Pi AI Camera / IMX500) + face detection opcional.

Wrapper sobre `picamera2`. Se nem picamera2 nem a câmera estiverem
disponíveis (caso típico: rodando no Windows pra dev), `is_available`
fica False e as telas mostram mensagem amigável.

Truques importantes:
- **Lazy start**: a câmera só liga depois do primeiro `acquire()`. Sem
  ninguém segurando ela, fica desligada (economiza calor e energia).
  Refcount simples: cada screen que precisa chama `acquire()` no enter e
  `release()` no exit. Quando o contador zera, picam2.stop() é chamado.
- picamera2 'RGB888' é na verdade BGR — inverte canais antes do pygame
- HFlip aplicado no ISP via libcamera.Transform (espelho tipo selfie cam)
- Face detection (Haar do OpenCV) só roda se alguém chamou get_faces()
  nos últimos FACE_REQUEST_TIMEOUT_S segundos — economiza CPU/calor quando
  ninguém tá olhando

Setup no Pi:
    sudo apt install python3-picamera2 imx500-models python3-opencv
"""
from __future__ import annotations

import os
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

HAS_CV2 = False          # cascade pronto → face detection
HAS_CV2_MODULE = False   # só o módulo cv2 → captura de webcam USB
_face_cascade = None
try:
    import cv2  # type: ignore
    HAS_CV2_MODULE = True
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
        self.kind = "none"      # "ai" (Pi AI/IMX500) | "csi" (Pi cam) | "usb" | "none"
        self._mode = None       # "picam" | "usb"
        self._picam = None
        self._usb_cap = None
        self._lock = threading.Lock()
        self._latest_frame: Optional[pygame.Surface] = None
        self._latest_array = None   # último frame cru (BGR ndarray) p/ capture_jpeg
        self._qr = None             # cv2.QRCodeDetector lazy (leitura de QR de WiFi)
        self._latest_faces: list[tuple[int, int, int, int]] = []
        self._last_face_request = 0.0
        self._frame_count = 0
        self._fps_window_start = time.time()
        self._active = False    # captura ligada? (picam.start() ou loop USB)
        self._users = 0         # refcount de quem pediu a câmera
        self._stop_flag = False

        # BMO_CAMERA: "auto" (padrão) | "usb" (força webcam USB) | "pi" (só picamera2)
        pref = os.environ.get("BMO_CAMERA", "auto").strip().lower()

        # 1) câmera Pi (CSI / AI cam) via picamera2.
        # Em "auto", se o libcamera só enxerga uma webcam USB, deixamos ela pro
        # OpenCV (cores corretas + sem inteligência) em vez do pipeline picamera2,
        # que inverte os canais (a pessoa fica "azul") em câmeras USB.
        lk = self._libcamera_kind() if (HAS_PICAMERA and pref in ("auto", "pi")) else "none"
        if HAS_PICAMERA and (pref == "pi" or lk in ("ai", "csi")):
            try:
                self._picam = Picamera2()
                kwargs = dict(main={"size": PREVIEW_SIZE, "format": "RGB888"})
                if Transform is not None:
                    kwargs["transform"] = Transform(hflip=True)
                config = self._picam.create_preview_configuration(**kwargs)
                self._picam.configure(config)
                # NÃO chama start() — espera primeiro acquire() pra ligar a câmera
                self.kind = lk if lk in ("ai", "csi") else "csi"
                self._mode = "picam"
                self.is_available = True
            except Exception as e:
                self.error = f"picam: {str(e)[:40]}"
                self._picam = None

        # 2) webcam USB via OpenCV (sem inteligência) — pulada se pref=pi
        if not self.is_available and HAS_CV2_MODULE and pref in ("auto", "usb"):
            cap = self._open_usb_capture()
            if cap is not None:
                self._usb_cap = cap
                self.kind = "usb"
                self._mode = "usb"
                self.is_available = True
            else:
                self.error = "webcam USB nao abriu"

        if not self.is_available:
            if not self.error:
                if pref == "usb" and not HAS_CV2_MODULE:
                    self.error = "instale opencv (cv2)"
                elif not HAS_PICAMERA and not HAS_CV2_MODULE:
                    self.error = "sem picamera2/opencv"
                else:
                    self.error = "nenhuma camera"
            return

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _libcamera_kind(self) -> str:
        """O que o libcamera enxerga: 'ai' (IMX500) | 'csi' | 'usb' | 'none'.

        Webcams USB também aparecem no libcamera em Pi OS recentes; detectamos
        pelo Id (caminho contém 'usb') pra poder roteá-las pro OpenCV.
        """
        try:
            infos = Picamera2.global_camera_info()
        except Exception:
            return "none"
        if not infos:
            return "none"
        for info in infos:
            if "imx500" in str(info.get("Model", "")).lower():
                return "ai"
        for info in infos:
            if "usb" in str(info.get("Id", "")).lower():
                return "usb"
        return "csi"

    def _open_usb_capture(self):
        """Abre a 1a webcam USB que responder (tenta índices 0..3). cv2.VideoCapture."""
        for idx in range(4):
            try:
                cap = cv2.VideoCapture(idx)
            except Exception:
                continue
            if cap is None:
                continue
            if cap.isOpened():
                # confirma que realmente entrega frame (alguns índices "abrem" vazios)
                ok, _ = cap.read()
                if ok:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, PREVIEW_W)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, PREVIEW_H)
                    return cap
            try:
                cap.release()
            except Exception:
                pass
        return None

    # ---------- lifecycle (refcount) ----------

    def acquire(self) -> None:
        """Marca um usuário ativo. No primeiro, liga a câmera."""
        if not self.is_available:
            return
        with self._lock:
            was_zero = self._users == 0
            self._users += 1
        if was_zero:
            try:
                if self._mode == "picam":
                    self._picam.start()
                with self._lock:
                    self._active = True
                    self._fps_window_start = time.time()
                    self._frame_count = 0
            except Exception:
                with self._lock:
                    self._users = max(0, self._users - 1)

    def release(self) -> None:
        """Marca usuário inativo. No último, desliga a câmera."""
        if not self.is_available:
            return
        with self._lock:
            if self._users <= 0:
                return
            self._users -= 1
            should_stop = self._users == 0
            if should_stop:
                self._active = False
        if should_stop:
            if self._mode == "picam":
                try:
                    self._picam.stop()
                except Exception:
                    pass
            with self._lock:
                self._latest_frame = None
                self._latest_array = None
                self._latest_faces = []
                self.fps = 0.0

    # ---------- thread loop ----------

    def _loop(self) -> None:
        frame_dt = 1.0 / PREVIEW_FPS
        face_skip = 0
        while not self._stop_flag:
            with self._lock:
                active = self._active
            if not active:
                # câmera desligada — thread fica idle até alguém chamar acquire()
                time.sleep(0.1)
                continue
            t0 = time.time()
            try:
                if self._mode == "usb":
                    ok, arr = self._usb_cap.read()   # BGR
                    if not ok or arr is None:
                        time.sleep(frame_dt)
                        continue
                else:
                    arr = self._picam.capture_array("main")
                # 'RGB888' do picamera2 é na verdade BGR (igual cv2) — inverte
                # canais e transpõe (H,W,3) → (W,H,3) pro pygame.surfarray
                surf = pygame.surfarray.make_surface(arr[:, :, ::-1].transpose([1, 0, 2]))
                with self._lock:
                    self._latest_frame = surf
                    self._latest_array = arr   # cru (BGR) p/ capture_jpeg
                # FPS rolling 1s
                self._frame_count += 1
                now = time.time()
                window = now - self._fps_window_start
                if window >= 1.0:
                    self.fps = self._frame_count / window
                    self._frame_count = 0
                    self._fps_window_start = now
                # Face detection só em câmera Pi (USB não tem inteligência) e
                # só se alguém pediu recentemente
                face_skip += 1
                wants_faces = (HAS_CV2 and self.kind in ("ai", "csi")
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

    def capture_jpeg(self, quality: int = 80) -> Optional[bytes]:
        """Codifica o último frame (BGR) em JPEG na memória, pro teste de visão.
        Usa o frame que a thread já capturou (sem reler o device em paralelo).
        Retorna None se câmera offline / sem frame / sem cv2."""
        if not self.is_available or not HAS_CV2_MODULE:
            return None
        with self._lock:
            arr = self._latest_array
        if arr is None:
            return None
        try:
            ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
            return buf.tobytes() if ok else None
        except Exception:
            return None

    def read_qr(self) -> str:
        """Decodifica um QR no último frame (pro WiFi por QR). "" se não achar.
        Usa o cv2.QRCodeDetector no frame que a thread já capturou."""
        if not self.is_available or not HAS_CV2_MODULE:
            return ""
        with self._lock:
            arr = self._latest_array
        if arr is None:
            return ""
        try:
            if self._qr is None:
                self._qr = cv2.QRCodeDetector()
            data, _points, _straight = self._qr.detectAndDecode(arr)
            return data or ""
        except Exception:
            return ""

    def capture_photo(self, target_dir: Path) -> Optional[Path]:
        """Captura uma foto. Retorna o Path ou None."""
        if not self.is_available:
            return None
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = target_dir / f"photo_{int(time.time())}.jpg"
            if self._mode == "usb":
                ok, arr = self._usb_cap.read()
                if not ok or arr is None:
                    return None
                cv2.imwrite(str(filename), arr)
            else:
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
            # close() libera o device (fd do libcamera) — só stop() não basta.
            # Necessário antes do execv do restart, senão o processo novo acha
            # a câmera ocupada.
            try:
                self._picam.close()
            except Exception:
                pass
        if self._usb_cap is not None:
            try:
                self._usb_cap.release()
            except Exception:
                pass
        self.is_available = False

    @property
    def intelligence_active(self) -> bool:
        """True quando a câmera suporta inteligência (Pi cam, não USB)."""
        return self.kind in ("ai", "csi") and HAS_CV2

    @property
    def kind_label(self) -> str:
        return {"ai": "PI AI CAM", "csi": "PI CAM", "usb": "USB", "none": "--"}.get(self.kind, "--")

    @property
    def detector_status(self) -> str:
        """ACTIVE se cv2 tá rodando agora; IDLE se ngm pediu; OFF caso contrário."""
        if self.kind == "usb":
            return "OFF (usb)"
        if not HAS_CV2:
            return "OFF (no cv2)"
        if not self._active:
            return "OFF (cam off)"
        if time.time() - self._last_face_request > FACE_REQUEST_TIMEOUT_S:
            return "IDLE"
        return "ACTIVE"

    @property
    def hflip(self) -> bool:
        return Transform is not None

    @property
    def is_running(self) -> bool:
        """True se a câmera está ligada agora (alguém deu acquire)."""
        return self._active

    @property
    def users(self) -> int:
        return self._users
