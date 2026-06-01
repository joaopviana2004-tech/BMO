#!/usr/bin/env bash
#
# bmo-os-install.sh — instala o BMO pra iniciar sozinho no boot (kiosk).
#
# Rode NO RASPBERRY PI, como seu usuario normal (NAO com sudo):
#
#   bash ~/BMO/scripts/bmo-os-install.sh
#
# O que faz:
#   - Detecta o caminho real do repo e do venv.
#   - Desativa um eventual bmo-os.service de SISTEMA antigo (evita conflito de tela).
#   - Gera e instala um servico de USUARIO (systemctl --user) com os caminhos certos.
#   - Liga o linger (rodar no boot sem login) e ativa o servico ja agora.
#
# Servico de usuario (em vez de sistema) porque ele compartilha a sessao de
# audio — assim o som do BMO sai no speaker Bluetooth configurado pelo
# bmo-bt-setup.sh. O usuario precisa estar nos grupos video, render e input
# (veja o README) pra acessar a tela e o touch via kmsdrm.
#
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PY="$REPO/.venv/bin/python"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/bmo-os.service"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
log()  { printf '[bmo-os-install] %s\n' "$*"; }
die()  { printf '[bmo-os-install] ERRO: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "rode como seu usuario normal, sem sudo (o servico e --user)."

if [ ! -x "$VENV_PY" ]; then
  die "nao achei o python do venv em: $VENV_PY
       crie o venv primeiro:
         python3 -m venv $REPO/.venv --system-site-packages
         $REPO/.venv/bin/pip install -r $REPO/requirements.txt"
fi

bold "==> Repo:  $REPO"
bold "==> Python: $VENV_PY"

# 1. Desativa um servico de SISTEMA antigo (dois processos brigando pela tela
#    via DRM = tela preta). Ignora se nao existir / sem sudo.
if systemctl list-unit-files 2>/dev/null | grep -q '^bmo-os\.service'; then
  log "achei um bmo-os.service de SISTEMA — desativando pra nao conflitar..."
  sudo systemctl disable --now bmo-os.service 2>/dev/null || \
    log "(nao consegui desativar o de sistema; se a tela ficar preta, rode: sudo systemctl disable --now bmo-os.service)"
fi

# 2. Gera o servico de usuario com os caminhos REAIS detectados.
bold "==> Gerando $UNIT"
mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=BMO OS
Wants=bmo-bt-speaker.service
After=bmo-bt-speaker.service

[Service]
Type=simple
WorkingDirectory=$REPO
Environment=SDL_VIDEODRIVER=kmsdrm
ExecStart=$VENV_PY -m bmo_os.main --fullscreen
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

# 3. Linger (boot sem login) + ativa.
bold "==> Habilitando linger + ativando o servico"
sudo loginctl enable-linger "$USER" 2>/dev/null || \
  log "(nao consegui ligar o linger; rode: sudo loginctl enable-linger $USER)"
systemctl --user daemon-reload
systemctl --user enable --now bmo-os.service || die "falha ao ativar o servico."

echo
bold "Pronto! O BMO deve estar rodando agora e vai subir sozinho no boot."
echo "  - Status:  systemctl --user status bmo-os.service"
echo "  - Logs:    journalctl --user -u bmo-os.service -b"
echo "  - Parar:   systemctl --user stop bmo-os.service"
echo "  - Reiniciar p/ testar boot real:  sudo reboot"
echo
echo "Se a tela ficar preta (conflito de DRM), garanta que NAO tem outro BMO"
echo "rodando: 'systemctl --user stop bmo-os.service', feche terminais rodando o"
echo "BMO na mao, e cheque 'sudo systemctl status bmo-os.service' (servico de sistema)."
