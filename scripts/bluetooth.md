# Conectar num alto-falante Bluetooth no boot

Faz o BMO conectar automaticamente num alto-falante Bluetooth quando o Raspberry
Pi liga, e define ele como saída de áudio padrão.

São dois arquivos neste diretório:
- `bmo-bt-speaker.sh` — script que conecta no speaker (com retry) e define o sink padrão.
- `bmo-bt-speaker.service` — serviço systemd **de usuário** que roda o script no boot.

O MAC do speaker **não** fica em nenhum arquivo versionado — ele vive em
`~/.config/bmo/bt.env` no Pi (assim sobrevive a `git pull`).

> Tudo abaixo roda **no Raspberry Pi**, não no PC de desenvolvimento.

## 1. Descobrir o MAC do alto-falante (uma vez)

Ligue o speaker em modo de pareamento e, no Pi:

```bash
bluetoothctl
# dentro do prompt do bluetoothctl:
power on
agent on
default-agent
scan on
# espere aparecer o nome do seu speaker e anote o MAC (ex: AA:BB:CC:DD:EE:FF)
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF      # IMPORTANTE: trust = o BlueZ reconecta sozinho depois
connect AA:BB:CC:DD:EE:FF
scan off
exit
```

O `trust` é o que faz o speaker reconectar sozinho sempre que aparece. O serviço
de boot é só pra forçar a conexão rápido e definir o áudio padrão.

## 2. Salvar o MAC pro serviço

```bash
mkdir -p ~/.config/bmo
echo 'BMO_BT_MAC=AA:BB:CC:DD:EE:FF' > ~/.config/bmo/bt.env
```

(troque pelo MAC real do passo 1)

## 3. Instalar e ativar o serviço

```bash
chmod +x ~/BMO/scripts/bmo-bt-speaker.sh
mkdir -p ~/.config/systemd/user
cp ~/BMO/scripts/bmo-bt-speaker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bmo-bt-speaker.service

# Faz o serviço de usuário rodar no boot mesmo sem ninguém logar:
sudo loginctl enable-linger "$USER"
```

## 4. Verificar

```bash
systemctl --user status bmo-bt-speaker.service
journalctl --user -u bmo-bt-speaker.service -b      # logs do último boot
pactl info | grep "Default Sink"                    # deve mostrar o sink do speaker
speaker-test -c2 -twav -l1                           # toca um som de teste
```

## Se o som do BMO não sair no speaker

A conexão pode funcionar mas o som do BMO continuar saindo no lugar errado. Isso
acontece porque o BMO, hoje, roda como serviço **de sistema** (`User=pi`, veja o
`bmo-os.service` no README), enquanto o áudio (PipeWire/PulseAudio) e esta conexão
Bluetooth vivem na **sessão de usuário** — são contextos diferentes.

Duas formas de resolver:

**Opção A (recomendada) — rodar o BMO também como serviço de usuário**, na mesma
sessão do áudio. Mova o serviço do BMO pra `~/.config/systemd/user/` e ative com
`systemctl --user enable --now` + `loginctl enable-linger` (igual ao passo 3). Aí
o BMO compartilha o PipeWire e o sink padrão automaticamente.

**Opção B — manter o BMO como serviço de sistema** e apontar o áudio pra sessão do
usuário, adicionando ao `[Service]` do `bmo-os.service`:

```ini
Environment="XDG_RUNTIME_DIR=/run/user/1000"
Environment="PULSE_SERVER=unix:/run/user/1000/pulse/native"
```

(`1000` é o UID do usuário — confirme com `id -u`.)

Me avisa qual opção você prefere que eu já deixo o `bmo-os.service` ajustado.

## Trocar de speaker depois

Edite o MAC em `~/.config/bmo/bt.env` e rode `systemctl --user restart bmo-bt-speaker.service`.
(Pareie/trust o novo speaker antes, como no passo 1.)
