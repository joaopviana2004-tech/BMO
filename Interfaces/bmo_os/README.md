# BMO OS

Shell retrô estilo BMO (Adventure Time) pra Raspberry Pi 4B com tela touch 5" (800x480).
Tudo em Python + pygame-ce, renderizando em surface lógica de 400x240 escalada 2x
pra ficar pixel-perfect.

## Estrutura

```
bmo_os/
  main.py              # entry point
  core/
    app.py             # loop + scaler 2x
    screen_manager.py  # pilha de telas
    input.py           # touch hoje, GPIO depois (mesma API)
    widgets.py         # Carousel, Tile, ListMenu, draw_header
    theme.py           # cores BMO, fontes pixel
  screens/
    clock.py           # img_0471 — relógio + temp/umidade
    home.py            # img_0472 — carrossel home
    sleep.py           # img_0473 — HOW BMO RESTS
    placeholder.py     # stubs Games / Settings (V2)
  services/
    weather.py         # OpenWeather (thread em background)
  assets/
    fonts/             # ver "Fontes" abaixo
    sprites/
```

## Setup (Windows, pra desenvolver)

```powershell
cd "D:\Meus Projetos\BMO\Interfaces"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r bmo_os/requirements.txt
python -m bmo_os.main
```

## Setup (Raspberry Pi 4B)

```bash
sudo apt update
sudo apt install python3-pip python3-venv libsdl2-dev
cd ~/bmo_os
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# rodar sem X (modo kiosk direto no framebuffer):
SDL_VIDEODRIVER=kmsdrm python -m bmo_os.main --fullscreen
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
WorkingDirectory=/home/pi/bmo_os
Environment="SDL_VIDEODRIVER=kmsdrm"
Environment="OPENWEATHER_API_KEY=sua_chave"
Environment="OPENWEATHER_CITY=Sao Paulo,BR"
ExecStart=/home/pi/bmo_os/.venv/bin/python -m bmo_os.main --fullscreen
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now bmo-os
```

## OpenWeather

Pegue chave grátis em <https://openweathermap.org/api> e defina as variáveis:

```powershell
$env:OPENWEATHER_API_KEY="sua_chave"
$env:OPENWEATHER_CITY="Sao Paulo,BR"
python -m bmo_os.main
```

Sem chave: as temperaturas aparecem como `--C` e `--%`, sem erro.

## Fontes pixel

Pro look 100% BMO, baixe uma fonte pixel e ponha em `bmo_os/assets/fonts/`:

- **Press Start 2P** — <https://fonts.google.com/specimen/Press+Start+2P> (salve como `PressStart2P.ttf`)
- **Departure Mono** — <https://departuremono.com/> (salve como `DepartureMono.ttf`)

Sem fonte custom: o sistema usa Consolas/Courier como fallback (ainda fica legal).

## Controles

| Ação    | Touchscreen           | Teclado (debug) | GPIO (V2)         |
|---------|----------------------|-----------------|-------------------|
| Navegar | Toque nas setas       | Setas           | D-pad             |
| Confirmar | Toque no item       | Enter / Espaço  | Botão vermelho A  |
| Voltar  | -                    | Esc / Backspace | Botão verde B     |
| Menu    | -                    | Tab             | Triângulo azul    |
| Sair    | -                    | F4              | -                 |

## Roadmap

- [x] **V1** — relógio + home + sleep (3 telas)
- [ ] **V1.1** — tela settings real (brilho, volume, cidade weather)
- [ ] **V2** — tela games + RetroArch launcher (subprocess)
- [ ] **V2** — input GPIO (gpiozero) quando os botões físicos chegarem
- [ ] **V3** — animações de "personalidade" do BMO (rostinho idle, reações)
- [ ] **V3** — sensores reais (DHT22/BME280 via I2C) em vez/além do OpenWeather
