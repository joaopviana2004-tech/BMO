# BMO OS

Shell retrô estilo **BMO** (Adventure Time) pra Raspberry Pi 4B com tela touch 5"
(800x480). É a interface de um console pessoal que vai morar dentro de uma case
física do BMO — eventualmente com botões físicos (D-pad + A/B/MENU via GPIO),
RetroArch pra rodar emulador, e personalidade própria (rostinhos, reações,
animações idle).

Tudo em **Python + pygame-ce**, renderizando numa surface lógica de **400x240**
escalada **2x** com nearest-neighbor pra preservar o look de pixel art.

## O que tem hoje

**Telas ambient (lock screen)**, escolhíveis em SLEEP ou SETTINGS:
- **CLOCK** — relógio P&B CRT: HH:MM 72px com dois-pontos piscando, segundos
  pequenos, clima top-esq (TEMP / UMID), data bot-dir, brackets nos 4 cantos e
  scanlines sutis. Tap → home.
- **BMO FACE** — pet virtual procedural: olhos pretos, boquinha, expressões
  (idle / blink / look / smile / think / speak), reage ao toque (HAPPY /
  SURPRISED / WINK / SPEAK). Opcionalmente os olhos seguem **seu rosto de
  verdade** via câmera (config `BMO TE VE`).
- **PONG** — bot vs bot rodando no fundo, scores discretos nos cantos.
- **INVADERS** — nave do BMO vagueia sozinha pelo espaço, caça inimigos
  esporádicos que aparecem do topo. Starfield com parallax 3 camadas.
- **VARIADO** — cicla aleatoriamente entre os 4 acima a cada 10-30s.

Mini-relógio HH:MM no topo das telas ambient (exceto clock que já tem o grandão).

**Botão de mic virtual** (🎙️ no canto) nas telas de **descanso, foco, kanban
e agenda**: **segure** pra gravar e **solte** pra mandar pro BMO (igual ao
push-to-talk físico), sem precisar do botão GPIO.

**Home + ações** (carrossel P&B, auto-volta pro ambient após N segundos):
- **SLEEP** — escolhe ambient mode com previews ao vivo dos 5 tiles
- **GAMES** — grid estilo home de celular com:
  - **Space Invaders** — touch arrasta nave, auto-fire, 4 tipos de inimigos
    pixel-art coloridos, starfield, vidas, score, game over
  - **Pong** — player (touch arrasta paddle Y) vs bot. Primeiro a 7 pontos
- **TASKS** — kanban Todoist 3 colunas (TO-DO / DOING / DONE):
  - Toque + arrasta cards entre colunas
  - Botão SYNC força refresh
  - Scroll por coluna se tiver muita tarefa
  - Fonte Consolas 11pt (não-pixel) pra caber mais texto
- **AGENDA** — próximos compromissos do Google Calendar (iCal/OAuth read-only).
  Aviso automático (AlertScreen) quando um evento está chegando.
- **FOCO** — timer pomodoro por tarefa (puxa as tarefas "Doing" do Todoist);
  acumula o tempo focado por tarefa. Estado preservado ao sair/voltar.
- **SISTEMA** — telemetria da Pi (CPU, temperatura, memória); no PC mostra "--".
- **PHOTO** — câmera fullscreen:
  - Preview HD 800x480 com hflip (modo selfie)
  - Botão SHOOT vermelho (estilo app de câmera)
  - Boxes brancos sobre rostos detectados
  - Toggle DEBUG (i): mostra FPS, resolução, status do detector
  - Botão GALERIA: abre grid de thumbnails das fotos tiradas
- **GALERIA** — grid 3×2 de thumbs + viewer fullscreen (tap esq/dir = nav)
- **TESTE (IA)** — diagnóstico de IA: medidor de nível do mic, status do
  Whisper/STT e do wake word, estado do botão físico de fala, preview da câmera,
  push-to-talk pra testar transcrição + conversa com o BMO (LLM), e botão
  **VER (VISÃO)** que manda a imagem da câmera pro modelo multimodal descrever
- **SETTINGS** — menu por categorias (SOM / TELA / SISTEMA / IA), cada uma com
  cyclers (gira com ←/→ ou tap) e ações:
  - **SOM:** Volume (efeitos)
  - **TELA:** Brilho (20-100% via dimming); Tema (auto/escuro/claro — *auto* =
    claro 6h-18h)
  - **SISTEMA:** Standby (5-120s); Ambient (qual lock screen); Aviso evento
    (antecedência do alerta da AGENDA); Atualizar (`git reset --hard origin/main`
    + restart); Desligar (confirmação dupla em 3s)
  - **IA:** Provedor + Modelo de **chat** (OpenRouter/NVIDIA/Grok); Provedor +
    Modelo de **visão**; BMO me ouve (wake word); **Botão de fala** (liga/desliga
    o mic virtual nas telas); Microfone; Voz BMO (volume do TTS); BMO te vê (face
    tracking); **Gerar vozes** (gera o cache de fala faltante)

**Status bar** (canto superior direito de todas as telas CRT): sol/lua (auto
pelo horário), nível de sinal (mock 4/4), bateria (mock 100%). Ícone de
**refresh** piscando à esquerda quando tem código novo no git pra puxar.

**Tema claro** estilo Game Boy DMG (creme + tinta escura) substitui o preto+branco
nas telas CRT, ativável via `Tema: CLARO` ou automático.

**Zona morta** de 14px nas bordas pra não esbarrar no frame físico da case do
BMO — todas as telas CRT respeitam isso, content e corners empurrados pra dentro.

**Serviços em thread:**
- **Weather** — [Open-Meteo](https://open-meteo.com) (grátis, sem API key).
  Refetch 10 min, default João Pessoa/PB. Mantém último snapshot bom em caso
  de falha de rede (não fica piscando `--`).
- **Todoist** — API v1 (`https://api.todoist.com/api/v1/`), refetch 60s + push
  on demand. Move otimista via `POST /tasks/{id}/move`.
- **Git updates** — `git fetch` a cada 5 min, detecta tanto commits novos no
  origin quanto drift local (`startup_sha != HEAD`).
- **Camera** — picamera2 lazy: só liga quando `PhotoScreen` ou `BMOFaceScreen+BMO TE VE`
  pedem. Stop automático no release pra economizar calor/bateria. Face detect via
  OpenCV Haar cascade roda apenas quando alguém pede `get_faces()` recentemente.
- **Voice** — push-to-talk + (opcional) wake word. Captura do mic via
  sounddevice, transcrição (STT) por Whisper local (`pywhispercpp`) ou API
  compatível OpenAI (Groq por padrão). **Acesso exclusivo ao mic** (ALSA só
  permite 1 captura por vez): monitor, wake e gravação se revezam, com retry ao
  abrir o stream.
- **Chat (LLM)** — o BMO responde via **OpenRouter, NVIDIA NIM ou Grok** (escolha
  em SETTINGS → IA). Pede um JSON `{"msg", "screen", "task"}` e, além de responder,
  pode **abrir uma tela** ou **criar uma tarefa** no Todoist (ver seção "IA").
- **Visão** — `chat.ask_vision`: manda a imagem da câmera (base64) pro modelo
  multimodal escolhido descrever. Botão **VER (VISÃO)** na tela TESTE.
- **TTS (voz do BMO)** — Edge TTS (voz Francisca pt-BR) fala as respostas, com
  **cache de frases fixas** pra latência ~zero (ver seção "IA").
- **Google Calendar** — `gcalendar.py`: lê eventos via iCal secreta (agenda
  privada) ou OAuth (Workspace). `notifications.py` dispara o alerta de evento.
- **SysInfo** — telemetria de hardware (CPU/temp/memória) pra tela SISTEMA.

## Estrutura

```
bmo_os/
  main.py              # entry point + wiring + singletons de serviços
  core/
    app.py             # loop principal + scaler 2x + dimming brightness
    screen_manager.py  # pilha de telas (push/pop com enter/exit)
    input.py           # touch+teclado hoje, GPIO depois (mesma Action API)
    widgets.py         # pygame.Color mutável pra tema, corners, scanlines, SAFE_INSET
    theme.py           # fontes pixel/consolas
    theme_state.py     # apply_theme + status bar + draw_mini_clock + sun/moon
    config.py          # defaults + load .env + persistência bmo_config.json
  screens/
    clock.py           # ambient: relógio P&B CRT
    bmo_face.py        # ambient: pet procedural (camera-aware)
    pong.py            # PongScreen (jogo) + PongAmbientScreen (bot vs bot)
    space_invaders.py  # SpaceInvadersScreen (jogo) + SpaceInvadersAmbientScreen
    shuffler.py        # ShufflingAmbientScreen (cicla as 4 ambient)
    home.py            # carrossel SLEEP/GAMES/TASKS/AGENDA/FOCO/PHOTO/SISTEMA/TESTE/SETTINGS
    sleep.py           # tiles dos 5 ambient modes
    games.py           # grid estilo celular (Space Invaders + Pong)
    tasks.py           # kanban Todoist 3 colunas (touch drag)
    agenda.py          # próximos eventos do Google Calendar
    pomodoro.py        # timer de foco por tarefa (FOCO)
    photo.py           # camera fullscreen + debug overlay + galeria btn
    gallery.py         # grid 3x2 de thumbs + viewer
    sysinfo.py         # tela SISTEMA: CPU/temperatura/memória da Pi
    alert.py           # AlertScreen: aviso de evento próximo (por cima de tudo)
    aitest.py          # TESTE IA: mic/STT/câmera/botão + push-to-talk + chat + VISÃO
    mic_button.py      # MicButton: botão de mic virtual (overlay global, segura p/ gravar)
    settings.py        # menu por categorias (SOM/TELA/SISTEMA/IA) + atualizar/desligar
    suspended.py       # tela SUSPENSO: display off + FPS baixo, toque acorda
    placeholder.py     # stub genérico (legado)
  services/
    weather.py         # Open-Meteo, thread + lock + último bom em cache
    todoist.py         # API v1, thread + trigger_refresh + create
    gcalendar.py       # Google Calendar (iCal secreta ou OAuth), read-only
    notifications.py   # dispara o alerta de evento próximo (AlertScreen)
    sysinfo.py         # telemetria de hardware (CPU/temp/memória)
    git_updates.py     # fetch + drift detection
    camera.py          # picamera2 + cv2, refcount lazy (acquire/release) + capture_jpeg
    audio.py           # sons 8-bit gerados em runtime (numpy)
    voice.py           # mic + STT (Whisper local / API Groq) + push-to-talk + wake
    chat.py            # LLM (OpenRouter/NVIDIA/Grok) -> JSON {msg,screen,task} + visão
    tts.py             # voz do BMO: Edge TTS (Francisca pt-BR) > Piper > eSpeak + cache
    gpio_button.py     # botão físico de push-to-talk (gpiozero)
  assets/
    fonts/             # PressStart2P.ttf (ver "Fontes pixel" abaixo)
    voice_cache/       # MP3 das frases fixas do TTS (gerados em runtime, gitignored)
  references/          # .webp/.png das fotos do BMO físico e refs de face
scripts/               # deploy no Pi (ver "Áudio Bluetooth" abaixo)
  bmo-bt-setup.sh        # instalador 1-comando do alto-falante Bluetooth
  bmo-bt-speaker.sh      # conecta no speaker + define sink padrão (roda no boot)
  bmo-bt-speaker.service # serviço systemd --user que roda o script acima
  bluetooth.md           # passo a passo do Bluetooth
```

## Setup (Windows, pra desenvolver)

```powershell
cd "D:\Projetos Pessoais\BMO\BMO"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m bmo_os.main
```

Sem câmera, picamera2 e opencv. PhotoScreen mostra "CAMERA OFFLINE" mas o resto
tudo funciona normal.

## Setup (Raspberry Pi 4B)

O Pi roda **Raspberry Pi OS (Bookworm)** com o desktop **Wayland (labwc)** padrão.
O BMO sobe como uma aplicação fullscreen **dentro da sessão do desktop** — não é
kiosk no console/framebuffer. Usa o **Python do sistema** (`/usr/bin/python3`), sem
venv; pygame e as libs da câmera vêm do `apt`.

```bash
sudo apt update
sudo apt install python3-pygame python3-numpy \
                 python3-picamera2 python3-opencv
git clone <repo> ~/BMO
cd ~/BMO
python3 -m bmo_os.main --fullscreen   # teste manual dentro do desktop
```

**Shutdown sem senha** (pro botão DESLIGAR do Settings funcionar):
```bash
sudo visudo
# adicionar (troca `gravae` pelo seu user):
gravae ALL=(ALL) NOPASSWD: /sbin/shutdown
```

### Autostart com o desktop

O BMO inicia junto com o desktop via um arquivo `.desktop` em `~/.config/autostart/`:

```ini
# ~/.config/autostart/bmo.desktop
[Desktop Entry]
Type=Application
Name=BMO OS
Comment=Inicia o BMO automaticamente com o desktop
Exec=/usr/bin/python3 /home/gravae/BMO/bmo_os/main.py --fullscreen
Terminal=false
```

> O `Exec` é um caminho **absoluto** — se mover/renomear a pasta do repo, atualize
> essa linha, senão o autostart falha calado no boot.

O botão **Atualizar** do Settings (ou o comando de voz *"se atualiza"*) faz
`git reset --hard origin/main` e reinicia o processo in-place via `os.execv`
(não depende de systemd). Antes do `execv` o BMO **libera o hardware** (câmera,
GPIO, mic) — libs em C deixam file descriptors abertos que sobreviveriam ao
`execv` e travariam o processo novo.

### Áudio Bluetooth (opcional)

Pra conectar num alto-falante Bluetooth automaticamente no boot, use o instalador
de um comando só:

```bash
bash ~/BMO/scripts/bmo-bt-setup.sh             # sem MAC: escaneia e lista os aparelhos
bash ~/BMO/scripts/bmo-bt-setup.sh AA:BB:CC:DD:EE:FF   # com o MAC: faz tudo
```

Detalhes em [`scripts/bluetooth.md`](scripts/bluetooth.md).

## Configuração local (.env + bmo_config.json)

Duas fontes de config, ambas **gitignored**:

**`.env`** na raiz (env vars carregadas automaticamente no boot):
```
TODOIST_TOKEN=xxxxxxxx                  # token da REST API v1 do Todoist
# TODOIST_PROJECT=BMO                   # nome do projeto kanban (default BMO)
# WEATHER_LAT=-7.1195                   # default João Pessoa/PB
# WEATHER_LON=-34.8450
# WEATHER_TIMEZONE=America/Fortaleza
```

Veja `.env.example` (commitado) pra docs completas. Env vars já no shell têm
precedência sobre o `.env`.

**`bmo_config.json`** (preferências persistidas pelo cycler do SETTINGS, criado/
escrito sozinho — você não precisa editar à mão):
- `idle_timeout_s`, `ambient_mode`, `theme`, `brightness`, `volume`
- `event_warning_min` — antecedência do alerta da AGENDA
- IA: `llm_provider` + `{openrouter,nvidia,grok}_model`; `vision_provider` +
  `*_vision_model`; `voice_enabled`, `mic_device`, `tts_volume`, `camera_face_tracking`
- `todoist_token`, `todoist_project` — fallback se não tiver no env

## Todoist (kanban)

Pra a tela TASKS funcionar:

1. **No Todoist**: crie um projeto chamado **`BMO`** (ou outro nome — define em
   `TODOIST_PROJECT`) com 3 seções nomeadas exatamente **`To-Do`**, **`Doing`**,
   **`Done`** (case-insensitive na leitura).
2. Pegue o token em **Todoist → Settings → Integrations → Developer**.
3. Bota no `.env`: `TODOIST_TOKEN=xxxx`.

Cria tarefas no Todoist pelo PC/celular como sempre, e arrasta entre colunas
pelo touch do BMO. SYNC força refresh imediato. O BMO também cria tarefas por
voz/IA (ver seção abaixo).

## IA — conversa com o BMO (LLM + push-to-talk)

O BMO ouve um comando de voz, transcreve, manda pro LLM e responde — e a
resposta pode **abrir uma tela** ou **criar uma tarefa**. Funciona em **qualquer
tela**: um rodapé global mostra `GRAVANDO` → `PENSANDO` → a resposta do BMO.

**Fluxo:** segura o botão físico (push-to-talk) → fala → solta → o áudio é
transcrito (STT) → o texto vai pro LLM → o BMO responde e age.

- **Botão físico (GPIO):** segura = grava, solta = transcreve. Pino padrão
  `GPIO17` (muda com `PTT_GPIO`). Botão entre o pino e o GND (pull-up interno,
  sem resistor). No PC, use o botão **TOCAR P/ FALAR** da tela TESTE.
- **STT (fala → texto):** Whisper local (`pywhispercpp`) **ou** uma API
  compatível com OpenAI (Groq por padrão — sem inferência na Pi, sem calor).
  Com `STT_API_KEY` setada, usa a API; senão tenta o Whisper local.
- **LLM (resposta):** OpenRouter, NVIDIA NIM ou Grok (xAI) — todos compatíveis
  com OpenAI. O provedor e o modelo são escolhidos em **SETTINGS → IA** (troca
  rápida por cycler). O BMO responde sempre com um JSON `{"msg", "screen", "task"}`.
- **Visão:** a tela TESTE tem um botão **VER (VISÃO)** que manda a imagem da
  câmera pro modelo descrever. O provedor/modelo de visão são **próprios**
  (separados do chat, em SETTINGS → IA), porque só modelos multimodais enxergam.

**Telas/ações que o BMO pode disparar** (campo `screen`):
`agenda`, `tarefas`, `foco`, `sistema`, `foto`, `jogos`, `pong`, `invaders`,
`configuracoes`, `relogio`, `home`, `atualizar` (ou `none` pra só conversar).
O campo `task` (texto) cria uma tarefa no Todoist. Ex.: *"abre o pong"*,
*"cria uma tarefa: comprar pão"*, *"se atualiza"*, *"que horas são?"*.

> **Voz falada (TTS) — ATIVA.** O BMO fala as respostas (conversa e descrição de
> visão) com a voz **Francisca (pt-BR)** via **Edge TTS** (Microsoft, grátis, sem
> chave — precisa de internet). Incorporado do módulo de laboratório `bmo_voz.py`
> em `services/tts.py` (backend `edge`, ajustes do lab: +13% velocidade, +18Hz
> tom, +24% volume). Setup: `pip install edge-tts` (a voz toca pelo próprio mixer
> do pygame, junto dos efeitos — sem player externo; `mpg123` fica só de fallback).
> Volume em SETTINGS → IA ("Voz BMO"); `tts_volume=0` deixa mudo. Backend padrão
> = `edge` (sem ele, voz fica indisponível em vez de cair numa voz masculina do
> Piper); pra Piper/eSpeak use `BMO_TTS_BACKEND`.
>
> **Cache de frases (latência ~zero):** saudações, "aqui está [tela]" de cada
> tela e falinhas do BMO são **pré-geradas em MP3** (em background no 1º boot,
> em `bmo_os/assets/voice_cache/`, gitignored) e tocam **direto do disco** — sem
> rede. No boot o BMO dá um "bom dia/boa tarde/boa noite". Quando você **pede pra
> IA abrir uma tela** ("abre o relógio"), ele **corta a resposta verbosa do LLM**
> e fala a frase de cache da tela ("Aqui está o relógio!") — isso só acontece no
> pedido via IA, não ao abrir manualmente. Ao criar uma tarefa, fala "Tarefa
> criada com sucesso!". Só as respostas livres do LLM passam pela rede (~1-3s).
> O cache se completa sozinho a cada boot (e logo após "Atualizar"); SETTINGS →
> IA → **Gerar vozes** força a verificação/geração das que faltarem, com
> progresso na tela.
>
> *Pronúncia:* na fala, "BMO" vira "bimu" (a voz neural soletra/buga "BMO") — só
> no áudio; o texto na tela continua "BMO".

**Setup (`.env`):** ponha só a chave do(s) provedor(es) que for usar — o
provedor e o modelo (chat **e** visão) saem do menu SETTINGS → IA.
```
OPENROUTER_API_KEY=sk-or-xxxx           # OpenRouter (openrouter.ai/keys)
NVIDIA_API_KEY=nvapi-xxxx               # NVIDIA NIM (build.nvidia.com)
XAI_API_KEY=xai-xxxx                    # Grok / xAI (console.x.ai)
# *_MODEL / *_VISION_MODEL               # (opcional) semeia o default; depois o menu manda
# STT_API_KEY=gsk_xxxx                   # API de transcrição (Groq); sem ela usa Whisper local
# STT_API_MODEL=whisper-large-v3-turbo
# PTT_GPIO=17                            # pino do botão de push-to-talk
```

Sem a chave do provedor ativo o chat/visão fica indisponível (a tela TESTE
mostra o erro). Sem mic/STT, o push-to-talk degrada e mostra "indisponivel".

## Câmera (AI Camera / IMX500)

A tela PHOTO e o modo "BMO te vê" usam a câmera oficial Raspberry Pi AI Camera
(Sony IMX500) via `picamera2`. **Lazy**: só liga quando alguém precisa, desliga
no release. Padrão é **OFF** pra não esquentar.

Fotos salvam em `<repo>/photos/` (gitignored).

Sem câmera ou sem `picamera2` instalado, PhotoScreen mostra "CAMERA OFFLINE" e
o BMO face cai pro modo touch.

**Face detection** atual usa OpenCV Haar cascade (CPU, ~3 fps de detecção). Pra
upgrade futuro com modelo on-sensor do IMX500, trocar dentro de `camera.py` sem
mexer na API pública.

## Clima (Open-Meteo)

Default já vem configurado pra **João Pessoa/PB**. Pra trocar de cidade,
defina as env vars no `.env` ou no shell:

```bash
WEATHER_LAT=-23.5505
WEATHER_LON=-46.6333
WEATHER_TIMEZONE=America/Sao_Paulo
```

Sem internet: TEMP/UMID aparecem como `--C / --%` na primeira vez, depois
mantêm o último valor bom (não fica piscando).

## Atualizações via git

A tela do clock mostra um **ícone de refresh piscando** no canto sup-direito
quando o código no disco diverge do processo rodando — seja porque alguém
pushou de outra máquina (e o fetch pegou commits novos), seja porque o auto-commit
local advançou o HEAD enquanto o BMO ainda roda código antigo.

Pra atualizar: SETTINGS → ATUALIZAR (faz `git reset --hard origin/main` +
restart), ou peça por voz: *"BMO, se atualiza"*.

## Fontes pixel

Pro look 100% BMO, baixe uma fonte pixel e ponha em `bmo_os/assets/fonts/`:

- **Press Start 2P** — <https://fonts.google.com/specimen/Press+Start+2P>
  (salve como `PressStart2P.ttf`)
- **Departure Mono** — <https://departuremono.com/>
  (salve como `DepartureMono.ttf`)

Sem fonte custom o sistema usa Consolas/Courier como fallback (funciona, mas
perde a vibe de fliperama). Tasks e overlays usam Consolas propositalmente
(legibilidade > vibe).

## Controles

| Ação      | Touchscreen     | Teclado (debug) | GPIO (V2)         |
|-----------|-----------------|-----------------|-------------------|
| Navegar   | Toque nas setas | Setas           | D-pad             |
| Confirmar | Toque no item   | Enter / Espaço  | Botão vermelho A  |
| Voltar    | Botão HOME      | Esc / Backspace | Botão verde B     |
| Menu      | Tap no relógio  | Tab             | Triângulo azul    |
| Sair      | -               | F4 / F          | -                 |

Cada jogo/tela tem seus próprios atalhos touch (botão SHOOT no invaders, drag
do paddle no pong, drag do card no kanban, etc.) — sempre com HOME button no
canto superior esquerdo pra sair.

## Roadmap

- [x] **V1** — relógio + home + sleep (3 telas base)
- [x] **V1.1** — clima sem API key, clock P&B, home auto-return, settings com update
- [x] **V1.2** — settings completo: brilho, tema (claro/escuro/auto), shutdown
- [x] **V1.3** — BMO Face (pet procedural com expressões)
- [x] **V1.4** — Tasks/Kanban Todoist com touch drag
- [x] **V1.5** — Pong + Space Invaders (jogos e telas idle bot vs bot)
- [x] **V1.6** — Photo + Gallery (câmera fullscreen + thumbnails)
- [x] **V1.7** — Face tracking via câmera (BMO te vê)
- [x] **V1.8** — Status bar (sol/lua + sinal + bateria mock) + alerta de update
- [x] **V1.9** — Shuffle ambient (cicla telas idle aleatoriamente)
- [x] **V2.0** — IA: push-to-talk (GPIO) + STT (Whisper/Groq) + chat LLM
  (OpenRouter) que abre telas e cria tarefas; tela TESTE IA; cleanup de hardware
  no restart
- [ ] **V2.1** — input GPIO completo (D-pad + A/B/MENU) quando os botões chegarem
- [x] **V2.2** — TTS (voz falada do BMO): Edge TTS / voz Francisca pt-BR
  (incorporado do lab `bmo_voz.py`), fala conversa + descrição de visão
- [ ] **V2.3** — RetroArch launcher (subprocess) — Games vira lista de ROMs
- [ ] **V2.4** — gestos de mão (MediaPipe Hands) pra controle sem toque
- [ ] **V3** — IMX500 native inference (objeto/pose direto no chip da câmera)
- [ ] **V3** — sensores reais (DHT22/BME280 via I2C) em vez/além do clima online
- [ ] **V3** — wake word offline ("BMO me ouve" sem push-to-talk)
