#!/bin/bash
# Atualiza o BMO OS e reinicia — o caminho oficial, sem gambiarra por SSH.
#
# Uso, no proprio Pi:
#     ~/BMO/scripts/atualizar_bmo.sh
#
# Ou de fora, numa linha so:
#     ssh gravae@192.168.0.110 '~/BMO/scripts/atualizar_bmo.sh'
#
# Faz, nesta ordem: git pull --ff-only -> derruba a instancia que esta rodando
# -> sobe de novo na sessao grafica -> confere se subiu de verdade. Sai com
# codigo != 0 em qualquer falha, entao da pra encadear com && sem medo.
#
# NAO reinicia a maquina e NAO mexe em servico nenhum: so troca o processo.
set -u

REPO="${BMO_REPO:-$HOME/BMO}"
LOG="${BMO_LOG:-/tmp/bmo.log}"
ALVO="bmo_os/main.py"          # o que identifica o processo do BMO
ESPERA_SAIR=8                  # segundos ate apelar pro -9
ESPERA_SUBIR=8                 # segundos ate desistir de esperar ele aparecer

cd "$REPO" || { echo "!! repo nao encontrado em $REPO"; exit 1; }

echo "== 1/3  puxando o codigo mais recente =="
git pull --ff-only || {
    echo "!! git pull falhou (divergiu do remoto? tem mudanca local?)"
    echo "   veja com: cd $REPO && git status"
    exit 1
}
git log --oneline -1

echo
echo "== 2/3  derrubando a instancia atual =="
# pgrep -f casa por linha de comando inteira. Se este script fosse chamado por
# um `bash -c` que contivesse "bmo_os/main.py", ele acharia a si mesmo e se
# mataria no meio — o BMO nunca voltaria. Por isso tiramos nosso PID e o do pai.
derrubar() {
    local sinal="$1" achou=0 p
    for p in $(pgrep -f "$ALVO" 2>/dev/null); do
        [ "$p" = "$$" ] && continue
        [ "$p" = "$PPID" ] && continue
        kill "$sinal" "$p" 2>/dev/null && echo "   $sinal -> PID $p"
        achou=1
    done
    return $((1 - achou))
}

if derrubar -TERM; then
    for _ in $(seq "$ESPERA_SAIR"); do
        derrubar -0 >/dev/null 2>&1 || break
        sleep 1
    done
    if derrubar -0 >/dev/null 2>&1; then
        echo "   nao saiu no TERM, apelando pro KILL"
        derrubar -KILL >/dev/null
        sleep 1
    fi
    echo "   encerrado"
else
    echo "   (nao estava rodando)"
fi

echo
echo "== 3/3  subindo de novo =="
# Rodando por SSH nao herdamos nada da sessao grafica: sem estas tres o pygame
# nao acha a tela e morre com "failed to open display".
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DISPLAY="${DISPLAY:-:0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

cd "$HOME" || exit 1
# setsid + nohup + stdin fechado: o processo sobrevive quando o SSH cair.
setsid nohup python "$REPO/$ALVO" --fullscreen > "$LOG" 2>&1 < /dev/null &

for _ in $(seq "$ESPERA_SUBIR"); do
    sleep 1
    if pgrep -f "$ALVO" >/dev/null 2>&1; then
        echo "   no ar:"
        ps -eo pid,etime,cmd | grep "[b]mo_os/main.py"
        echo
        echo "OK — atualizado e rodando. Log em $LOG"
        exit 0
    fi
done

echo "!! nao subiu. ultimas linhas de $LOG:"
tail -25 "$LOG"
exit 1
