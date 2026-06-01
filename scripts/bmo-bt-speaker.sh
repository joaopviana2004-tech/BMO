#!/usr/bin/env bash
#
# bmo-bt-speaker.sh — conecta o BMO num alto-falante Bluetooth pareado e o
# define como saída de áudio padrão. Pensado pra rodar no boot via systemd
# (serviço de usuário — veja bmo-bt-speaker.service).
#
# O MAC do alto-falante vem da variável de ambiente BMO_BT_MAC.
# Defina em ~/.config/bmo/bt.env:
#     BMO_BT_MAC=AA:BB:CC:DD:EE:FF
#
# (Opcional) ajuste as tentativas/intervalo:
#     BMO_BT_ATTEMPTS=30   # quantas vezes tenta conectar
#     BMO_BT_SLEEP=3       # segundos entre tentativas
#
set -u

MAC="${BMO_BT_MAC:-}"
ATTEMPTS="${BMO_BT_ATTEMPTS:-30}"   # ~90s (30 x 3s) esperando o speaker acordar
SLEEP="${BMO_BT_SLEEP:-3}"

log() { echo "[bmo-bt] $*"; }

if [ -z "$MAC" ]; then
  log "BMO_BT_MAC nao definido (crie ~/.config/bmo/bt.env). Nada a fazer."
  exit 0
fi

# Liga o controlador Bluetooth (idempotente).
bluetoothctl power on >/dev/null 2>&1 || true

connected() { bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"; }

# Loop de conexao — logo apos o boot o speaker pode ainda nao estar pronto.
i=0
while [ "$i" -lt "$ATTEMPTS" ]; do
  if connected; then break; fi
  i=$((i + 1))
  log "tentativa $i/$ATTEMPTS — conectando em $MAC..."
  bluetoothctl connect "$MAC" >/dev/null 2>&1 || true
  sleep "$SLEEP"
done

if ! connected; then
  log "nao consegui conectar em $MAC apos $ATTEMPTS tentativas."
  exit 1
fi
log "conectado em $MAC."

# Define o speaker como sink de audio padrao. pactl funciona tanto no
# PipeWire (Raspberry Pi OS Bookworm) quanto no PulseAudio antigo. O nome do
# sink do BlueZ contem o MAC com ':' trocado por '_'.
if command -v pactl >/dev/null 2>&1; then
  mac_us="${MAC//:/_}"
  for _ in 1 2 3 4 5; do
    SINK=$(pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -i "$mac_us" | head -n1)
    if [ -n "${SINK:-}" ]; then
      pactl set-default-sink "$SINK" && log "sink padrao = $SINK"
      # Move streams que ja estao tocando pro novo sink.
      pactl list short sink-inputs 2>/dev/null | awk '{print $1}' | while read -r id; do
        [ -n "$id" ] && pactl move-sink-input "$id" "$SINK" 2>/dev/null || true
      done
      break
    fi
    sleep 1
  done
else
  log "pactl nao encontrado — pulei a definicao do sink padrao."
fi

exit 0
