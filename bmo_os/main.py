"""Ponto de entrada do BMO OS.

Uso:
    python -m bmo_os.main             # janelado, ótimo pra desenvolver no PC
    python -m bmo_os.main --fullscreen # no Pi
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pygame

# permite rodar tanto como módulo quanto como script direto
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bmo_os.core import config, session, theme_state
from bmo_os.core.app import App
from bmo_os.core.theme import Colors, LOGICAL_SIZE, render_text
from bmo_os.screens.agenda import AgendaScreen
from bmo_os.screens.aitest import AITestScreen
from bmo_os.screens.alert import AlertScreen
from bmo_os.screens.bmo_face import BMOFaceScreen
from bmo_os.screens.brain import BrainScreen
from bmo_os.screens.confirm import ConfirmScreen
from bmo_os.screens.devhub import DevHubScreen
from bmo_os.screens.clock import ClockScreen
from bmo_os.screens.flappy import FlappyScreen
from bmo_os.screens.flappy_train import FlappyTrainScreen
from bmo_os.screens.games import (
    GamesScreen, draw_flappy_icon, draw_haxball_icon, draw_pong_icon,
    draw_snake_icon, draw_space_invaders_icon,
)
from bmo_os.screens.haxball import HaxballScreen
from bmo_os.screens.haxball_train import HaxballTrainScreen
from bmo_os.screens.snake import SnakeScreen
from bmo_os.screens.home import HomeScreen, build_categories
from bmo_os.screens.gallery import GalleryScreen
from bmo_os.screens.login import LoginScreen
from bmo_os.screens.mic_button import MicButton
from bmo_os.screens.photo import PHOTOS_DIR, PhotoScreen
from bmo_os.screens.pomodoro import PomodoroScreen
from bmo_os.screens.pong import PongAmbientScreen, PongScreen
from bmo_os.screens.recorder import RecorderScreen
from bmo_os.screens.settings import SettingsScreen
from bmo_os.screens.smarthome import SmartHomeScreen
from bmo_os.screens.wifi import WifiScreen
from bmo_os.screens.sysinfo import SysInfoScreen
from bmo_os.screens.shuffler import ShufflingAmbientScreen
from bmo_os.screens.sleep import SleepScreen
from bmo_os.screens.space_invaders import SpaceInvadersAmbientScreen, SpaceInvadersScreen
from bmo_os.screens.suspended import SuspendedScreen
from bmo_os.screens.tasks import TasksScreen
from bmo_os.services import audio
from bmo_os.services import google_auth
from bmo_os.services.camera import CameraService
from bmo_os.services.chat import ChatService
from bmo_os.services.cooler import CoolerService
from bmo_os.services.dev_hub import DevHubService
from bmo_os.services.github_dev import GitHubPoller
from bmo_os.services.drive_sync import DriveSync
from bmo_os.services.gcalendar import CalendarService
from bmo_os.services.gpio_button import GPIOButton
from bmo_os.services.git_updates import GitUpdatesService
from bmo_os.services.knowledge import KnowledgeService
from bmo_os.services.network import NetworkService
from bmo_os.services.notifications import EventAlerter
from bmo_os.services.pairing import PairingServer, local_ip
from bmo_os.services.pet_brain import PetBrain
from bmo_os.services.recorder import RecorderService
from bmo_os.services.smarthome import SmartHomeService
from bmo_os.services.pet_memory import PetMemory
from bmo_os.services.pet_state import PetState
from bmo_os.services.sysinfo import SysInfoService
from bmo_os.services.reminders import ReminderService
from bmo_os.services.routines import due_today as routines_due_today, load_routines
from bmo_os.services.todoist import SECTION_LABELS, SECTION_NAMES, TodoistService
from bmo_os.services.tts import SCREEN_PHRASES, TTSService
from bmo_os.services.voice import VoiceService
from bmo_os.services.webui import WebUIServer

# Sync das preferências do perfil com o Drive (None = guest/sem credencial).
# Vive aqui pra o logout do SETTINGS conseguir dar o flush final.
_drive_sync: dict = {"svc": None}

# Toast não-intrusivo (rodapé): "Sincronização com o Drive concluída" etc.
_toast = {"msg": "", "until": 0.0}


def show_toast(msg: str) -> None:
    _toast["msg"] = (msg or "").strip()
    _toast["until"] = time.time() + 4.0


# Pareamento pelo PC (Drive COMPLETO): a thread HTTP do PairingServer
# enfileira aqui; o main thread aplica via _drain_pair (troca de tela e de
# tokens não pode acontecer fora dele).
_pair_queue: list = []
_pair_lock = threading.Lock()
_pair_apply = {"fn": None}   # definido em main() (precisa de app/_after_login)


def _on_pair_request(user: dict, tokens: dict) -> None:
    with _pair_lock:
        _pair_queue.append((user, tokens))


def _drain_pair() -> None:
    with _pair_lock:
        item = _pair_queue.pop(0) if _pair_queue else None
    if item is not None and _pair_apply["fn"] is not None:
        try:
            _pair_apply["fn"](*item)
        except Exception:
            pass


# Chat remoto (POST /chat no PairingServer): mensagem digitada no PC entra no
# mesmo fluxo da fala. O handler real é registrado pelo build_initial.
_remote_chat = {"fn": None}

# Dev Hub (POST /dev + GitHub API): commits/CI/logs — global (sobrevive ao login).
_dev_hub = DevHubService()
_github = GitHubPoller(_dev_hub)


def _on_remote_chat(text: str) -> dict:
    fn = _remote_chat["fn"]
    if fn is None:
        return {"msg": "", "error": "bimo ainda iniciando (ou na tela de login)"}
    return fn(text)


def _on_dev_event(payload: dict) -> dict:
    return _dev_hub.ingest_http(payload)


def _apply_profile_volume() -> None:
    audio.set_volume((config.get("volume") or 100) / 100)


def start_drive_sync() -> None:
    """Liga o espelhamento do perfil ativo no Drive: preferências
    (bmo_config.json) + áudios offline-first (Sync & Destroy) + conhecimento.

    No-op pra convidado ou sem sessão — o Bimo segue 100% local. Tokens do
    pareamento PC trazem o client embutido, então funciona até sem
    GOOGLE_CLIENT_ID no .env do aparelho.
    """
    prof = session.current()
    if not prof or session.is_guest():
        return
    creds = google_auth.Credentials(session.tokens_path(prof["sub"]))
    if not creds.ok:
        return
    svc = DriveSync(creds, config_path=config.get_path(),
                    on_pulled=_apply_profile_volume,
                    recordings_dir=session.recordings_dir(),
                    knowledge_dir=session.knowledge_dir(),
                    on_event=show_toast)
    config.on_change = svc.mark_dirty   # cada ajuste no SETTINGS agenda upload
    svc.start()
    _drive_sync["svc"] = svc


def build_initial(app: App):
    # Cache pra reaproveitar a mesma instância de cada ambient — evita criar
    # uma WeatherService nova (e portanto uma thread) toda vez que a home volta.
    ambient_cache: dict = {}

    # Singleton de Todoist (thread + cache vivem aqui)
    todoist = TodoistService()
    # Detector de git updates (só usado pelo clock pra mostrar alerta)
    git_updates = GitUpdatesService()
    # Câmera (AI Camera no Pi). is_available=False quando offline (dev no PC)
    camera = CameraService()
    # Google Calendar (URLs secretas iCal) + disparador de avisos de evento
    calendar = CalendarService()
    alerter = EventAlerter()
    # Telemetria de hardware (tela SISTEMA). No PC mostra "--".
    sysinfo = SysInfoService()
    # Rede: detecção de internet (qualquer SO) + WiFi via nmcli (só no Pi).
    # A status bar passa a mostrar "sem internet" quando offline.
    network = NetworkService()
    theme_state.set_online_getter(lambda: network.online)
    # Casa inteligente (tela CASA): tomadas Tuya/JWcom controladas na LAN.
    # Sem tinytuya (PC) ou sem tomadas no .env -> available=False (tela offline).
    smarthome = SmartHomeService()
    # Coolers (2x) — refrigeração ativa via GPIO 17 (pino 11) e GPIO 23 (pino 16).
    # Liga no atalho da tela SISTEMA e sozinho acima de 60°C (lê a temp do sysinfo).
    cooler = CoolerService(get_temp=lambda: sysinfo.get().temp_c)
    cooler.set_enabled(bool(config.get("cooler_enabled")))
    # Pomodoro é cacheado: o tempo de foco por tarefa (e o estado do timer)
    # sobrevive ao abrir/fechar a tela.
    pomodoro = PomodoroScreen(on_back=app.manager.pop, todoist=todoist)
    # Audição (wake word + Whisper). No PC degrada pra "indisponivel".
    voice = VoiceService()
    # Gravador offline-first (aulas/reuniões): WAV local -> Sync & Destroy
    # no Drive (drive_sync). A pasta é do PERFIL (some no wipe do logout).
    recorder = RecorderService(voice=voice, recordings_dir=session.recordings_dir())
    # Segundo Cérebro: grafo das notas .md espelhadas do Drive (tela CEREBRO)
    knowledge = KnowledgeService(session.knowledge_dir())
    # --- pet: estado emocional + memória + cérebro proativo (autossuficientes,
    # NÃO dependem de câmera/mic). Tudo degrada sozinho se faltar algo. ---
    pet = PetState()
    memory = PetMemory()
    brain = PetBrain(pet, sysinfo=sysinfo, calendar=calendar, todoist=todoist)
    # Secretária: central de lembretes proativos (briefing matinal + prazos +
    # rotinas do Obsidian). Alimentada pelo secretary_tick (frame_hook); a aba
    # HOJE do painel e a voz na telinha consomem daqui.
    reminders = ReminderService()
    # BMO responde via LLM (OpenRouter ou NVIDIA NIM — escolhível em SETTINGS->IA).
    # Degrada sem a chave do provedor ativo (OPENROUTER_API_KEY / NVIDIA_API_KEY).
    # memory dá contexto (nome/fatos) e histórico entre conversas.
    def _push_note_to_drive(path) -> bool:
        svc = _drive_sync.get("svc")
        return bool(svc and svc.push_note(path))

    chat = ChatService(memory=memory, knowledge=knowledge,
                       on_note_saved=_push_note_to_drive, smarthome=smarthome)
    # Voz do BMO (TTS): Edge TTS (Francisca pt-BR) por padrão — incorporado do
    # módulo de laboratório bmo_voz.py. Degrada sem edge-tts/internet.
    # Volume separado em SETTINGS->IA ("Voz BMO" = tts_volume); 0 = mudo.
    tts = TTSService()

    # Botão físico de push-to-talk (GPIO): segura = grava, solta = transcreve
    # + BMO responde. No PC degrada (ok=False); use o botão da tela TESTE.
    def _ptt_done(text):
        # delega pro handler (definido abaixo) que pergunta ao LLM e, se ele
        # pedir, abre a tela correspondente. Late binding resolve o nome.
        handle_ai_response(text)

    ptt_pin = int(os.environ.get("PTT_GPIO", "17"))
    ptt_button = GPIOButton(
        ptt_pin,
        on_press=lambda: voice.ptt_begin(on_done=_ptt_done),
        on_release=voice.ptt_end,
    )

    def cleanup_hardware() -> None:
        """Libera hardware (mic, câmera, GPIO) ANTES do restart por execv.
        Sem isso, libs em C (libcamera, lgpio) deixam fds abertos que
        sobrevivem ao execv e o processo novo não reivindica câmera/botão."""
        try:
            if webui is not None:   # fecha a porta do painel antes do novo bind
                webui.stop()
        except Exception:
            pass
        try:
            voice.set_enabled(False)
        except Exception:
            pass
        try:
            voice.stop_monitor()
        except Exception:
            pass
        try:
            tts.stop()   # corta fala/player externo pendente antes do execv
        except Exception:
            pass
        try:
            camera.stop()
        except Exception:
            pass
        try:
            network.stop()   # encerra a thread de checagem de internet
        except Exception:
            pass
        try:
            cooler.close()   # desliga os fans e libera os pinos GPIO 17/23
        except Exception:
            pass
        try:
            ptt_button.close()
        except Exception:
            pass
        try:
            pet.flush()   # grava afeto/streak antes do execv (não perde o convívio)
        except Exception:
            pass
        # fecha o pin factory do gpiozero (libera todos os pinos)
        try:
            from gpiozero import Device
            if getattr(Device, "pin_factory", None) is not None:
                Device.pin_factory.close()
        except Exception:
            pass
    # Fila de ações dos comandos de voz: o wake-loop roda em thread, então
    # empilhamos a navegação aqui e executamos no main thread (frame_hook).
    voice_queue: list = []
    voice_lock = threading.Lock()

    def voice_enqueue(fn):
        with voice_lock:
            voice_queue.append(fn)

    def _instantiate_ambient(mode):
        if mode == "face":
            return BMOFaceScreen(on_open_home=open_home, camera=camera, tts=tts,
                                 pet_state=pet)
        if mode == "pong":
            return PongAmbientScreen(on_open_home=open_home)
        if mode == "invaders":
            return SpaceInvadersAmbientScreen(on_open_home=open_home)
        if mode == "devhub":
            return DevHubScreen(on_open_home=open_home, dev_hub=_dev_hub,
                                github=_github, ambient=True)
        if mode == "brain":
            return BrainScreen(on_open_home=open_home, knowledge=knowledge,
                               get_sync=lambda: _drive_sync.get("svc"),
                               ambient=True)
        # default: clock
        return ClockScreen(on_open_home=open_home, git_updates=git_updates)

    def make_ambient():
        mode = config.get("ambient_mode")
        if mode not in ambient_cache:
            if mode == "shuffle":
                # cria todas as ambient screens uma vez e deixa o shuffler ciclar
                ambient_cache[mode] = ShufflingAmbientScreen([
                    _instantiate_ambient("clock"),
                    _instantiate_ambient("face"),
                    _instantiate_ambient("brain"),
                    _instantiate_ambient("devhub"),
                    _instantiate_ambient("pong"),
                    _instantiate_ambient("invaders"),
                ])
            else:
                ambient_cache[mode] = _instantiate_ambient(mode)
        return ambient_cache[mode]

    def go_ambient() -> None:
        app.manager.replace(make_ambient())

    def select_ambient(mode: str) -> None:
        config.set_value("ambient_mode", mode)
        go_ambient()

    def open_home() -> None:
        app.manager.push(make_home())

    def make_games_screen():
        return GamesScreen(
            on_back=app.manager.pop,
            games=[
                {
                    "label": "Space Invaders",
                    "draw_icon": draw_space_invaders_icon,
                    "launch": lambda: app.manager.push(
                        SpaceInvadersScreen(on_back=app.manager.pop)
                    ),
                },
                {
                    "label": "Pong",
                    "draw_icon": draw_pong_icon,
                    "launch": lambda: app.manager.push(
                        PongScreen(on_back=app.manager.pop)
                    ),
                },
                {
                    "label": "Flappy",
                    "draw_icon": draw_flappy_icon,
                    "launch": lambda: app.manager.push(
                        FlappyScreen(on_back=app.manager.pop)
                    ),
                },
                {
                    "label": "Snake",
                    "draw_icon": draw_snake_icon,
                    "launch": lambda: app.manager.push(
                        SnakeScreen(on_back=app.manager.pop)
                    ),
                },
                {
                    "label": "Haxball",
                    "draw_icon": draw_haxball_icon,
                    "launch": lambda: app.manager.push(
                        HaxballScreen(on_back=app.manager.pop)
                    ),
                },
            ],
        )

    def open_suspend() -> None:
        # Suspende: display off + FPS baixo. Wake → vai direto pro ambient.
        app.manager.push(SuspendedScreen(on_wake=go_ambient))

    def make_recorder_screen() -> RecorderScreen:
        return RecorderScreen(on_back=app.manager.pop, recorder=recorder,
                              get_sync=lambda: _drive_sync.get("svc"))

    def make_brain_screen() -> BrainScreen:
        return BrainScreen(on_back=app.manager.pop, knowledge=knowledge,
                           get_sync=lambda: _drive_sync.get("svc"))

    def make_devhub_screen() -> DevHubScreen:
        return DevHubScreen(on_back=app.manager.pop, dev_hub=_dev_hub, github=_github)

    def make_sysinfo_screen() -> SysInfoScreen:
        # tela SISTEMA: telemetria + controle dos coolers (atalhos de atualizar/
        # desligar ficam no grid de AJUSTES, não aqui)
        return SysInfoScreen(on_back=app.manager.pop, sysinfo=sysinfo, cooler=cooler)

    def make_smarthome_screen() -> SmartHomeScreen:
        # tela CASA: liga/desliga as tomadas Tuya/JWcom (controle local)
        return SmartHomeScreen(on_back=app.manager.pop, smarthome=smarthome)

    def confirm_shutdown() -> None:
        # tile DESLIGAR do grid: um toque é destrutivo, então confirma antes
        app.manager.push(ConfirmScreen(
            title="DESLIGAR", message="Desligar o BMO agora?",
            on_confirm=do_shutdown, on_cancel=app.manager.pop))

    def confirm_update() -> None:
        # tile ATUALIZAR do grid: baixa o origin/main e reinicia — confirma antes
        app.manager.push(ConfirmScreen(
            title="ATUALIZAR", message="Baixar a ultima versao e reiniciar?",
            on_confirm=do_update, on_cancel=app.manager.pop))

    def make_home() -> HomeScreen:
        push = app.manager.push
        pop = app.manager.pop
        return HomeScreen(
            on_back=go_ambient,
            categories=build_categories(
                on_brain=lambda: push(make_brain_screen()),
                on_aitest=lambda: push(
                    AITestScreen(on_back=pop, voice=voice, camera=camera,
                                 sysinfo=sysinfo, chat=chat, button=ptt_button,
                                 on_respond=handle_ai_response)),
                on_flappy_ai=lambda: push(FlappyTrainScreen(on_back=pop)),
                on_haxball_ai=lambda: push(HaxballTrainScreen(
                    on_back=pop, get_sync=lambda: _drive_sync.get("svc"))),
                on_sleep=lambda: push(
                    SleepScreen(on_back=pop, on_select_mode=select_ambient)),
                on_suspend=open_suspend,
                on_tasks=lambda: push(TasksScreen(on_back=pop, todoist=todoist)),
                on_agenda=lambda: push(AgendaScreen(on_back=pop, calendar=calendar)),
                on_pomodoro=lambda: push(pomodoro),
                on_recorder=lambda: push(make_recorder_screen()),
                on_games=lambda: push(make_games_screen()),
                on_photo=lambda: push(PhotoScreen(
                    on_back=pop, camera=camera,
                    on_open_gallery=lambda: push(
                        GalleryScreen(on_back=pop, photos_dir=PHOTOS_DIR)),
                )),
                on_dev=lambda: push(make_devhub_screen()),
                on_smarthome=lambda: push(make_smarthome_screen()),
                on_settings=lambda: push(make_settings()),
                on_sysinfo=lambda: push(make_sysinfo_screen()),
                on_shutdown=confirm_shutdown,
                on_update=confirm_update,
            ),
        )

    def on_setting_change(key, value) -> None:
        if key == "voice_enabled":
            voice.set_enabled(bool(value))
        elif key == "mic_device" and config.get("voice_enabled"):
            # reabre a escuta no novo microfone
            voice.set_enabled(False)
            voice.set_enabled(True)

    def do_logout() -> None:
        """Wipe & Load: backup final no Drive -> wipe do perfil -> reinicia.

        O restart por execv garante que NENHUM cache do usuário anterior
        (threads, memória do pet, tokens) sobreviva à troca. O processo novo
        cai na tela de LOGIN (sem sessão ativa)."""
        try:
            recorder.stop()   # fecha .part -> .wav pra entrar no flush
        except Exception:
            pass
        svc = _drive_sync.get("svc")
        if svc is not None:
            try:
                svc.flush()   # sobe preferências + áudios não sincronizados
            except Exception:
                pass
            try:
                svc.stop()
            except Exception:
                pass
        config.on_change = None
        try:
            cleanup_hardware()
        except Exception:
            pass
        session.logout()
        pygame.quit()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def do_connect() -> None:
        """SETTINGS -> CONTA -> "Conectar conta": abre o LOGIN (QR) por cima.

        É a saída do modo local/convidado (e serve pra trocar de conta SEM
        wipe — o perfil anterior fica guardado). No sucesso, ativa o perfil
        novo e reinicia limpo via execv: o processo novo já boota logado."""
        def _ok(user: dict, tokens: dict) -> None:
            session.login(user, tokens)
            try:
                cleanup_hardware()
            except Exception:
                pass
            pygame.quit()
            os.execv(sys.executable, [sys.executable, *sys.argv])

        app.manager.push(LoginScreen(on_success=_ok, on_guest=app.manager.pop,
                                     pair_ip=local_ip(), guest_label="VOLTAR"))

    def open_wifi() -> None:
        app.manager.push(WifiScreen(
            net=network, camera=camera,
            on_back=app.manager.pop, push=app.manager.push, pop=app.manager.pop))

    def make_settings() -> SettingsScreen:
        return SettingsScreen(
            on_back=app.manager.pop,
            on_open=app.manager.push,
            on_change=on_setting_change,
            mic_options=voice.list_input_devices,
            on_cleanup=cleanup_hardware,
            tts=tts,
            on_logout=do_logout,
            on_connect=do_connect,
            on_open_wifi=open_wifi,
        )

    # ---- comandos de voz -> navegação (executados no main thread) ----
    def _cmd(fn):
        return lambda: voice_enqueue(fn)

    voice.register_command(["agenda", "calendario", "compromisso"],
                           _cmd(lambda: app.manager.push(AgendaScreen(on_back=app.manager.pop, calendar=calendar))))
    voice.register_command(["foco", "pomodoro", "concentra"],
                           _cmd(lambda: app.manager.push(pomodoro)))
    voice.register_command(["tarefa", "tarefas", "kanban", "board"],
                           _cmd(lambda: app.manager.push(TasksScreen(on_back=app.manager.pop, todoist=todoist))))
    voice.register_command(["sistema", "hardware", "temperatura", "cpu"],
                           _cmd(lambda: app.manager.push(make_sysinfo_screen())))
    voice.register_command(["casa", "tomada", "tomadas", "luz", "smart house"],
                           _cmd(lambda: app.manager.push(make_smarthome_screen())))
    voice.register_command(["foto", "fotos", "camera"],
                           _cmd(lambda: app.manager.push(
                               PhotoScreen(on_back=app.manager.pop, camera=camera,
                                           on_open_gallery=lambda: app.manager.push(
                                               GalleryScreen(on_back=app.manager.pop, photos_dir=PHOTOS_DIR))))))
    voice.register_command(["flappy", "passarinho", "voar"],
                           _cmd(lambda: app.manager.push(FlappyScreen(on_back=app.manager.pop))))
    voice.register_command(["treino", "treinar", "neuroevolucao", "flappy ia"],
                           _cmd(lambda: app.manager.push(FlappyTrainScreen(on_back=app.manager.pop))))
    voice.register_command(["snake", "cobra", "cobrinha"],
                           _cmd(lambda: app.manager.push(SnakeScreen(on_back=app.manager.pop))))
    voice.register_command(["haxball", "futebol", "bola", "gol"],
                           _cmd(lambda: app.manager.push(HaxballScreen(on_back=app.manager.pop))))
    voice.register_command(["treina time", "treino haxball", "treina futebol"],
                           _cmd(lambda: app.manager.push(HaxballTrainScreen(
                               on_back=app.manager.pop,
                               get_sync=lambda: _drive_sync.get("svc")))))
    voice.register_command(["gravador", "gravar", "gravacao"],
                           _cmd(lambda: app.manager.push(make_recorder_screen())))
    voice.register_command(["cerebro", "conhecimento", "notas", "obsidian"],
                           _cmd(lambda: app.manager.push(make_brain_screen())))
    voice.register_command(["dev", "dev hub", "programacao", "codigo", "git"],
                           _cmd(lambda: app.manager.push(make_devhub_screen())))
    voice.register_command(["configura", "ajuste", "settings"], _cmd(lambda: app.manager.push(make_settings())))
    voice.register_command(["menu", "inicio", "casa", "home"], _cmd(open_home))
    voice.register_command(["relogio", "horas", "tela inicial", "descanso"], _cmd(go_ambient))

    def do_update() -> None:
        """Baixa a última versão (git reset --hard origin/main) e reinicia.
        Libera o hardware antes do execv (ver cleanup_hardware)."""
        try:
            cleanup_hardware()
        except Exception:
            pass
        root = str(config.REPO_ROOT)
        try:
            subprocess.run(["git", "-C", root, "fetch", "--quiet", "origin", "main"],
                           timeout=60, check=False)
            subprocess.run(["git", "-C", root, "reset", "--hard", "origin/main"],
                           timeout=60, check=False)
        except Exception:
            pass
        pygame.quit()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def do_shutdown() -> None:
        """Desliga a Raspberry. Libera o hardware antes (ver cleanup_hardware)."""
        try:
            cleanup_hardware()
        except Exception:
            pass
        pygame.quit()
        if sys.platform == "win32":
            os.system("shutdown /s /t 0")
        else:
            rc = os.system("sudo -n shutdown -h now")
            if rc != 0:
                os.system("shutdown -h now")
        sys.exit(0)

    # ---- LLM pode abrir telas / agir: chave (do JSON do chat) -> ação ----
    # As chaves espelham SCREENS_DOC em services/chat.py.
    screen_actions = {
        "agenda": lambda: app.manager.push(AgendaScreen(on_back=app.manager.pop, calendar=calendar)),
        "tarefas": lambda: app.manager.push(TasksScreen(on_back=app.manager.pop, todoist=todoist)),
        "foco": lambda: app.manager.push(pomodoro),
        "sistema": lambda: app.manager.push(make_sysinfo_screen()),
        "foto": lambda: app.manager.push(
            PhotoScreen(on_back=app.manager.pop, camera=camera,
                        on_open_gallery=lambda: app.manager.push(
                            GalleryScreen(on_back=app.manager.pop, photos_dir=PHOTOS_DIR)))),
        "jogos": lambda: app.manager.push(make_games_screen()),
        "pong": lambda: app.manager.push(PongScreen(on_back=app.manager.pop)),
        "invaders": lambda: app.manager.push(SpaceInvadersScreen(on_back=app.manager.pop)),
        "flappy": lambda: app.manager.push(FlappyScreen(on_back=app.manager.pop)),
        "snake": lambda: app.manager.push(SnakeScreen(on_back=app.manager.pop)),
        "gravador": lambda: app.manager.push(make_recorder_screen()),
        "cerebro": lambda: app.manager.push(make_brain_screen()),
        "devhub": lambda: app.manager.push(make_devhub_screen()),
        "casa": lambda: app.manager.push(make_smarthome_screen()),
        "configuracoes": lambda: app.manager.push(make_settings()),
        # relógio explícito (NÃO o ambient configurado, que pode ser face/pong)
        "relogio": lambda: app.manager.replace(_instantiate_ambient("clock")),
        "home": open_home,
        "atualizar": do_update,
    }

    def _apply_power(power: dict) -> None:
        """Executa a ação de tomada pedida pela IA (campo "power" do chat).
        device: "tomadaN" ou "todas" (tolerante a variações); on liga/desliga.
        smarthome.set/set_all são thread-safe (fila), então roda direto aqui."""
        dev = (power.get("device") or "").strip().lower()
        on = bool(power.get("on"))
        if any(w in dev for w in ("tod", "all", "tudo", "amba")):
            smarthome.set_all(on)
        else:
            digits = "".join(c for c in dev if c.isdigit())
            if not digits:
                return
            smarthome.set(f"t{digits}", on)
        # sem frase própria da IA? fala uma confirmação curta.
        msg = (getattr(chat, "last_msg", "") or "").strip()
        if not msg or msg == "...":
            chat.last_msg = ("Ligando" if on else "Desligando") + " a tomada."

    def handle_ai_response(text: str) -> None:
        """Roda na thread de voz: manda o texto pro LLM e, conforme a resposta,
        cria tarefa no Todoist e/ou enfileira a navegação pra main thread."""
        if not (text and chat.available):
            return
        # conversar conta como convívio (sobe afeto e tira o BMO da solidão)
        try:
            pet.touch("talk")
        except Exception:
            pass
        mood = ""
        try:
            mood = pet.get().mood
        except Exception:
            pass
        chat.ask(text, mood=mood)   # atualiza last_msg / last_error / last_screen / last_task
        screen_key = (getattr(chat, "last_screen", "") or "").strip()
        # Pediu pra IA ABRIR uma tela? Corta a resposta verbosa da LLM e usa a
        # frase de cache daquela tela (instantânea). A msg da LLM é ignorada.
        # (Isso NÃO fala ao abrir manualmente — só quando o pedido vem pela IA.)
        phrase = SCREEN_PHRASES.get(screen_key)
        if phrase:
            chat.last_msg = phrase
        task = (getattr(chat, "last_task", "") or "").strip()
        if task:
            try:
                if todoist.create(task) and tts is not None:
                    tts.speak("Tarefa criada.")   # cacheado = instantâneo
            except Exception:
                pass
        # IA mandou ligar/desligar uma tomada? (campo "power" do JSON do chat)
        power = getattr(chat, "last_power", None)
        if power and getattr(smarthome, "available", False):
            try:
                _apply_power(power)
            except Exception:
                pass
        action = screen_actions.get(screen_key)
        if action is not None:
            voice_enqueue(action)

    def remote_chat(text: str) -> dict:
        """Mensagem DIGITADA vinda do PC (scripts/bimo_chat.py): roda o mesmo
        caminho da fala — LLM + memória + tool das notas + abrir telas + voz
        na rasp — e devolve a resposta pro PC. Embrião da extensão desktop."""
        if not chat.available:
            return {"msg": "", "error":
                    "LLM indisponivel (provedor/chave em SETTINGS -> IA)"}
        handle_ai_response(text)
        msg = (getattr(chat, "last_msg", "") or "").strip()
        return {
            "msg": "" if msg == "..." else msg,
            "screen": getattr(chat, "last_screen", ""),
            "task": getattr(chat, "last_task", ""),
            "error": getattr(chat, "last_error", ""),
            "notes": getattr(chat, "last_notes", []),
            "rag": getattr(chat, "last_rag", []),   # quais notas o LLM consultou
        }

    _remote_chat["fn"] = remote_chat

    # ---- painel web (localhost temático): ajustes + espaço interno + chat ----
    def web_state() -> dict:
        """Snapshot do 'mundo interno' do BMO pro painel: humor/afeto/energia/
        streak, o que ele lembra de você e a telemetria da Pi. Tudo via getters
        thread-safe que já existem — nada bloqueia."""
        snap = pet.get()
        sysd = sysinfo.get()
        try:
            graph = knowledge.scan()
            notes, links = len(graph.notes), len(graph.edges)
        except Exception:
            notes, links = 0, 0
        last = (getattr(chat, "last_msg", "") or "").strip()
        return {
            "pet": {"mood": snap.mood, "energy": round(snap.energy, 3),
                    "affection": round(snap.affection, 1), "streak": snap.streak,
                    "idle_s": int(snap.idle_s), "present": snap.present},
            "memory": {"name": memory.name, "facts": memory.facts()},
            "sys": {"cpu": sysd.cpu_pct, "temp": sysd.temp_c, "ram_pct": sysd.ram_pct,
                    "gpu": sysd.gpu_pct, "volts": sysd.volts, "ok": sysd.ok},
            "knowledge": {"notes": notes, "links": links},
            "bmo_says": "" if last == "..." else last,
        }

    def web_set_config(key: str, value) -> dict:
        """Aplica uma config vinda do painel, espelhando os efeitos vivos do
        SETTINGS (volume, voz, coolers). Só aceita chaves conhecidas e coage o
        tipo pelo DEFAULT, então o painel não quebra a config."""
        if key not in config.DEFAULTS:
            return {"ok": False, "error": "config desconhecida"}
        default = config.DEFAULTS[key]
        try:
            if isinstance(default, bool):
                value = value in (True, "true", "True", 1, "1", "on")
            elif isinstance(default, int):       # bool já tratado acima
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            else:
                value = "" if value is None else str(value)
        except (TypeError, ValueError):
            return {"ok": False, "error": "valor invalido"}
        config.set_value(key, value)
        if key == "volume":
            audio.set_volume(value / 100)
        elif key == "cooler_enabled":
            try:
                cooler.set_enabled(bool(value))
            except Exception:
                pass
        try:
            on_setting_change(key, value)   # reabre o mic em voice_enabled/mic_device
        except Exception:
            pass
        return {"ok": True, "key": key, "value": config.get(key)}

    def web_memory(payload: dict) -> dict:
        """Edita a memória do BMO pelo painel (espaço interno): nome, fatos e
        'esquecer tudo'. Usa a API thread-safe do PetMemory."""
        action = (payload.get("action") or "").strip()
        if action == "set_name":
            memory.set_name(payload.get("name", ""))
        elif action == "add_fact":
            memory.add_facts([payload.get("fact", "")])
        elif action == "del_fact":
            memory.remove_fact(payload.get("fact", ""))
        elif action == "clear":
            memory.clear()
        else:
            return {"ok": False, "error": "acao invalida"}
        return {"ok": True, "name": memory.name, "facts": memory.facts()}

    def web_brain() -> dict:
        """Snapshot do 'cérebro' (RAG do Obsidian) pro painel: resumo do grafo,
        lista das notas (mais recentes primeiro) e o que o RAG consultou na
        última resposta — pra o dono ver quais arquivos foram pro LLM."""
        g = knowledge.scan()
        notes = []
        for n in sorted(g.notes.values(), key=lambda x: -x.mtime):
            notes.append({
                "id": n.id, "title": n.title,
                "tags": list(n.tags), "links": g.degree(n.id),
                "preview": " ".join(n.preview)[:160], "mtime": n.mtime,
            })
        return {
            "summary": {"notes": len(g.notes), "links": len(g.edges),
                        "ghosts": len(g.ghosts)},
            "notes": notes,
            "last_rag": getattr(chat, "last_rag", []),
        }

    def web_brain_search(query: str) -> dict:
        """Roda a MESMA busca do RAG (knowledge.search) pro dono testar o que o
        BMO acharia — mostra título, score e trecho de cada acerto."""
        q = (query or "").strip()
        if not q:
            return {"query": "", "hits": []}
        try:
            hits = knowledge.search(q, k=6)
        except Exception as e:
            return {"query": q, "hits": [], "error": str(e)[:80]}
        return {"query": q, "hits": [
            {"title": h["title"], "score": round(float(h.get("score", 0)), 1),
             "tags": h.get("tags", []), "snippet": (h.get("snippet", "") or "")[:300]}
            for h in hits]}

    def web_brain_note(note_id: str) -> dict:
        """Conteúdo integral de UMA nota do cérebro pro painel (visualização
        Obsidian). Aceita o id (stem minúsculo) OU o título; lê o .md direto
        pelo path do grafo."""
        g = knowledge.scan()
        nid = (note_id or "").strip().lower()
        note = g.notes.get(nid)
        if note is None:
            for n in g.notes.values():
                if n.title.lower() == nid:
                    note = n
                    break
        if note is None:
            return {"error": "nota nao encontrada"}
        try:
            body = note.path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            body = ""
        return {"id": note.id, "title": note.title, "tags": list(note.tags),
                "links": g.degree(note.id), "mtime": note.mtime, "body": body}

    def web_tasks() -> dict:
        """Snapshot do Kanban (Todoist) pro painel: colunas TO-DO/DOING/DONE com
        suas tarefas. Getter thread-safe — não bloqueia o frame."""
        snap = todoist.get()
        cols = todoist.by_section()
        return {
            "ok": bool(snap.ok), "error": snap.error,
            "columns": [
                {"key": k, "label": SECTION_LABELS.get(k, k.upper()),
                 "tasks": [{"id": t.id, "content": t.content, "due": t.due}
                           for t in cols.get(k, [])]}
                for k in SECTION_NAMES
            ],
        }

    def web_tasks_action(payload: dict) -> dict:
        """Cria ou move uma tarefa do Kanban pelo painel. todoist.create/move já
        rodam em thread própria (otimistas), então chamamos direto."""
        action = (payload.get("action") or "").strip()
        if action == "create":
            ok = todoist.create(payload.get("content", ""),
                                payload.get("section", "to-do") or "to-do")
            return {"ok": bool(ok)}
        if action == "move":
            ok = todoist.move(payload.get("id", ""), payload.get("target", ""))
            return {"ok": bool(ok)}
        return {"ok": False, "error": "acao invalida"}

    def web_agenda() -> dict:
        """Eventos de HOJE (Calendar) pro painel. Snapshot thread-safe."""
        snap = calendar.get()
        events = []
        for e in snap.events:
            events.append({
                "title": e.title, "all_day": bool(e.all_day),
                "start": "" if e.all_day else e.start.strftime("%H:%M"),
                "end": "" if e.all_day else e.end.strftime("%H:%M"),
                "start_iso": e.start.isoformat(), "cal": e.cal_label,
            })
        return {"ok": bool(snap.ok), "error": snap.error, "events": events}

    def web_smarthome() -> dict:
        """Estado das tomadas smart pro painel."""
        if not getattr(smarthome, "available", False):
            return {"ok": False, "error": getattr(smarthome, "status", "indisponivel"),
                    "devices": []}
        return {"ok": True, "devices": smarthome.get_devices()}

    def web_smarthome_action(payload: dict) -> dict:
        """Liga/desliga/toggle das tomadas pelo painel. Comandos thread-safe
        (fila interna), refletem otimista na hora."""
        if not getattr(smarthome, "available", False):
            return {"ok": False, "error": "casa indisponivel"}
        action = (payload.get("action") or "").strip()
        key = (payload.get("key") or "").strip()
        on = bool(payload.get("on"))
        if action == "set":
            smarthome.set(key, on)
        elif action == "toggle":
            smarthome.toggle(key)
        elif action == "all":
            smarthome.set_all(on)
        else:
            return {"ok": False, "error": "acao invalida"}
        return {"ok": True, "devices": smarthome.get_devices()}

    def web_mic(action: str) -> dict:
        """Push-to-talk remoto: o painel segura o botão (start) e solta (stop);
        o BMO ouve pelo PRÓPRIO mic e responde no aparelho (igual ao botão
        físico). O on_done reaproveita o handler da IA."""
        action = (action or "").strip()
        if action == "start":
            voice.ptt_begin(on_done=_ptt_done)
        elif action == "stop":
            voice.ptt_end()
        else:
            return {"ok": False, "error": "acao invalida"}
        return {"ok": True}

    def web_update() -> dict:
        """Atualiza a versão (git reset --hard origin/main) e reinicia, igual ao
        tile ATUALIZAR. Enfileira pro main thread: do_update libera o hardware e
        chama execv — não pode rodar na thread do request."""
        voice_enqueue(do_update)
        return {"ok": True, "msg": "baixando a ultima versao e reiniciando..."}

    def web_notifications() -> dict:
        """Central de lembretes (aba HOJE): briefing + cutucadas de prazo/rotina."""
        return reminders.snapshot()

    def web_notification_read(payload: dict) -> dict:
        """Marca um aviso (ou todos, {all:true}) como lido."""
        if payload.get("all"):
            reminders.mark_read(every=True)
        else:
            reminders.mark_read(str(payload.get("id", "")))
        return reminders.snapshot()

    # Sobe o painel (no-op se desligado na config ou porta ocupada). Reaproveita
    # remote_chat: o chat web abre telas / cria tarefas / fala no aparelho, igual
    # ao push-to-talk. Mesmo modelo de confiança da rede local (ver pairing.py).
    webui = None
    if config.get("webui_enabled"):
        webui = WebUIServer(on_chat=remote_chat, get_state=web_state,
                            list_mics=voice.list_input_devices,
                            on_set_config=web_set_config, on_memory=web_memory,
                            get_brain=web_brain, on_brain_search=web_brain_search,
                            on_brain_note=web_brain_note,
                            camera=camera, on_mic=web_mic,
                            get_tasks=web_tasks, on_tasks=web_tasks_action,
                            get_agenda=web_agenda,
                            get_smarthome=web_smarthome, on_smarthome=web_smarthome_action,
                            on_update=web_update,
                            get_notifications=web_notifications,
                            on_notification_read=web_notification_read)
        if webui.start():
            ip = local_ip()
            extra = f"  (rede: http://{ip}:{webui.port})" if ip else ""
            print(f"[webui] painel do BMO em {webui.url()}{extra}")

    # Telas onde o BMO pode falar sozinho (ambientes/descanso) — nunca durante
    # jogos ativos, menus ou suspensão (tela apagada).
    TALKATIVE_SCREENS = (BMOFaceScreen, ClockScreen, PongAmbientScreen,
                         SpaceInvadersAmbientScreen, ShufflingAmbientScreen)

    # ---- secretária: briefing matinal + cutucadas de prazo/rotina ----
    _secretary = {"last_tick": 0.0, "last_spoke": 0.0}
    SECRETARY_TICK_S = 30.0       # recalcula os lembretes a cada 30s
    SECRETARY_SPEAK_GAP_S = 25.0  # fala no máximo 1 lembrete a cada 25s

    def _build_briefing(today: dt.date) -> str:
        lines = [f"Resumo de hoje ({today.strftime('%d/%m')}):"]
        try:
            snap = calendar.get()
            evs = list(getattr(snap, "events", []) or []) if getattr(snap, "ok", False) else []
        except Exception:
            evs = []
        for e in evs[:6]:
            when = "dia todo" if getattr(e, "all_day", False) else e.start.strftime("%H:%M")
            lines.append(f"- {when}  {e.title}")
        today_s = today.isoformat()
        tom_s = (today + dt.timedelta(days=1)).isoformat()
        try:
            tsnap = todoist.get()
            tasks = list(getattr(tsnap, "tasks", []) or []) if getattr(tsnap, "ok", False) else []
        except Exception:
            tasks = []
        for t in tasks:
            if getattr(t, "section_key", "") == "done":
                continue
            due = (getattr(t, "due", "") or "")[:10]
            if due == today_s:
                lines.append(f"- tarefa hoje: {t.content}")
            elif due == tom_s:
                lines.append(f"- tarefa amanhã: {t.content}")
        try:
            for it in routines_due_today(load_routines(knowledge.dir), today):
                tag = f" #{it['area']}" if it["area"] else ""
                if it["antec"] == 1:
                    lines.append(f"- amanhã: {it['text']} (prepare hoje){tag}")
                elif it["antec"] >= 2:
                    lines.append(f"- em {it['antec']} dias: {it['text']}{tag}")
                else:
                    lines.append(f"- {it['text']}{tag}")
        except Exception:
            pass
        if len(lines) == 1:
            lines.append("- nada marcado. Dia livre.")
        return "\n".join(lines)

    def secretary_tick() -> None:
        """Recalcula os lembretes proativos (rotinas + prazos + briefing) e os
        joga na central. Roda no main thread (frame_hook), com throttle. Gated só
        por briefing_enabled — independe do 'BMO fala sozinho' (que só controla a
        VOZ; o painel sempre recebe)."""
        if not config.get("briefing_enabled"):
            return
        today = dt.date.today()
        # 1) rotinas que disparam hoje -> lembrete + auto-cria a task (1x/ocorrência)
        try:
            for it in routines_due_today(load_routines(knowledge.dir), today):
                area = it["area"]
                if it["antec"] == 1:
                    txt = f"Amanhã: {it['text']} — prepare hoje"
                elif it["antec"] >= 2:
                    txt = f"Em {it['antec']} dias: {it['text']}"
                else:
                    txt = it["text"]
                if area:
                    txt += f"  ·  #{area}"
                created = reminders.add(txt, area=area, kind="routine",
                                        when=it["occur"],
                                        key=f"rt:{it['key']}:{it['occur']}")
                if created:
                    try:
                        todoist.create(it["text"])
                    except Exception:
                        pass
        except Exception:
            pass
        # 2) tarefas com prazo hoje/amanhã -> cutucada (1x/dia por task)
        try:
            tsnap = todoist.get()
            if getattr(tsnap, "ok", False):
                today_s = today.isoformat()
                tom_s = (today + dt.timedelta(days=1)).isoformat()
                for t in getattr(tsnap, "tasks", []) or []:
                    if getattr(t, "section_key", "") == "done":
                        continue
                    due = (getattr(t, "due", "") or "")[:10]
                    if due == today_s:
                        reminders.add(f"Tarefa para hoje: {t.content}", kind="task",
                                      when=due, key=f"due:{t.id}:{due}")
                    elif due == tom_s:
                        reminders.add(f"Tarefa para amanhã: {t.content}", kind="task",
                                      when=due, key=f"due:{t.id}:{due}")
        except Exception:
            pass
        # 3) briefing matinal — 1x/dia, a partir do horário configurado
        bt = str(config.get("briefing_time") or "08:00")
        try:
            hh, mm = (int(x) for x in bt.split(":")[:2])
        except Exception:
            hh, mm = 8, 0
        nowdt = dt.datetime.now()
        bkey = f"briefing:{today.isoformat()}"
        if (nowdt.hour, nowdt.minute) >= (hh, mm) and not reminders.fired_today(bkey):
            reminders.add(_build_briefing(today), kind="briefing", key=bkey)

    def _speak_reminder_text(item: dict) -> str:
        """Texto pro TTS — tira bullets/símbolos (o motor de voz engasga neles)."""
        t = (item.get("text") or "").replace("\n", ". ").replace("- ", "")
        for ch in ("•", "#", "·"):
            t = t.replace(ch, "")
        if item.get("kind") == "briefing":
            t = "Bom dia! " + t
        return " ".join(t.split())

    def frame_hook(_dt: float) -> None:
        # Roda todo frame (main thread).
        # 0) pareamento pelo PC pendente (tokens de Drive completo)
        _drain_pair()
        # 1) drena comandos de voz pendentes (a thread de voz só enfileira)
        while True:
            with voice_lock:
                fn = voice_queue.pop(0) if voice_queue else None
            if fn is None:
                break
            try:
                fn()
            except Exception:
                pass
        # 1.5) secretária: recalcula os lembretes (briefing/prazos/rotinas) com
        # throttle. Sempre roda (independe do 'fala sozinho') pra o painel receber.
        now_t = time.time()
        if now_t - _secretary["last_tick"] >= SECRETARY_TICK_S:
            _secretary["last_tick"] = now_t
            try:
                secretary_tick()
            except Exception:
                pass
        # 2) proatividade: o BMO puxa conversa sozinho (com parcimônia), só em
        # telas tagarelas e quando não está ocupado ouvindo/pensando/falando.
        if config.get("pet_proactive"):
            cur = app.manager.current
            busy = (getattr(voice, "busy", False) or getattr(tts, "speaking", False)
                    or (getattr(chat, "last_msg", "") or "").strip() == "...")
            if isinstance(cur, TALKATIVE_SCREENS) and not busy:
                said = False
                # lembretes da secretária têm prioridade — fala 1 de cada vez
                if now_t - _secretary["last_spoke"] >= SECRETARY_SPEAK_GAP_S:
                    pend = reminders.unspoken()
                    if pend:
                        order = {"briefing": 0, "task": 1, "routine": 2}
                        pend.sort(key=lambda r: order.get(r.get("kind"), 9))
                        item = pend[0]
                        bmo_say(_speak_reminder_text(item))
                        reminders.mark_spoke(item["id"])
                        _secretary["last_spoke"] = now_t
                        said = True
                if not said:
                    try:
                        phrase = brain.tick()
                    except Exception:
                        phrase = None
                    if phrase:
                        bmo_say(phrase)
        # 3) se um evento está próximo, empilha a AlertScreen por cima de
        # qualquer tela (relógio, jogo, suspended...)
        if isinstance(app.manager.current, AlertScreen):
            return
        snap = calendar.get()
        if not snap.ok:
            return
        warn = int(config.get("event_warning_min") or 10)
        ev = alerter.check(snap.events, warn)
        if ev is not None:
            app.manager.push(AlertScreen(event=ev, on_dismiss=app.manager.pop))

    app.frame_hook = frame_hook

    # estado do rodapé de voz: guarda a última resposta + até quando exibi-la.
    # spoke_at = quando o BMO falou por último (pra não duplicar com o anúncio de tela)
    ai_overlay = {"msg": "", "until": 0.0, "spoke_at": 0.0}
    RESP_SHOW_S = 7.0

    def bmo_say(text: str, mood: str | None = None) -> None:
        """BMO fala espontaneamente (proatividade): mostra no rodapé E fala, sem
        duplicar com o auto-speak do overlay (marca ai_overlay['msg'] antes)."""
        text = (text or "").strip()
        if not text:
            return
        now = time.time()
        ai_overlay["msg"] = text       # marca ANTES pra o overlay não re-falar
        ai_overlay["until"] = now + RESP_SHOW_S
        ai_overlay["spoke_at"] = now
        try:
            chat.last_msg = text       # o rodapé exibe via draw_voice_overlay
        except Exception:
            pass
        if tts is not None:
            try:
                m = mood if mood is not None else pet.get().mood
                tts.speak(text, mood=m)
            except Exception:
                pass

    def draw_voice_overlay(canvas) -> None:
        """Rodapé POR CIMA de qualquer tela: GRAVANDO / PENSANDO durante o
        push-to-talk e a resposta do BMO por alguns segundos depois."""
        busy = getattr(voice, "busy", False)
        status = (getattr(voice, "status", "") or "").lower()
        now = time.time()
        msg = (getattr(chat, "last_msg", "") or "").strip()
        thinking = (msg == "...")   # LLM em andamento (chat.ask marca "...")
        # detecta nova resposta do BMO pra exibir por RESP_SHOW_S segundos
        if msg and msg != "..." and msg != ai_overlay["msg"]:
            ai_overlay["msg"] = msg
            ai_overlay["until"] = now + RESP_SHOW_S
            # fala a resposta (conversa OU descrição de visão — ambas caem aqui).
            # speak() é não-bloqueante (fila/thread) e respeita o tts_volume.
            # passa o humor do pet pra voz sair com a emoção certa (Edge dinâmico).
            if tts is not None:
                try:
                    try:
                        mood = pet.get().mood
                    except Exception:
                        mood = ""
                    tts.speak(msg, mood=mood)
                    ai_overlay["spoke_at"] = now
                except Exception:
                    pass
        showing_resp = now < ai_overlay["until"] and bool(ai_overlay["msg"])
        toast_active = bool(_toast["msg"]) and now < _toast["until"]
        if not (busy or thinking or showing_resp or toast_active):
            return

        if busy and ("grav" in status or "ouv" in status):
            label, color, body = "GRAVANDO", Colors.RED, ""
        elif busy or thinking:
            label, color, body = "PENSANDO", Colors.YELLOW, ""
        elif showing_resp:
            label, color, body = "BMO", Colors.CYAN, ai_overlay["msg"]
        else:
            # toast do sync (não-intrusivo): "Sincronizacao com o Drive concluida"
            label, color, body = "DRIVE", Colors.GREEN_BTN, _toast["msg"]

        w, h = LOGICAL_SIZE
        bar_h = 16
        strip = pygame.Surface((w, bar_h))
        strip.set_alpha(205)
        strip.fill((0, 0, 0))
        canvas.blit(strip, (0, h - bar_h))
        cy = h - bar_h // 2
        pygame.draw.circle(canvas, color, (8, cy), 3)
        lbl = render_text(label, 9, color, pixel=False)
        canvas.blit(lbl, lbl.get_rect(midleft=(16, cy)))
        if body:
            avail = w - (16 + lbl.get_width() + 8) - 6
            maxn = max(8, avail // 4)   # ~4px por char no font 8
            body = body if len(body) <= maxn else body[: maxn - 1] + "."
            img = render_text(body, 8, Colors.WHITE, pixel=False)
            canvas.blit(img, img.get_rect(midleft=(16 + lbl.get_width() + 8, cy)))

    app.overlay_hook = draw_voice_overlay

    # Botão de mic virtual: aparece nas telas com show_mic_button=True
    # (descanso, foco, kanban, agenda). Toque grava a fala e manda pro LLM —
    # mesmo caminho do push-to-talk físico.
    app.mic_button = MicButton(voice=voice, on_text=handle_ai_response)

    # OBS: o anúncio de tela NÃO é feito a cada abertura — só quando o usuário
    # PEDE pra IA abrir (ver handle_ai_response, que troca a msg da LLM pela
    # frase de cache da tela). Abrir manualmente pelo carrossel é silencioso.

    # Saudação no boot (por horário) + uma falinha do BMO — ambas cacheadas.
    if tts is not None:
        try:
            h = time.localtime().tm_hour
            greet = "Bom dia." if 5 <= h < 12 else "Boa tarde." if 12 <= h < 18 else "Boa noite."
            tts.speak(greet)
            tts.speak("BMO online.")
        except Exception:
            pass

    return make_ambient()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fullscreen", action="store_true")
    args = parser.parse_args()

    # reativa a sessão gravada (profiles/_active) ANTES de ler o config:
    # com usuário logado, config.get() já lê as preferências DELE.
    session.restore()

    # mixer precisa ser inicializado ANTES do pygame.init (App.__init__)
    # pra os pre_init params (sample rate, buffer) valerem
    audio.init()
    audio.set_volume((config.get("volume") or 100) / 100)

    app = App(fullscreen=args.fullscreen)

    def _after_login() -> None:
        _apply_profile_volume()   # volume/brilho/tema do perfil valem já
        start_drive_sync()
        app.manager.replace(build_initial(app))

    # Pareamento pelo PC (scripts/bimo_drive_login.py): recebe tokens com
    # Drive COMPLETO pela rede local — o QR (device flow) é limitado pelo
    # Google ao drive.file, que não enxerga a vault sincada pelo Drive Desktop.
    def _apply_pair(user: dict, tokens: dict) -> None:
        prof = session.current()
        if prof is None:
            # estava na tela LOGIN: o pareamento é o próprio login
            session.login(user, tokens)
            _after_login()
            show_toast(f"Drive completo: {user.get('email', '')}")
            return
        if session.is_guest():
            show_toast("Saia do modo convidado (SETTINGS) e pareie de novo")
            return
        if prof.get("sub") != user.get("sub"):
            show_toast("Conta diferente da sessao — troque o usuario antes")
            return
        # mesma conta: troca os tokens (drive.file -> drive completo) e
        # religa o sync, que já enxerga o Drive inteiro
        svc = _drive_sync.get("svc")
        if svc is not None:
            try:
                svc.stop()
            except Exception:
                pass
            _drive_sync["svc"] = None
        google_auth.Credentials.save_initial(
            session.tokens_path(prof["sub"]), tokens)
        config.on_change = None
        start_drive_sync()
        show_toast("Drive completo conectado!")

    _pair_apply["fn"] = _apply_pair
    pairing = PairingServer(on_pair=_on_pair_request, on_chat=_on_remote_chat,
                            on_dev=_on_dev_event)
    pairing.start()
    _github.start()

    if session.current() is None and google_auth.available():
        # sem sessão: tela de LOGIN (QR + device flow) antes de tudo.
        # Os serviços (threads, câmera, TTS...) só sobem APÓS o login.
        def _on_success(user: dict, tokens: dict) -> None:
            session.login(user, tokens)
            _after_login()

        def _on_guest() -> None:
            session.login_guest()
            _after_login()

        initial = LoginScreen(on_success=_on_success, on_guest=_on_guest,
                              pair_ip=local_ip())
        # build_initial ainda não rodou: drena o pareamento por aqui
        app.frame_hook = lambda _dt: _drain_pair()
    else:
        # sessão ativa (reboot) OU sem GOOGLE_CLIENT_ID (modo legado local)
        start_drive_sync()
        initial = build_initial(app)

    app.run(initial)


if __name__ == "__main__":
    main()
