# BMO OS

Shell retrô estilo **BMO** (Adventure Time) pra Raspberry Pi 4B com tela touch 5"
(800x480). É a interface de um console pessoal que vai morar dentro de uma case
física do BMO — eventualmente com botões físicos (D-pad + A/B/MENU via GPIO),
RetroArch pra rodar emulador, e personalidade própria (rostinhos, reações,
animações idle).

Hoje o foco é a parte de **software/UI**: um shell minimalista, pixel-perfect,
que serve de hub pras telas (relógio, sleep, games, settings) e roda em kiosk
direto no framebuffer do Pi (sem X.org, sem desktop, sem barra de janela).

Tudo em **Python + pygame-ce**, renderizando numa surface lógica de **400x240**
escalada **2x** com nearest-neighbor pra preservar o look de pixel art.

## O que tem hoje

**Telas funcionais:**
- **Clock** — relógio P&B estilo terminal CRT: HH:MM gigante (72px) com dois-pontos
  piscando, segundos pequenos, clima no canto superior esquerdo (temp / umid /
  céu), data no canto inferior direito, brackets nos cantos e scanlines sutis.
  Tap em qualquer lugar → abre o **Home**.
- **Home** — carrossel central (DISPLAY MODE / HOW BMO RESTS / GAMES / SETTINGS)
  com setas tocáveis e footer com atalhos. **Auto-volta pro relógio depois de
  10s sem input**.
- **Sleep** — "HOW BMO RESTS" (placeholder visual da img_0473).
- **Settings** — lista vertical com botão **Atualizar (git pull)**: faz
  `git pull --ff-only` e re-executa o processo. Mensagens de feedback inline
  (`Atualizando...`, `Ja na versao mais nova!`, `OK! Reiniciando...`).
- **Games** — ainda placeholder ("em breve").

**Serviços:**
- **Weather** — [Open-Meteo](https://open-meteo.com) (grátis, sem API key, sem
  cadastro). Default = João Pessoa/PB. Roda em thread separada, refetch a cada
  10 min, fallback silencioso (`--C / --%`) se offline.

**Comportamentos legais:**
- Janela **sem barra de título** (NOFRAME) — mesmo rodando dentro do desktop
  do Pi, não aparece aquela tarja branca no topo.
- Touch é mapeado pras coords lógicas (400x240) antes do hit-test — qualquer
  resolução de display vai funcionar.
- Input abstraído num `Action` enum — quando os botões físicos GPIO chegarem,
  é só adicionar um módulo que dispara as mesmas ações, sem mexer nas telas.

## Estrutura

```
bmo_os/
  main.py              # entry point + wiring das callbacks entre telas
  core/
    app.py             # loop principal + scaler 2x + flags da janela
    screen_manager.py  # pilha de telas (push/pop com enter/exit)
    input.py           # touch+teclado hoje, GPIO depois (mesma API)
    widgets.py         # Carousel, Tile, ListMenu, draw_header, draw_dashed_rect
    theme.py           # paleta BMO, fontes pixel
  screens/
    clock.py           # relógio P&B com clima + brackets + scanlines
    home.py            # carrossel + auto-return em 10s
    sleep.py           # HOW BMO RESTS
    settings.py        # menu com git pull + restart
    placeholder.py     # stub genérico (usado por GAMES)
  services/
    weather.py         # Open-Meteo, thread em background
  assets/
    fonts/             # PressStart2P.ttf (ver "Fontes pixel" abaixo)
    sprites/
  references/          # .webp das fotos do BMO físico — fonte da verdade do look
```

## Setup (Windows, pra desenvolver)

```powershell
cd "D:\Meus Projetos\BMO"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r bmo_os/requirements.txt
python -m bmo_os.main
```

## Setup (Raspberry Pi 4B)

```bash
sudo apt update
sudo apt install python3-pip python3-venv libsdl2-dev
cd ~/BMO
python3 -m venv .venv
source .venv/bin/activate
pip install -r bmo_os/requirements.txt

# rodar sem X (modo kiosk direto no framebuffer):
SDL_VIDEODRIVER=kmsdrm python -m bmo_os.main --fullscreen
```

**Permissões pra usar KMS sem desktop:**
```bash
sudo usermod -aG video,render,input pi   # ou seu user
# logout / login
```

E confirme que o KMS tá ativo (não o "fkms" antigo) em `/boot/firmware/config.txt`:
```
dtoverlay=vc4-kms-v3d
```

### Boot automático com systemd

Crie `/etc/systemd/system/bmo-os.service`:

```ini
[Unit]
Description=BMO OS
After=multi-user.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/BMO
Environment="SDL_VIDEODRIVER=kmsdrm"
# (opcional) sobrescreva a localização — default já é João Pessoa/PB
# Environment="WEATHER_LAT=-7.1195"
# Environment="WEATHER_LON=-34.8450"
# Environment="WEATHER_TIMEZONE=America/Fortaleza"
ExecStart=/home/pi/BMO/.venv/bin/python -m bmo_os.main --fullscreen
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now bmo-os
```

> `Restart=always` deixa o botão "Atualizar" do menu Settings funcionar mesmo
> sem `os.execv` — qualquer exit vira reinício automático.

## Clima (Open-Meteo)

Usa <https://open-meteo.com> — grátis, sem API key, sem cadastro. Default já vem
configurado pra **João Pessoa/PB**. Pra trocar de cidade, defina as variáveis:

```powershell
$env:WEATHER_LAT="-23.5505"     # latitude
$env:WEATHER_LON="-46.6333"     # longitude
$env:WEATHER_TIMEZONE="America/Sao_Paulo"
python -m bmo_os.main
```

Sem internet: as medidas aparecem como `--C` e `--%`, sem erro.

## Fontes pixel

Pro look 100% BMO, baixe uma fonte pixel e ponha em `bmo_os/assets/fonts/`:

- **Press Start 2P** — <https://fonts.google.com/specimen/Press+Start+2P>
  (salve como `PressStart2P.ttf`)
- **Departure Mono** — <https://departuremono.com/>
  (salve como `DepartureMono.ttf`)

Sem fonte custom o sistema usa Consolas/Courier como fallback (funciona, mas
perde a vibe de fliperama).

## Controles

| Ação      | Touchscreen     | Teclado (debug) | GPIO (V2)         |
|-----------|-----------------|-----------------|-------------------|
| Navegar   | Toque nas setas | Setas           | D-pad             |
| Confirmar | Toque no item   | Enter / Espaço  | Botão vermelho A  |
| Voltar    | -               | Esc / Backspace | Botão verde B     |
| Menu      | -               | Tab             | Triângulo azul    |
| Sair      | -               | F4              | -                 |

## Roadmap

- [x] **V1** — relógio + home + sleep (3 telas base)
- [x] **V1.1a** — clima sem API key (Open-Meteo), default João Pessoa
- [x] **V1.1b** — clock P&B retrô + janela sem barra de título
- [x] **V1.1c** — home com auto-return em 10s
- [x] **V1.1d** — settings com botão de update (`git pull` + restart)
- [ ] **V1.2** — settings de verdade (brilho, volume, trocar cidade pelo touch)
- [ ] **V2** — tela games + RetroArch launcher (subprocess)
- [ ] **V2** — input GPIO (gpiozero) quando os botões físicos chegarem
- [ ] **V3** — animações de "personalidade" do BMO (rostinho idle, reações)
- [ ] **V3** — sensores reais (DHT22/BME280 via I2C) em vez/além do clima online
