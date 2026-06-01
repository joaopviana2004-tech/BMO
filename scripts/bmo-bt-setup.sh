#!/usr/bin/env bash
#
# bmo-bt-setup.sh — instalador "um comando só" do alto-falante Bluetooth do BMO.
#
# Rode NO RASPBERRY PI:
#
#   # 1) Sem o MAC ainda? Escaneia e lista os aparelhos por perto:
#   bash ~/BMO/scripts/bmo-bt-setup.sh
#
#   # 2) Com o MAC do speaker (ligue ele em modo pareamento antes):
#   bash ~/BMO/scripts/bmo-bt-setup.sh AA:BB:CC:DD:EE:FF
#
# O passo 2 faz TUDO: pareia, da trust, conecta, salva o MAC em
# ~/.config/bmo/bt.env, instala o servico de boot (systemd --user), ativa o
# linger e define o speaker como saida de audio padrao. Idempotente — pode
# rodar de novo sem problema.
#
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="$SCRIPT_DIR/bmo-bt-speaker.service"
CONNECT_SH="$SCRIPT_DIR/bmo-bt-speaker.sh"
ENV_DIR="$HOME/.config/bmo"
ENV_FILE="$ENV_DIR/bt.env"
USER_UNIT_DIR="$HOME/.config/systemd/user"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
log()  { printf '[bmo-bt-setup] %s\n' "$*"; }
die()  { printf '[bmo-bt-setup] ERRO: %s\n' "$*" >&2; exit 1; }

command -v bluetoothctl >/dev/null 2>&1 || die "bluetoothctl nao encontrado. Instale: sudo apt install bluez"

# ---------- modo descoberta (sem argumento) ----------
if [ "$#" -eq 0 ]; then
  bold "Nenhum MAC informado — escaneando aparelhos Bluetooth por ~15s..."
  log  "Deixe o alto-falante LIGADO e em modo pareamento agora."
  bluetoothctl power on >/dev/null 2>&1 || true
  bluetoothctl --timeout 15 scan on >/dev/null 2>&1 || true
  echo
  bold "Aparelhos encontrados:"
  bluetoothctl devices | sed 's/^Device //'
  echo
  bold "Agora rode de novo com o MAC do seu speaker, ex:"
  echo "  bash $SCRIPT_DIR/bmo-bt-setup.sh AA:BB:CC:DD:EE:FF"
  exit 0
fi

# ---------- modo setup (com o MAC) ----------
MAC="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
echo "$MAC" | grep -Eq '^([0-9A-F]{2}:){5}[0-9A-F]{2}$' \
  || die "MAC invalido: '$1' (esperado formato AA:BB:CC:DD:EE:FF)"

[ -f "$SERVICE_SRC" ] || die "nao achei $SERVICE_SRC (rode a partir do repo BMO)."
[ -f "$CONNECT_SH" ]  || die "nao achei $CONNECT_SH (rode a partir do repo BMO)."

bold "==> 1/5  Salvando o MAC em $ENV_FILE"
mkdir -p "$ENV_DIR"
printf 'BMO_BT_MAC=%s\n' "$MAC" > "$ENV_FILE"
log "ok: BMO_BT_MAC=$MAC"

bold "==> 2/5  Pareando / confiando / conectando ($MAC)"
log "ligue o speaker em modo pareamento se ainda nao estiver."
# Sessao unica do bluetoothctl: o subshell que alimenta o stdin fica vivo
# durante os sleeps, entao o scan continua ligado enquanto descobrimos o
# aparelho, e so depois pareamos. agent on/default-agent cobrem o pareamento.
{
  echo "power on";    sleep 1
  echo "agent on"
  echo "default-agent"
  echo "scan on";     sleep 12
  echo "scan off"
  echo "pair $MAC";   sleep 6
  echo "trust $MAC";  sleep 2
  echo "connect $MAC"; sleep 6
  echo "quit"
} | bluetoothctl >/dev/null 2>&1 || true

if bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"; then
  log "conectado."
else
  log "ainda nao conectou — sem estresse, o servico de boot tenta de novo."
  log "verifique se o speaker estava ligado/em pareamento e rode este script outra vez."
fi

bold "==> 3/5  Instalando o servico de boot (systemd --user)"
chmod +x "$CONNECT_SH"
mkdir -p "$USER_UNIT_DIR"
cp "$SERVICE_SRC" "$USER_UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now bmo-bt-speaker.service >/dev/null 2>&1 || true
log "servico bmo-bt-speaker.service ativado."

bold "==> 4/5  Habilitando linger (rodar no boot sem login)"
if sudo -n true 2>/dev/null || [ -t 0 ]; then
  sudo loginctl enable-linger "$USER" && log "linger ligado para $USER."
else
  log "pulei o linger (sem sudo). Rode manualmente: sudo loginctl enable-linger $USER"
fi

bold "==> 5/5  Definindo o speaker como saida de audio padrao"
BMO_BT_MAC="$MAC" "$CONNECT_SH" || true

echo
bold "Pronto! Resumo:"
echo "  - MAC salvo em:  $ENV_FILE"
echo "  - Servico:       systemctl --user status bmo-bt-speaker.service"
echo "  - Logs do boot:  journalctl --user -u bmo-bt-speaker.service -b"
echo "  - Teste de som:  speaker-test -c2 -twav -l1"
echo
echo "Se o som do BMO nao sair no speaker, veja a secao de troubleshooting em"
echo "  $SCRIPT_DIR/bluetooth.md  (provavelmente precisa rodar o BMO como servico --user tambem)."
