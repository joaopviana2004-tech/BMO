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
  - **Flappy** — passarinho minimalista: toque (ou A) bate asa contra a
    gravidade pra passar pelos canos; +1 por cano, bateu = fim de jogo
  - **Snake** — cobrinha em grade: vira por setas/botões **ou por toque**
    (na direção do toque relativo à cabeça); come, cresce e acelera
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
- **CÉREBRO** — grafo Obsidian interativo (force-directed): nós = notas, arestas
  = wikilinks/tags. Zoom/pan, busca por palavra-chave, ghost nodes pra links que
  apontam pra notas inexistentes. Espelha `knowledge/` do perfil (sincado via
  Drive). Também é um ambient mode (deixa o grafo pulsando no descanso).
- **DEV HUB** — feed de commits, runs de CI e logs dos seus repos: GitHub
  poller direto + push do PC via `scripts/bimo_dev_bridge.py` (PairingServer
  HTTP:8377). Mostra streak de dias com commit, contagem semanal, status do
  último CI. Também serve de ambient.
- **GRAVADOR** — REC/STOP grande, VU meter ao vivo. **Offline-first**: grava
  WAV local mesmo sem rede; fila de "Sync & Destroy" sobe pro Drive
  (`Bimo/Multimidia/Audios`) e deleta local quando confirmado. Pausa o monitor
  do mic enquanto grava (acesso exclusivo ALSA).
- **LOGIN** — fluxo de boot multi-usuário: QR Code (OAuth Device Flow Google) ou
  "USAR SEM CONTA" (convidado). Aparece se nenhum perfil restaurado. Acessível a
  qualquer momento via SETTINGS → CONECTAR.
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
- **Knowledge (Obsidian + RAG)** — `knowledge.py`: parse de `.md` (wikilinks
  `[[]]` + tags `#`) num grafo, com cache por assinatura. Busca por palavra-chave
  (sem embeddings) alimenta a tela CÉREBRO e injeta automaticamente no system
  prompt do chat (RAG) quando match forte. O LLM pode também escrever notas
  novas (tool `notes_write`).
- **Drive sync** — `drive_sync.py`: thread bidirecional pra Google Drive da
  conta logada — pull do config/notas/preferências, push das gravações
  (`Bimo/Multimidia/Audios`) com "sync & destroy" do local após confirmação.
  Notas novas escritas pelo LLM também sobem na hora (`push_note`).
- **Google Auth** — `google_auth.py`: OAuth Device Flow (QR Code da tela LOGIN).
  Refresh token persistido em `profiles/<sub>/tokens.json`. Pra Drive completo
  (vault inteira do Obsidian) precisa de pareamento com PC via
  `scripts/bimo_drive_login.py`.
- **Pairing server** — `pairing.py`: servidor HTTP na porta **8377** pra (a)
  receber token de Drive completo do PC, (b) aceitar chat remoto via
  `scripts/bimo_chat.py`, (c) receber eventos do Dev Hub via
  `scripts/bimo_dev_bridge.py`. IP da Pi exposto no boot.
- **Dev Hub** — `dev_hub.py` + `github_dev.py`: deque de commits/CI/logs (40/8/20).
  GitHub poller a cada 150s puxa stats (commits hoje, semana, streak 7 dias).
  Bridge no PC (`bimo_dev_bridge.py`) faz POST `/dev` com eventos locais.
- **Recorder** — `recorder.py`: serviço do GRAVADOR. Captura em WAV via
  sounddevice, fila pendente, sync ao Drive quando online. Suspende o monitor
  do mic durante gravação.
- **Cooler** — `cooler.py`: GPIO 17/23 pros fans. Histerese **liga ≥60°C**,
  desliga só `<55°C` (não fica pulsando). Override manual em SETTINGS → SISTEMA.
- **Alarmes** — `alarms.py` (pendente de wiring): thread que checa hora vs
  config `alarm_enabled`/`alarm_hour`/`alarm_minute` e dispara callback uma vez
  por minuto-do-dia. UI em `screens/alarm_set.py` (também pendente de wiring).

## Estrutura

```
bmo_os/
  main.py              # entry point + wiring + singletons + frame_hook/overlay_hook
  core/
    app.py             # loop principal + scaler 2x + dimming + mic_button overlay
    screen_manager.py  # pilha de telas (push/pop com enter/exit)
    input.py           # touch+teclado, GPIO depois (mesma Action API)
    widgets.py         # pygame.Color mutável pra tema, corners, scanlines, SAFE_INSET
    theme.py           # fontes pixel/consolas
    theme_state.py     # apply_theme + status bar + draw_mini_clock + sun/moon
    config.py          # defaults + load .env + persistência (por perfil)
    session.py         # multiusuário: profiles/<sub>/, login(), restore(), wipe()
  screens/
    clock.py           # ambient: relógio P&B CRT
    bmo_face.py        # ambient: pet procedural (humor + carinho + camera-aware)
    pong.py            # PongScreen (jogo) + PongAmbientScreen (bot vs bot)
    space_invaders.py  # SpaceInvadersScreen + SpaceInvadersAmbientScreen
    flappy.py          # FlappyScreen (passarinho: toque/A bate asa)
    snake.py           # SnakeScreen (cobrinha: setas/botões ou toque)
    shuffler.py        # ShufflingAmbientScreen (cicla as 4 ambient)
    home.py            # carrossel (15+ telas; ambient + apps + sistema)
    sleep.py           # tiles dos 5 ambient modes
    games.py           # grid estilo celular (Invaders + Pong + Flappy + Snake)
    tasks.py           # kanban Todoist 3 colunas (touch drag)
    agenda.py          # próximos eventos do Google Calendar (multi-conta + cores)
    pomodoro.py        # timer FOCO por tarefa (puxa "Doing" do Todoist)
    photo.py           # camera fullscreen + debug overlay + galeria btn
    gallery.py         # grid 3x2 de thumbs + viewer
    recorder.py        # GRAVADOR: REC/STOP + VU + fila Sync & Destroy ao Drive
    brain.py           # CÉREBRO: grafo Obsidian force-directed (ambient + apps)
    devhub.py          # DEV HUB: feed commits/CI/logs (GitHub + bridge do PC)
    sysinfo.py         # SISTEMA: CPU/temp/memória + override do cooler
    alert.py           # AlertScreen: aviso de evento próximo (por cima de tudo)
    aitest.py          # TESTE IA: mic/STT/câmera/botão + push-to-talk + chat + VISÃO
    mic_button.py      # MicButton: botão de mic virtual (overlay global)
    login.py           # LOGIN: QR Code (Device Flow Google) + USAR SEM CONTA
    alarm_set.py       # (pendente de wiring) UI cycler hora/minuto/ativo
    settings.py        # menu por categorias (SOM/TELA/SISTEMA/IA) + atualizar/desligar/conectar
    suspended.py       # tela SUSPENSO: display off + FPS baixo, toque acorda
    placeholder.py     # stub genérico (legado)
  services/
    weather.py         # Open-Meteo, thread + último bom em cache
    todoist.py         # API v1, thread + trigger_refresh + create
    gcalendar.py       # Google Calendar (iCal secreta ou OAuth), multi-conta
    notifications.py   # EventAlerter: dispara AlertScreen perto da hora
    sysinfo.py         # telemetria de hardware (CPU/temp/memória)
    git_updates.py     # fetch + drift detection + alerta no clock
    camera.py          # picamera2 + cv2, refcount lazy + capture_jpeg
    audio.py           # sons 8-bit (numpy) + canal de voz dedicado
    voice.py           # mic exclusivo: STT (Whisper local / API) + PTT + wake
    chat.py            # LLM (OpenRouter/NVIDIA/Grok/Ollama) -> JSON + visão
    tts.py             # voz do BMO: Edge > Piper > eSpeak + cache + humor
    pet_state.py       # humor/energia/afeto/streak (bmo_pet.json) — sem hardware
    pet_memory.py      # nome + fatos do usuário (bmo_memory.json)
    pet_brain.py       # proatividade: BMO puxa conversa sozinho (cooldowns)
    knowledge.py       # grafo Obsidian (wikilinks + tags) + RAG search
    drive_sync.py      # Drive bidirecional: config/notas pull + áudios push
    google_auth.py     # OAuth Device Flow + refresh token por perfil
    pairing.py         # HTTP:8377: Drive completo, chat remoto, dev hub bridge
    dev_hub.py         # deques de commits/CI/logs + ingest HTTP /dev
    github_dev.py      # poller GitHub (commits/CI/stats/streak 7d)
    recorder.py        # gravador WAV; offline-first; pendentes pro Drive
    cooler.py          # GPIO 17/23 fans com histerese 60/55°C
    alarms.py          # (pendente de wiring) thread que checa hora vs config
    gpio_button.py     # botão físico de push-to-talk (gpiozero, padrão GPIO17)
  assets/
    fonts/             # PressStart2P.ttf (ver "Fontes pixel" abaixo)
    voice_cache/       # MP3 das frases fixas do TTS (gerados em runtime, gitignored)
  references/          # .webp/.png das fotos do BMO físico e refs de face
profiles/              # criado em runtime, gitignored — um diretório por perfil
  _active              # arquivo aponta pro perfil ativo (texto)
  <sub>/               # ID Google (ou "guest") como pasta
    profile.json       # identidade (nome, email, avatar)
    tokens.json        # OAuth Drive/Calendar (refresh token)
    bmo_config.json    # preferências DESTE perfil (volume, IA, tema, etc)
    recordings/        # WAVs gravados offline, aguardando sync
    knowledge/         # espelho local da vault Obsidian do perfil
scripts/               # utilidades (não rodam dentro do BMO)
  bmo-bt-setup.sh        # instalador 1-comando do alto-falante Bluetooth
  bmo-bt-speaker.sh      # conecta no speaker + define sink padrão (boot)
  bmo-bt-speaker.service # serviço systemd --user
  bluetooth.md           # passo a passo do Bluetooth
  bimo_drive_login.py    # pareamento PC↔Bimo pra Drive completo (vault)
  bimo_chat.py           # chat de texto do PC com o Bimo (sem mic)
  bimo_pc_sync.py        # espelho bidirecional Obsidian ↔ Drive
  bimo_dev_bridge.py     # envia commits/CI do PC pro Dev Hub do Bimo
  gcal_auth.py           # OAuth one-shot pra Google Calendar Workspace
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

**`.env`** na raiz (env vars carregadas automaticamente no boot). O
`.env.example` (commitado) é só uma lista limpa de campos pra copiar — a doc
completa de cada chave fica aqui embaixo, agrupada por feature. **Tudo é
opcional**: sem a chave, o recurso só fica indisponível, o BMO segue rodando.
Env vars já no shell têm precedência sobre o arquivo.

#### Login Google + perfis (tela LOGIN / multiusuário)

QR Code (OAuth Device Flow) + Drive gerenciado pelo BMO em pastas
`Bimo/Conhecimento` (segundo cérebro), `Bimo/Multimidia/Audios` (gravações),
`Bimo/Preferencias` (config por perfil).

**Como obter** (uma vez): [console.cloud.google.com](https://console.cloud.google.com) → crie ou use um projeto →
1. *APIs e serviços* → ative a **Google Drive API**
2. *Tela de permissão OAuth*: publique o app ("Em produção") pra o refresh
   token não vencer em 7 dias
3. *Credenciais* → *Criar credenciais* → *ID do cliente OAuth* → tipo
   **"TVs e dispositivos de entrada limitada"**

```
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

**Drive completo** (recomendado se usa Obsidian sincado pelo Google Drive
Desktop): o QR acima é limitado pelo Google ao escopo `drive.file` (o BMO só
vê o que ele mesmo criou). Pra ler a vault inteira, no MESMO projeto crie uma
credencial tipo **"App para computador"** e rode o pareamento no PC (token
chega no BMO pela rede local):
```bash
python scripts/bimo_drive_login.py <ip-do-bimo>
```
```
GOOGLE_DESKTOP_CLIENT_ID=
GOOGLE_DESKTOP_CLIENT_SECRET=
```

Alternativa sem o pareamento (login só por QR): espelhe a vault com:
```bash
python scripts/bimo_pc_sync.py "C:\caminho\da\vault"
```

#### Todoist (tela TASKS)
Token em [app.todoist.com](https://app.todoist.com) → Settings → Integrations
→ Developer. O projeto precisa ter 3 seções nomeadas exatamente: **To-Do**,
**Doing**, **Done**.
```
TODOIST_TOKEN=
TODOIST_PROJECT=BMO   # opcional; default = BMO
```

#### Google Calendar (tela AGENDA)
Pares `rotulo=fonte` separados por vírgula. Fonte = URL secreta iCal (agenda
privada) **OU** e-mail/ID de agenda pública.
```
GCAL_ICS_URLS=Pessoal=https://calendar.google.com/calendar/ical/.../basic.ics,Trampo=outro@gmail.com
```

Pra agenda privada sem URL secreta (Workspace), use OAuth — preencha as
credenciais abaixo e rode uma vez (passo a passo no topo do script):
```bash
python scripts/gcal_auth.py
```
```
GCAL_CLIENT_ID=
GCAL_CLIENT_SECRET=
```

#### IA: chat + visão (LLM)
Provedor e modelo (de chat **E** de visão) saem do menu SETTINGS → IA. Aqui
só a chave do(s) provedor(es) que for usar:
```
OPENROUTER_API_KEY=    # openrouter.ai/keys
NVIDIA_API_KEY=        # build.nvidia.com (nvapi-...)
XAI_API_KEY=           # console.x.ai (Grok)
```

#### LLM local no PC (Ollama)
Alternativa gratuita/offline aos provedores de nuvem: roda Ollama no PC e
aponta o BMO pra ele (SETTINGS → IA → provedor **LOCAL (PC)**).

**No PC**: instale o [Ollama](https://ollama.ai), baixe um modelo
(`ollama pull llama3.2`) e sirva na rede:
```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

**Na Pi** (este `.env`):
```
LOCAL_LLM_HOST=192.168.0.102   # ip do PC (porta padrão 11434)
LOCAL_LLM_MODEL=llama3.2       # modelo padrão do cycler
LOCAL_LLM_URL=                 # (alternativa) URL completa do endpoint
```

Utilidades complementares no PC:
- `python scripts/bimo_chat.py <ip-do-bimo>` — chat de texto sem mic
- `python scripts/bimo_pc_sync.py "C:\caminho\vault"` — espelho Obsidian ↔ Drive (notas criadas pelo BMO no Drive aparecem em `vault/Bimo/`)
- `python scripts/bimo_dev_bridge.py <ip-do-bimo> --repo .` — empurra commits/CI pro Dev Hub
- `python scripts/bimo_dev_bridge.py <ip-do-bimo> --install-hook --repo .` — instala post-commit hook

#### Voz: BMO ouve (STT)
Transcrição via API compatível-OpenAI (**recomendado no Pi**: sem calor, sem
modelo pesado local). Default é Groq. Sem chave, tenta Whisper local
(`pywhispercpp`, `STT_BACKEND=local`).
```
STT_API_KEY=    # console.groq.com
```

Wake word "BIMO" (opcional, Porcupine): crie a keyword no
[console.picovoice.ai](https://console.picovoice.ai), baixe o `.ppn` pra
`bmo_os/assets/bimo.ppn` e ponha a chave. Atalho pra testar sem treinar:
`PORCUPINE_KEYWORD=computer` usa keyword builtin.
```
PORCUPINE_ACCESS_KEY=
```

Botão físico de push-to-talk (GPIO, segura pra gravar; default GPIO17):
```
PTT_GPIO=17
```

#### Voz: BMO fala (TTS)
Padrão = Edge TTS (voz Francisca pt-BR, grátis, precisa de internet).
Install: `pip install edge-tts`. A fala é decodificada inteira pra memória e
toca num canal reservado do mixer (nunca começa cortada nem disputa com os
efeitos). Volume em SETTINGS → IA ("Voz BMO"); `tts_volume=0` deixa mudo.

Sem `edge-tts` a voz fica **off** (não cai numa voz masculina do Piper). Pra
forçar outro motor:
```
BMO_TTS_BACKEND=edge                       # edge|piper|espeak (default edge)
BMO_TTS_EDGE_VOICE=pt-BR-FranciscaNeural
BMO_TTS_GAIN=1.0                           # ganho de software só da voz (1.4 = +40%, clip seguro)
```

#### Áudio (mixer)
Buffer em samples @44100Hz (512 = ~11.6ms). Valores menores reduzem latência
mas podem dar underrun/estalo no Pi. Um keep-alive de silêncio roda sempre
pra o ALSA/PipeWire não suspender o device (era a causa de som atrasado/
engolido).
```
BMO_AUDIO_BUFFER=512
```

#### Câmera
```
BMO_CAMERA=auto   # auto (padrão) | usb (força webcam USB) | pi (força picamera2/CSI)
```

#### Clima (tela CLOCK)
Default = João Pessoa/PB. Open-Meteo, sem chave necessária.
```
WEATHER_LAT=-7.1195
WEATHER_LON=-34.8450
WEATHER_TIMEZONE=America/Fortaleza
```

#### Dev Hub (GitHub direto na Pi)
O BMO puxa commits, CI/Actions e stats da API do GitHub em background. Token
recomendado (mais rate limit + repos privados): GitHub → Settings → Developer
settings → **Personal Access Token**.
```
GITHUB_USER=seu-user
GITHUB_TOKEN=ghp_xxxxxxxx
GITHUB_REPOS=BMO,Outros   # opcional; vazio = top repos por push recente
```

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
- **LLM (resposta):** OpenRouter, NVIDIA NIM, Grok (xAI) **ou LOCAL (PC via
  Ollama)** — todos compatíveis com OpenAI. O provedor e o modelo são escolhidos
  em **SETTINGS → IA** (troca rápida por cycler). O BMO responde sempre com um
  JSON `{"msg", "screen", "task", "facts", "name", "notes_query", "notes_write"}`.
  Pra usar local: rode `OLLAMA_HOST=0.0.0.0 ollama serve` no PC, ponha
  `LOCAL_LLM_HOST=<ip-do-pc>` no `.env` e selecione **LOCAL (PC)** no menu.
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

## Multi-usuário (perfis + login Google)

O BMO suporta vários usuários — cada um com **suas próprias preferências,
gravações e vault Obsidian**. Implementado em `core/session.py`:

- Cada perfil vive em `profiles/<sub>/` (`sub` = ID Google ou `guest`)
- O perfil ativo é apontado pelo arquivo `profiles/_active`
- `config.get()`/`set_value()` lê/grava do `bmo_config.json` **DO PERFIL** ativo

**Boot**: se `_active` aponta pra um perfil válido com `tokens.json`, `restore()`
volta direto pro ambient dele. Senão, abre a tela LOGIN (QR Code Device Flow ou
"USAR SEM CONTA").

**Login por QR** (sem precisar de teclado/mouse na Pi):
1. Configure `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` no `.env`
   (tipo de credencial: "TVs e dispositivos de entrada limitada" no Google Cloud)
2. LoginScreen mostra QR + código manual
3. Você escaneia, aprova no celular, BMO recebe o token via polling

**Drive completo** (vault Obsidian inteira, não só o que o app cria): Google
limita o Device Flow ao escopo `drive.file`. Pra ler vault de fora, pareia uma
vez pelo PC:
```bash
python scripts/bimo_drive_login.py <ip-do-bimo>
```
Isso usa `GOOGLE_DESKTOP_CLIENT_ID`/`SECRET` (tipo "App para computador") e
manda o token via PairingServer:8377.

**Logout** (SETTINGS → "Sair"): faz Sync & Destroy de tudo (sobe pendentes, apaga
local), wipe da pasta do perfil, `execv` clean. Volta pra tela LOGIN.

## Knowledge / RAG (Obsidian)

`services/knowledge.py` lê os `.md` da pasta `knowledge/` do perfil, parseia
**wikilinks `[[Nota]]`** e **tags `#x`**, monta um grafo e cacheia por
assinatura (mtime).

**Busca**: `knowledge.search(query, k=3)` pontua por título (4), tag (3) e
ocorrências no corpo (cap 6). Sem embeddings — é word-key simples mas rápido.

**RAG automático**: o `chat.ask()` chama internamente `_auto_notes(text)` antes
de mandar pro LLM e, se achar match com score ≥ 4, injeta um bloco
"NOTAS DO USUARIO (do Obsidian dele)" no system prompt. O LLM responde
referenciando os trechos.

**Tools do LLM**:
- `notes_query`: o LLM pede uma busca extra (refaz `ask` com o contexto novo)
- `notes_write: {"title", "body", "mode": "create|append|replace"}`: cria/edita
  uma nota; `drive_sync.push_note()` sobe na hora pro Drive

**Tela CÉREBRO**: visualização force-directed do grafo, zoom/pan, busca por
texto, ghost nodes pros `[[]]` que apontam pra notas inexistentes. Também roda
como ambient mode.

**Espelho com PC**: rode `python scripts/bimo_pc_sync.py "C:\caminho\vault"` no
PC pra sincronizar bidirecionalmente — você edita no Obsidian, o BMO vê.

## Dev Hub (commits, CI, logs)

Tela DEV HUB mostra um feed da sua atividade de código:

**GitHub poller** (`services/github_dev.py`): puxa commits, runs de
Actions e stats da API do GitHub a cada 150s. Mostra commits hoje, semana,
**streak de dias seguidos** com commit.

**Bridge do PC** (`scripts/bimo_dev_bridge.py`): rode no seu repo e ele
faz `POST /dev` pro PairingServer da Pi com commits novos + estado do CI +
linhas de log. Útil pra ver build status sem alt-tab.
```bash
python scripts/bimo_dev_bridge.py <ip-do-bimo> --repo .
python scripts/bimo_dev_bridge.py <ip-do-bimo> --install-hook --repo .   # post-commit auto
```

**Setup GitHub** (`.env`):
```
GITHUB_USER=seu-usuario
GITHUB_TOKEN=ghp_xxxx          # rate limit + repos privados
GITHUB_REPOS=BMO,Outros        # opcional; vazio = top por push recente
```

## Pareamento com PC (PairingServer:8377)

A Pi sobe um HTTP server local na porta **8377** pra coisas que não cabem na
tela touch:

| Endpoint | Quem usa | Função |
|---|---|---|
| `POST /pair` | `bimo_drive_login.py` | Recebe token Drive completo do PC |
| `POST /chat` | `bimo_chat.py` | Conversa por texto sem usar mic |
| `POST /dev` | `bimo_dev_bridge.py` | Envia commits/CI pro Dev Hub |

Não tem autenticação — assume rede local confiável. **Não exponha 8377 pra
internet pública.**

## Refrigeração (Cooler)

`services/cooler.py` controla até dois fans nos GPIO 17/23 (configurável). Lê
a temperatura via `sysinfo` e aplica **histerese**:

- Liga quando `temp_c >= 60°C`
- Desliga só quando `temp_c < 55°C` (gap de 5° evita on/off seguido)

Pode ser ligado **manualmente** em SETTINGS → SISTEMA ("Cooler: ON/OFF/AUTO"),
que sobrescreve o automático até o próximo boot. Sem GPIO disponível (PC dev),
o serviço fica inerte sem dar erro.

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
- [x] **V2.2** — TTS (voz falada do BMO): Edge TTS / voz Francisca pt-BR
  (incorporado do lab `bmo_voz.py`), fala conversa + descrição de visão
- [x] **V2.3** — Pet vivo: humor/energia/afeto/streak (`pet_state`), memória do
  usuário (`pet_memory`), proatividade (`pet_brain`); voz com emoção; carinho
  (cafuné/long-press) + animação de dormir na BMO Face
- [x] **V2.4** — Mais jogos: Flappy + Snake (minimalistas, touch + botões)
- [x] **V2.5** — Wake word offline "BIMO" (Porcupine) — `voice_enabled` na config
- [x] **V2.6** — Multi-usuário: perfis (`profiles/<sub>/`) + LoginScreen com
  QR Code (OAuth Device Flow) + logout com Sync & Destroy
- [x] **V2.7** — Knowledge / RAG: grafo Obsidian (`knowledge.py`), tela CÉREBRO
  force-directed, injeção automática no chat, `notes_write` tool
- [x] **V2.8** — Drive sync bidirecional + pareamento com PC (PairingServer:8377,
  scripts `bimo_drive_login.py` / `bimo_pc_sync.py` / `bimo_chat.py`)
- [x] **V2.9** — Dev Hub: feed de commits/CI/logs (GitHub poller + bridge do PC
  via `bimo_dev_bridge.py`), tela DEV HUB
- [x] **V3.0** — Gravador offline-first (WAV + fila Sync & Destroy ao Drive)
- [x] **V3.1** — Cooler GPIO 17/23 com histerese 60/55°C
- [x] **V3.2** — Mic virtual (botão overlay global nas telas com `show_mic_button`)
- [x] **V3.3** — LLM local via Ollama no PC (4º provedor)
- [ ] **V3.4** — Alarmes (`services/alarms.py` + `screens/alarm_set.py` prontos,
  faltando wiring em main.py)
- [ ] **V3.5** — Input GPIO completo (D-pad + A/B/MENU físicos)
- [ ] **V3.6** — RetroArch launcher (subprocess) — Games vira lista de ROMs
- [ ] **V3.7** — Gestos de mão (MediaPipe Hands)
- [ ] **V4** — IMX500 native inference (objeto/pose direto no chip da câmera)
- [ ] **V4** — Sensores reais (DHT22/BME280 via I2C) em vez/além do clima online
