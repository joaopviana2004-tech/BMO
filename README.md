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
- **PHOTO** — câmera fullscreen:
  - Preview HD 800x480 com hflip (modo selfie)
  - Botão SHOOT vermelho (estilo app de câmera)
  - Boxes brancos sobre rostos detectados
  - Toggle DEBUG (i): mostra FPS, resolução, status do detector
  - Botão GALERIA: abre grid de thumbnails das fotos tiradas
- **GALERIA** — grid 3×2 de thumbs + viewer fullscreen (tap esq/dir = nav)
- **SETTINGS** — lista vertical com cyclers e ações:
  - **Standby** (5/10/15/30/60/120s) — timer de auto-volta da home
  - **Ambient** — qual lock screen usar
  - **Tema** — auto/escuro/claro. *Auto* alterna por hora (6h-18h = claro)
  - **Brilho** — 20/40/60/80/100% via overlay de dimming
  - **BMO te vê** — liga/desliga face tracking pela câmera
  - **Atualizar** — `git pull --ff-only` + restart in-place
  - **Desligar** — shutdown com confirmação dupla em 3s
  - **Voltar**

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
    home.py            # carrossel SLEEP/GAMES/TASKS/PHOTO/SETTINGS
    sleep.py           # tiles dos 5 ambient modes
    games.py           # grid estilo celular (Space Invaders + Pong)
    tasks.py           # kanban Todoist 3 colunas (touch drag)
    photo.py           # camera fullscreen + debug overlay + galeria btn
    gallery.py         # grid 3x2 de thumbs + viewer
    settings.py        # cyclers + atualizar (git pull + os.execv) + desligar
    suspended.py       # tela SUSPENSO: display off + FPS baixo, toque acorda
    placeholder.py     # stub genérico (legado)
  services/
    weather.py         # Open-Meteo, thread + lock + último bom em cache
    todoist.py         # API v1, thread + trigger_refresh
    git_updates.py     # fetch + drift detection
    camera.py          # picamera2 + cv2, refcount lazy (acquire/release)
    audio.py           # sons 8-bit gerados em runtime (numpy) + voz do BMO
  assets/
    fonts/             # PressStart2P.ttf (ver "Fontes pixel" abaixo)
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

O botão **Atualizar** do Settings faz `git pull --ff-only` e reinicia o processo
in-place via `os.execv` (não depende de systemd).

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

**`bmo_config.json`** (preferências persistidas pelo cycler do SETTINGS):
- `idle_timeout_s` — segundos pra home voltar pro ambient
- `ambient_mode` — `clock` | `face` | `pong` | `invaders` | `shuffle`
- `theme` — `auto` | `dark` | `light`
- `brightness` — 20/40/60/80/100
- `camera_face_tracking` — bool (BMO te vê)
- `todoist_token`, `todoist_project` — fallback se não tiver no env

## Todoist (kanban)

Pra a tela TASKS funcionar:

1. **No Todoist**: crie um projeto chamado **`BMO`** (ou outro nome — define em
   `TODOIST_PROJECT`) com 3 seções nomeadas exatamente **`To-Do`**, **`Doing`**,
   **`Done`** (case-insensitive na leitura).
2. Pegue o token em **Todoist → Settings → Integrations → Developer**.
3. Bota no `.env`: `TODOIST_TOKEN=xxxx`.

Cria tarefas no Todoist pelo PC/celular como sempre, e arrasta entre colunas
pelo touch do BMO. SYNC força refresh imediato.

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

Pra atualizar: SETTINGS → ATUALIZAR (faz `git pull --ff-only` + restart).

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
- [ ] **V2.0** — input GPIO (gpiozero) quando os botões físicos chegarem
- [ ] **V2.1** — RetroArch launcher (subprocess) — Games vira lista de ROMs
- [ ] **V2.2** — gestos de mão (MediaPipe Hands) pra controle sem toque
- [ ] **V3** — IMX500 native inference (objeto/pose direto no chip da câmera)
- [ ] **V3** — sensores reais (DHT22/BME280 via I2C) em vez/além do clima online
- [ ] **V3** — speech-to-text (USB mic + Vosk offline) pra "BMO me ouve"
