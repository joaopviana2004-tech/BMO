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
  (idle / blink / look / smile / think / speak / **dormindo com Zzz**), reage ao
  toque (HAPPY / SURPRISED / WINK / SPEAK). **Carinho:** cafuné (vários toques
  seguidos = olhos derretidos), long-press (segura parado = "ãh?"), cutucar o
  olho (fica emburrado). As expressões e o ritmo mudam com o **humor** do pet
  (ver seção "Pet virtual"). Opcionalmente os olhos seguem **seu rosto de
  verdade** via câmera (config `BMO TE VE`).
- **PONG** — bot vs bot rodando no fundo, scores discretos nos cantos.
- **INVADERS** — nave do BMO vagueia sozinha pelo espaço, caça inimigos
  esporádicos que aparecem do topo. Starfield com parallax 3 camadas.
- **CÉREBRO** — o grafo do Segundo Cérebro "respirando": minimapa força-dirigido
  das notas do Obsidian (ver seção "Segundo Cérebro").
- **DEV HUB** — painel de programação em modo descanso: stats grandes, gráfico
  de commits 7d e feed rolando devagar (ver seção "Dev Hub").
- **VARIADO** — cicla aleatoriamente entre as ambient acima a cada 10-30s.

Mini-relógio HH:MM no topo das telas ambient (exceto clock que já tem o grandão).

**Botão de mic virtual** (🎙️ no canto) nas telas de **descanso, foco, kanban
e agenda**: **segure** pra gravar e **solte** pra mandar pro BMO (igual ao
push-to-talk físico), sem precisar do botão GPIO.

**Home — hub de categorias** (**IA · REPOUSO · ESTUDOS · AJUSTES**; arrasta pro
lado pra trocar de categoria, cada uma com sua grade de apps; auto-volta pro
ambient após N segundos):
- **CÉREBRO** *(IA)* — abre o grafo do Segundo Cérebro (ver seção própria)
- **FLAPPY IA** *(IA)* — treino de Flappy por neuroevolução em tempo real, com a
  rede neural do melhor pássaro visível (ver seção "Flappy IA")
- **TESTE (IA)** — diagnóstico de IA (mic/STT/câmera/chat/visão; detalhado abaixo)
- **GRAVAR** *(ESTUDOS)* — gravador offline-first "Sync & Destroy" (ver seção própria)
- **DEV** *(ESTUDOS)* — Dev Hub: dashboard de programação (ver seção "Dev Hub")
- **SLEEP** — escolhe ambient mode com previews ao vivo dos tiles
- **GAMES** — grid estilo home de celular com:
  - **Space Invaders** — touch arrasta nave, auto-fire, 4 tipos de inimigos
    pixel-art coloridos, starfield, vidas, score, game over
  - **Pong** — player (touch arrasta paddle Y) vs bot. Primeiro a 7 pontos
  - **Flappy** — passarinho minimalista: toque (ou A) bate asa contra a
    gravidade pra passar pelos canos; +1 por cano, bateu = fim de jogo. **Fica
    mais difícil** conforme avança: acelera e o vão afunila (ver "Flappy IA")
  - **Snake** — cobrinha em grade: vira por setas/botões **ou por toque**
    (na direção do toque relativo à cabeça); come, cresce e acelera
  - **Haxball** — futebol de botão top-down: arraste seu disco (vermelho) e
    encoste na bola pelo lado de ataque pra dar um **chute** (impulso) no gol da
    direita. Adversário azul = a **IA que você treinou** (tela HAXBALL IA) ou um
    jogador heurístico forte. Primeiro a 5. Física compartilhada com o treino.
- **TASKS** — kanban Todoist 3 colunas (TO-DO / DOING / DONE):
  - Toque + arrasta cards entre colunas
  - Botão SYNC força refresh
  - Scroll por coluna se tiver muita tarefa
  - Fonte Consolas 11pt (não-pixel) pra caber mais texto
- **AGENDA** — próximos compromissos do Google Calendar (iCal/OAuth read-only).
  Aviso automático (AlertScreen) quando um evento está chegando.
- **FOCO** — timer pomodoro por tarefa (puxa as tarefas "Doing" do Todoist);
  acumula o tempo focado por tarefa. Estado preservado ao sair/voltar.
- **SISTEMA** — telemetria da Pi (CPU, GPU, temperatura, memória, tensão; no PC
  mostra "--") + **controle dos coolers** (ver seção "Refrigeração"): botão liga/
  desliga com ícone girando quando ativo.
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
- **SETTINGS** — menu por categorias (SOM / TELA / SISTEMA / IA / CONTA), cada
  uma com cyclers (gira com ←/→ ou tap) e ações:
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
  - **CONTA:** conta logada; **Conectar conta** (abre o login por QR sem wipe);
    **Trocar usuário** (Wipe & Load — ver "Multiusuário e login pelo Drive")
- O grid de **AJUSTES** ainda traz **DESLIGAR** e **ATUALIZAR** como tiles diretos
  (com tela de confirmação), além de SETTINGS e SISTEMA.

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
  em SETTINGS → IA). Pede um JSON `{"msg", "screen", "task", "facts", "name"}` e,
  além de responder, pode **abrir uma tela**, **criar uma tarefa** no Todoist e
  **memorizar** fatos/seu nome. Mantém um **histórico curto** da conversa e injeta
  o **humor** do pet pra colorir o tom (ver seções "IA" e "Pet virtual").
- **Visão** — `chat.ask_vision`: manda a imagem da câmera (base64) pro modelo
  multimodal escolhido descrever. Botão **VER (VISÃO)** na tela TESTE.
- **TTS (voz do BMO)** — Edge TTS (voz Francisca pt-BR) fala as respostas, com
  **cache de frases fixas** pra latência ~zero. A voz das respostas livres ganha
  **emoção conforme o humor** do pet (tom/velocidade) — ver seção "IA".
- **Pet (humor + memória + cérebro)** — o que faz o BMO ser um *bicho de
  estimação* e não só uma interface. **Autossuficiente: não depende de câmera nem
  de mic.** Ver seção "Pet virtual".
  - `pet_state.py` — humor (feliz/animado/sonolento/carente/entediado/amoroso),
    energia (curva do horário) e **afeto + streak** de convívio, derivados de
    hora, ociosidade e toques. Persiste em `bmo_pet.json`.
  - `pet_memory.py` — lembra **nome e fatos** do usuário (`bmo_memory.json`).
  - `pet_brain.py` — **proatividade**: o BMO puxa conversa sozinho (com
    parcimônia/cooldowns) usando humor, agenda, tarefas e temperatura da Pi.
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
    config.py          # defaults + load .env + persistência bmo_config.json (por perfil)
    session.py         # multiusuário: perfis locais + Wipe & Load (login/logout)
  screens/
    clock.py           # ambient: relógio P&B CRT
    bmo_face.py        # ambient: pet procedural (humor + carinho + camera-aware)
    pong.py            # PongScreen (jogo) + PongAmbientScreen (bot vs bot)
    space_invaders.py  # SpaceInvadersScreen (jogo) + SpaceInvadersAmbientScreen
    flappy.py          # FlappyScreen (passarinho: toque/A) + modo versus contra a IA
    flappy_train.py    # FlappyTrainScreen: treino por neuroevolução + viz da rede
    haxball.py         # HaxballScreen: futebol de botão (você x IA/heurístico)
    haxball_train.py   # HaxballTrainScreen: co-evolução (grid 3x3) + rede + stats
    snake.py           # SnakeScreen (cobrinha: setas/botões ou toque)
    shuffler.py        # ShufflingAmbientScreen (cicla as ambient)
    home.py            # hub de categorias (IA/REPOUSO/ESTUDOS/AJUSTES) em grade
    sleep.py           # tiles dos ambient modes
    games.py           # grid estilo celular (Invaders + Pong + Flappy + Snake)
    tasks.py           # kanban Todoist 3 colunas (touch drag)
    agenda.py          # próximos eventos do Google Calendar
    pomodoro.py        # timer de foco por tarefa (FOCO)
    photo.py           # camera fullscreen + debug overlay + galeria btn
    gallery.py         # grid 3x2 de thumbs + viewer
    brain.py           # tela CEREBRO: grafo do Segundo Cérebro (força-dirigido)
    devhub.py          # tela DEV: dashboard GitHub (commits/CI/logs) menu + ambient
    recorder.py        # tela GRAVAR: gravador offline-first (Sync & Destroy)
    login.py           # tela LOGIN: QR + device flow do Google (multiusuário)
    sysinfo.py         # tela SISTEMA: telemetria da Pi + controle dos coolers
    alert.py           # AlertScreen: aviso de evento próximo (por cima de tudo)
    aitest.py          # TESTE IA: mic/STT/câmera/botão + push-to-talk + chat + VISÃO
    mic_button.py      # MicButton: botão de mic virtual (overlay global, segura p/ gravar)
    settings.py        # menu por categorias (SOM/TELA/SISTEMA/IA/CONTA) + atualizar/desligar
    confirm.py         # ConfirmScreen: confirmação sim/não (desligar/atualizar do grid)
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
    chat.py            # LLM (OpenRouter/NVIDIA/Grok) -> JSON {msg,screen,task,facts,name} + visão
    tts.py             # voz do BMO: Edge TTS (Francisca pt-BR) > Piper > eSpeak + cache + humor
    pet_state.py       # humor/energia/afeto/streak do pet (bmo_pet.json) — sem hardware
    pet_memory.py      # memória do usuário: nome + fatos (bmo_memory.json)
    pet_brain.py       # proatividade: BMO puxa conversa sozinho (cooldowns)
    recorder.py        # gravador offline-first (WAV) p/ o Sync & Destroy
    knowledge.py       # Segundo Cérebro: grafo das notas .md + tool de escrita (RAG)
    drive_sync.py      # espelho do perfil no Drive (prefs + áudios + conhecimento)
    google_auth.py     # OAuth Google (device flow + refresh) por perfil
    pairing.py         # link na rede local: pareamento PC + chat remoto + POST /dev
    dev_hub.py         # estado do Dev Hub (commits/CI/logs); github_dev alimenta
    github_dev.py      # GitHub API -> Dev Hub (commits, CI, stats) em thread
    flappy_ai.py       # neuroevolução do Flappy: rede + GA + salvar/carregar (jogo+treino)
    haxball_ai.py      # haxball: física + rede(numpy) + GA + imitação + heurístico
    cooler.py          # controle dos 2 coolers via GPIO (auto >60°C)
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
- `pet_proactive` — BMO puxa conversa sozinho (ver "Pet virtual")
- `todoist_token`, `todoist_project` — fallback se não tiver no env

O **pet** mantém ainda dois arquivos próprios (criados sozinhos, gitignored):
`bmo_pet.json` (humor/afeto/streak) e `bmo_memory.json` (nome + fatos do usuário).

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
`flappy`, `snake`, `configuracoes`, `relogio`, `home`, `atualizar` (ou `none` pra
só conversar). O campo `task` (texto) cria uma tarefa no Todoist; `facts`/`name`
alimentam a memória do pet. Ex.: *"abre o snake"*, *"bora voar"*,
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

## Multiusuário e login pelo Drive

Sem sessão ativa o BMO cai na tela **LOGIN**: um **QR Code** (Google *device
flow*) + o código pra digitar à mão. Quem loga vira um **perfil** em
`profiles/<sub>/` (identidade, tokens, `bmo_config.json` próprio). "USAR SEM
CONTA" entra como **convidado** (local, sem sync).

- **Preferências no Drive** (`drive_sync.py`): tema/volume/brilho de cada perfil
  sobem (debounce ~10s a cada ajuste) e descem no boot — ligar em outro aparelho
  já vem com as suas preferências.
- **Wipe & Load:** "Trocar usuário" (SETTINGS → CONTA) faz o backup final no
  Drive, **apaga a pasta do perfil** e reinicia — nenhum cache do usuário
  anterior sobrevive. O processo novo boota na tela de LOGIN.
- **Pareamento pelo PC** (`scripts/bimo_drive_login.py <ip>`): o QR só dá escopo
  `drive.file`; pra o Drive **completo** (enxergar a vault do Obsidian sincada
  pelo "Google Drive para Desktop"), pareie pelo PC pela rede local — o
  `PairingServer` recebe os tokens e religa o sync.

Sem `GOOGLE_CLIENT_ID/SECRET` no `.env`, o login fica indisponível e o BMO roda
em modo local (convidado/legado) — tudo funciona, só não sincroniza.

## Segundo Cérebro (grafo de conhecimento)

A tela **CÉREBRO** é o "Oráculo Visual": um grafo força-dirigido (estilo
Obsidian/matrix) das suas notas `.md`, que **respira** e se organiza sozinho.

- **nó** = uma nota; **aresta** = um `[[wikilink]]`; **fantasma** = link pra nota
  que ainda não existe (círculo vazado, apagado).
- Sem botões: **tap** seleciona, **arrasta** um nó move (a física segue),
  arrastar o vazio dá **pan**, **pinça** dá zoom, **2 toques** num nó abrem o
  **split** (grafo à esquerda, a nota inteira à direita).
- Fonte: as notas são espelhadas do **Drive** (`Bimo/Conhecimento` →
  `knowledge/` do perfil, bidirecional). É a base do **RAG local** — o chat usa
  essas notas como contexto e o agente pode **criar/editar notas** (tool
  `notes_write`), que sobem pro Drive e o PC puxa pro Obsidian.

## Dev Hub (dashboard de programação)

A tela **DEV** acompanha seus projetos sem sair do BMO: **commits, CI e logs**
puxados da **GitHub API** (`GITHUB_USER`/`GITHUB_TOKEN` no `.env`) + um *bridge*
do PC (`POST /dev`). Tem **modo menu** (abas RESUMO / GIT / CI / LOG) e **modo
ambient** (stats grandes, gráfico de commits 7d, feed rolando devagar) — vibe
terminal ciano. Funciona como lock screen escolhível em SLEEP/SETTINGS.

## Gravador (Sync & Destroy)

A tela **GRAVAR** captura áudio **offline-first** (aulas/reuniões/insights):
botão REC/STOP, timer e VU meter. Os `.wav` ficam no disco e **sobem sozinhos**
quando a rede voltar; o Drive confere o `md5` e aí o **arquivo local é apagado**
(memória do BMO sempre livre). A pasta é **do perfil** (some no wipe do logout).

## Flappy IA (neuroevolução)

A tela **FLAPPY IA** (categoria IA) treina um Flappy Bird por **algoritmo
genético em tempo real** e mostra a **rede neural do melhor pássaro ao vivo**:

- Uma população de 24 pássaros (rede `2→5→1`) joga junto sobre os mesmos canos;
  quando todos morrem, o GA cria a próxima geração (elitismo + crossover/mutação
  leves + injeção do campeão histórico, pra nunca regredir pra zero).
- **Dificuldade progressiva:** a cada cano a velocidade sobe e o vão **afunila**
  (de 76px até 38px — bem estreito, só pra profissionais). O treino é **sem teto
  de pontos**: a geração só acaba quando todos morrem, e a dificuldade crescente
  é o limitador natural (sem cap artificial — dá pra ver até onde chegam).
- **Entradas visíveis:** `DIST` (distância ao próximo cano) e `ALT` (altura do
  pássaro relativa ao vão). Os nós acendem (verde/vermelho) pela ativação; a
  saída mostra `FLAP`. Abaixo do painel, um **gráfico de recordes** mostra a
  pontuação de cada geração ao longo do treino.
- Renderiza até **10 pássaros** por vez, cada um numa **cor aleatória** (cara de
  enxame; o melhor com anel branco) e roda a **30 FPS** pra não esquentar a Pi.
- **SALVAR** valida os candidatos em vários mundos novos e grava o **mais
  robusto** (toast `robustez X/30`). **REINICIAR** zera o treino.
- **Jogar contra:** com um cérebro salvo, o **Flappy** normal vira **versus** —
  um pássaro azul controlado pela rede joga ao seu lado (placar VOCÊ × BMO).
- **Continua de onde parou:** ao abrir a tela, o último campeão salvo é
  carregado e o treino segue a partir dele (REINICIAR começa do zero).
- Modelo salvo em `flappy_ai.json` (gitignored).

## Haxball IA (neuroevolução / co-evolução)

A tela **HAXBALL IA** (categoria IA) treina jogadores de Haxball e te deixa
**assistir ao vivo**: um **grid 3×4 de 12 mini-quadras na proporção do campo**
(paisagem, igual ao jogo — o agente treina no mesmo "environment" que enfrenta),
cada uma com um agente ESQUERDA contra um DIREITA + o **placar nas bordas**.

- A **quadra fica VERDE** quando o lado direito está ganhando e **VERMELHA**
  quando o esquerdo ganha. Painel à direita: a **rede neural** do melhor agente
  da direita (ao vivo) + **estatísticas** (geração, gols, gols contra, vitórias,
  largura do gol, fitness).
- **Inputs POLARES + gols (18):** pra bola, oponente, gol-adversário e gol-próprio
  → distância + direção (cos, sin); + velocidade da bola, do oponente e a minha.
  Polar "casa" com a ação (mover numa direção) e dá consciência explícita do gol.
  (Raycasts foram descartados: o ambiente é simples/totalmente observável, então
  raios só repetiriam info e atrasariam o aprendizado.)
- **Memória de curto prazo (recorrência):** além das 18 observações, a rede recebe
  de volta **4 neurônios de memória** que ela própria escreveu no passo anterior —
  um "estado interno" que deixa ela lembrar pra onde a bola ia, se já estava num
  contra-ataque, etc. (não é puramente reativa). Rede `22→32→24→16→7` (3 camadas
  ocultas, tanh): entrada = 18 obs + 4 memória; saídas = ax, ay, **chutar** (3ª
  saída) + as **4 memórias novas**.
- **Currículo adaptativo (sparring):** o oponente começa fraco (~30%, quase um
  *dummy*) e fica **mais forte conforme a IA domina** (sobe pelo saldo de gols,
  recua se a IA apanha) — acompanha o nível dela, como um treinador. É o "jogar
  contra um dummy e ir escalando" levando a IA a aprender jogadas de verdade.
- **Frame canônico:** o lado direito é espelhado no X, então a rede aprende UMA
  política simétrica (serve pros dois lados) — metade da dificuldade.
- **Bootstrap por imitação:** como agentes aleatórios não engajam a bola, as
  populações nascem **seedadas** de um imitador pré-treinado (backprop) de um
  **jogador heurístico** que ataca e defende. A co-evolução refina por cima; um
  **currículo de gol que encolhe** (largo → 60px) ajuda os gols a aparecerem.
- **Matriz de pontuação (funil) no fundo da quadra:** cada quadra tem um **mapa de
  calor** desenhado atrás dos jogadores — verde escuro longe do gol, verde claro na
  **boca do gol** (um *funil*). É o **potencial** `goal_potential(x,y)`: a recompensa
  da IA é a **subida desse potencial** quadro a quadro (`Δpotencial × 25`), então
  levar a bola "morro acima" pelo funil rumo ao gol já pontua — isso a ensina a se
  mover **junto com a bola, cada vez mais perto do gol**, mesmo antes de marcar.
- **Recompensa** = subida do potencial (funil) + gols. **Gol contra** (o defensor
  empurra pra própria meta) leva **penalidade pesada nos dois** e ninguém ganha de
  graça — assim quase não aparece. (De propósito **não** premia toque/movimento
  cru — seria farmável "campando" na quina.)
- **Chute (3ª saída):** a rede DECIDE quando chutar (a 3ª saída > 0). Quando o
  agente quer chutar e o disco está perto da bola pelo lado de ataque, sai um
  **impulso forte** (cooldown) — é assim que se finaliza e fura o goleiro. O lado
  de ataque é checado pra nunca chutar pro próprio gol. No jogo, você chuta
  encostando na bola enquanto controla.
- **SALVAR** grava os campeões (direita + esquerda); **REINICIAR** recomeça do
  zero. Ao abrir, **continua do último salvo** (sem perder trabalho). **30 FPS**.
- **Jogar contra:** no Haxball normal, o adversário azul é a **IA salva** (se
  houver) ou o **jogador heurístico** (forte: ataca + defende). Modelo em
  `haxball_ai.json` (gitignored).

> Nota: a IA treina contra o heurístico (oponente fixo forte) e, com o chute,
> marca de verdade (dezenas de gols por geração) — o placar GIGANTE de cada
> quadra conta ao vivo. Dois jogadores IGUAIS ainda tendem a empatar (a defesa
> fecha), então o melhor da direita (que bate o heurístico) é o que o SALVAR
> guarda pra você enfrentar.

## Refrigeração (coolers)

Dois coolers ligados aos **GPIO 17 (pino 11)** e **GPIO 23 (pino 16)** dão
refrigeração ativa. Ligam por **OR**: o botão **COOLER** da tela SISTEMA
(override manual) **ou** automaticamente quando a temperatura passa de **60 °C**
(histerese desliga abaixo de 55 °C). O ícone de cooler **gira** enquanto ligado.

> ⚠️ Cada GPIO deve chavear um **transistor/MOSFET (ou relé)** que liga o 5 V do
> cooler — nunca o motor direto no pino. Pinos configuráveis com `COOLER_GPIO_1`
> /`COOLER_GPIO_2`. Fora do Pi degrada (vira só visual).

## Pet virtual (humor, memória, carinho)

O BMO não é só uma interface: ele tem **estado emocional, memória e iniciativa**.
Tudo isso é **modular e autossuficiente** — funciona sem câmera e sem microfone
(esses entram só como *bônus* quando existem). Três serviços cuidam disso:

**Humor + energia + afeto** (`pet_state.py`): o humor (feliz / animado /
sonolento / carente / entediado / amoroso) é derivado de sinais que **sempre
existem** — hora do dia, há quanto tempo ninguém interage, e os toques na tela.
A energia segue uma curva do horário (manhã animado, madrugada molinho). O
**afeto** sobe com carinho e a **streak** conta os dias seguidos de convívio.
Persistido em `bmo_pet.json` (gitignored). O humor muda as **expressões e o ritmo**
do BMO FACE e colore o **tom da voz/das respostas**.

**Memória** (`pet_memory.py`): o BMO lembra do seu **nome** e de **fatos** que
você contar ("gosta de café", "trabalha com X"). Ele extrai isso da conversa
(campos `name`/`facts` do JSON) e injeta um resumo no próximo papo — então te
chama pelo nome e referencia suas coisas. Guardado em `bmo_memory.json`
(gitignored).

**Proatividade** (`pet_brain.py`): de vez em quando o BMO **puxa conversa
sozinho** — "você tem 2 compromissos hoje!", "tô ficando quentinho aqui...",
"a gente se fala faz 3 dias seguidos!", ou só uma falinha fofa. Com **cooldowns**
pra não cansar, e só em telas de descanso (nunca durante um jogo ou menu) e
quando o BMO não está ocupado ouvindo/falando. Liga/desliga pela config
`pet_proactive` (padrão ligado).

**Carinho (toque):** cafuné (vários toques rápidos = derretido), long-press
(segura parado = "ãh?") e cutucar o olho (fica emburrado). Tudo isso também
alimenta o afeto. Sem câmera/mic, a interação por toque + humor + proatividade
continua 100%.

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

Histórico das atualizações que entraram de verdade — um pouco de cada uma, em
ordem, **até o último item que adicionamos**. É um registro do que já existe (sem
itens futuros): a cada feature nova, o roadmap ganha mais uma linha no fim.

- [x] **V1** — relógio + home + sleep (3 telas base)
- [x] **V1.1** — clima sem API key, clock P&B, home auto-return, settings com update
- [x] **V1.2** — settings completo: brilho, tema (claro/escuro/auto), shutdown
- [x] **V1.3** — BMO Face (pet procedural com expressões)
- [x] **V1.4** — Tasks/Kanban Todoist com touch drag
- [x] **V1.5** — Pong + Space Invaders (jogos e telas idle bot vs bot)
- [x] **V1.6** — Photo + Gallery (câmera fullscreen + thumbnails)
- [x] **V1.7** — Face tracking via câmera (BMO te vê)
- [x] **V1.8** — Status bar (sol/lua + sinal + bateria) + alerta de update
- [x] **V1.9** — Shuffle ambient (cicla telas idle aleatoriamente)
- [x] **V2.0** — IA: push-to-talk (GPIO) + STT (Whisper/Groq) + chat LLM que abre
  telas e cria tarefas; tela TESTE IA; cleanup de hardware no restart
- [x] **V2.1** — TTS (voz falada): Edge TTS / Francisca pt-BR, fala conversa +
  descrição de visão, com cache de frases (latência ~zero)
- [x] **V2.2** — Pet vivo: humor/energia/afeto/streak, memória do usuário,
  proatividade; voz com emoção; carinho (cafuné/long-press) na BMO Face
- [x] **V2.3** — Mais jogos: Flappy + Snake (minimalistas, touch + botões)
- [x] **V2.4** — **Login pelo Drive + multiusuário**: QR/OAuth (device flow),
  perfis locais, Wipe & Load, sync do `bmo_config` no Drive, pareamento pelo PC
  pra Drive completo
- [x] **V2.5** — **Segundo Cérebro**: grafo de conhecimento das notas Obsidian
  (tela CÉREBRO força-dirigida), espelho bidirecional com o Drive, base do RAG
  local + tool de notas do agente
- [x] **V2.6** — **Gravador** offline-first (aulas/reuniões): WAV local →
  "Sync & Destroy" no Drive
- [x] **V2.7** — **Dev Hub** (tela de programação): commits/CI/logs via GitHub —
  modo menu e ambient + bridge do PC
- [x] **V2.8** — **Refrigeração ativa**: 2 coolers via GPIO (auto >60 °C, ícone
  girando na tela SISTEMA) + grid de AJUSTES (SETTINGS/SISTEMA/DESLIGAR/ATUALIZAR
  com confirmação)
- [x] **V2.9** — **Flappy IA**: treino por neuroevolução em tempo real — rede
  neural do melhor pássaro visível ao vivo, salvar o campeão e jogar contra ele
- [x] **V3.0** — **Haxball** (futebol de botão top-down) + **Haxball IA**:
  co-evolução em grid 3×3 (verde/vermelho), rede + stats, bootstrap por imitação
  de um heurístico, salvar/continuar o treino e jogar contra o adversário
