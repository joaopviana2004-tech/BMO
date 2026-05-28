import pygame
import threading
from ollama import Client
from game import GameEngine, CELL_W, CELL_H, GRID_N, WIDTH, HEIGHT

# ==========================================
# CONFIGURAÇÃO DO OLLAMA
# ==========================================
DEFAULT_OLLAMA_URL = "https://sternmost-interregional-heath.ngrok-free.dev/"
MODEL = "llama3.1:8b"

# ==========================================
# SYSTEM PROMPT
# ==========================================
SYSTEM_PROMPT = """Você é um jogador de um shooter tático top-down por turnos. Você é o 'p' no mapa.

MAPA: grade {grid}x{grid}. '-'=vazio, '+'=obstáculo, 'p'=você, 'b'=inimigo.

AÇÕES (escolha UMA por turno):
- mover(direcao): move 1 célula. direcao = "cima", "baixo", "esquerda" ou "direita"
- atirar(linha, coluna): atira na célula onde está o inimigo 'b'. Se errar, arma fica em cooldown 2 turnos. Se acertar, sem cooldown.
- parar(): fica parado.

REGRAS:
- Você tem {hp_max} HP. Se chegar a 0, morre.
- Obstáculos '+' bloqueiam tiros e movimento.
- Só atire em células com 'b' e com linha de visão limpa (sem '+' entre você e o alvo).
- Se arma está RECARREGANDO, use mover ou parar.

RESPONDA SEMPRE neste formato exato:
PENSAMENTO: (1 frase sobre sua estratégia)
AÇÃO: mover("direcao") ou atirar(linha, coluna) ou parar()

Exemplo de respostas corretas:
PENSAMENTO: Há um bot na mesma linha que eu sem obstáculos, vou atirar.
AÇÃO: atirar(5, 12)

PENSAMENTO: Preciso me aproximar do inimigo, vou descer.
AÇÃO: mover("baixo")

PENSAMENTO: Arma recarregando, vou esperar.
AÇÃO: parar()"""

# ==========================================
# TOOLS
# ==========================================
TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'mover',
            'description': 'Move o player 1 célula na direção escolhida',
            'parameters': {
                'type': 'object',
                'properties': {
                    'direcao': {
                        'type': 'string',
                        'description': 'Direção do movimento: "cima", "baixo", "esquerda" ou "direita"',
                        'enum': ['cima', 'baixo', 'esquerda', 'direita'],
                    },
                },
                'required': ['direcao'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'atirar',
            'description': 'Atira um projétil na direção de uma célula alvo do grid',
            'parameters': {
                'type': 'object',
                'properties': {
                    'linha': {
                        'type': 'integer',
                        'description': 'Linha da célula alvo (0 = topo)',
                    },
                    'coluna': {
                        'type': 'integer',
                        'description': 'Coluna da célula alvo (0 = esquerda)',
                    },
                },
                'required': ['linha', 'coluna'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'parar',
            'description': 'Fica parado sem fazer nada neste turno',
            'parameters': {
                'type': 'object',
                'properties': {},
            },
        },
    },
]

DIRECOES = {
    'cima': pygame.math.Vector2(0, -1),
    'baixo': pygame.math.Vector2(0, 1),
    'esquerda': pygame.math.Vector2(-1, 0),
    'direita': pygame.math.Vector2(1, 0),
}


def format_state_map(grid):
    """Formata o minimapa como string legível."""
    header = "    " + "  ".join(f"{c:2d}" for c in range(len(grid[0])))
    lines = [header]
    for r, row in enumerate(grid):
        lines.append(f"{r:2d}  " + "  ".join(f" {cell}" for cell in row))
    return "\n".join(lines)


def build_turn_message(engine, turn_number, prev_events):
    """Monta a mensagem do turno com mapa + feedback de eventos."""
    grid = engine.get_state_map()
    minimap = format_state_map(grid)

    pc = int(engine.player.pos.x // CELL_W)
    pr = int(engine.player.pos.y // CELL_H)

    bots_info = []
    for bot in engine.bots:
        bc = int(bot.pos.x // CELL_W)
        br = int(bot.pos.y // CELL_H)
        dist = abs(pc - bc) + abs(pr - br)

        # Verifica se há linha de visão limpa
        has_los = engine.has_line_of_sight(engine.player.pos, bot.pos)
        los_text = "SIM" if has_los else "NÃO (obstáculo no caminho)"

        bots_info.append(
            f"  - Bot em (linha={br}, coluna={bc}), distância={dist}, linha de visão: {los_text}"
        )

    bots_text = "\n".join(bots_info) if bots_info else "  Nenhum bot vivo!"

    cooldown = engine.player.reload_cooldown
    arma_status = "PRONTA" if cooldown == 0 else f"RECARREGANDO ({cooldown} turnos restantes)"

    # Monta feedback de eventos do turno anterior
    feedback = ""
    if prev_events:
        feedback = "\n📋 FEEDBACK DO TURNO ANTERIOR:\n"
        for evt in prev_events:
            feedback += f"  → {evt}\n"
    elif turn_number > 1:
        feedback = "\n📋 FEEDBACK DO TURNO ANTERIOR:\n  → Nenhum evento relevante.\n"

    msg = f"""TURNO {turn_number}{feedback}
{minimap}

Você: linha={pr}, coluna={pc} | HP: {engine.player.hp} | Arma: {arma_status} | Bots vivos: {len(engine.bots)}
{bots_text}

Responda com PENSAMENTO e AÇÃO."""

    return msg


def process_llm_action(engine, tool_call):
    """Converte a tool call da LLM em ação do jogo."""
    name = tool_call.function.name
    args = tool_call.function.arguments

    if name == 'mover':
        direcao = args.get('direcao', 'cima')
        vec = DIRECOES.get(direcao, pygame.math.Vector2(0, -1))
        engine.execute_turn("MOVE", vec)
        return f"MOVER {direcao.upper()}"

    elif name == 'atirar':
        linha = int(args.get('linha', 0))
        coluna = int(args.get('coluna', 0))
        alvo_x = coluna * CELL_W + CELL_W / 2
        alvo_y = linha * CELL_H + CELL_H / 2
        alvo = pygame.math.Vector2(alvo_x, alvo_y)
        engine.execute_turn("SHOOT", alvo)
        return f"ATIRAR na célula ({linha}, {coluna})"

    elif name == 'parar':
        engine.execute_turn("STOP")
        return "PARAR"

    return "AÇÃO DESCONHECIDA"


def parse_action_from_text(text):
    """Fallback: extrai a ação do texto quando a LLM não usa tool calling."""
    import re
    text_lower = text.lower()

    # Tenta extrair atirar(linha, coluna) - vários formatos
    match = re.search(r'atirar\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)', text_lower)
    if match:
        return ('atirar', {'linha': int(match.group(1)), 'coluna': int(match.group(2))})

    # Tenta extrair JSON-like {"name": "atirar", ...}
    match = re.search(r'"linha"\s*:\s*(\d+).*?"coluna"\s*:\s*(\d+)', text)
    if match:
        return ('atirar', {'linha': int(match.group(1)), 'coluna': int(match.group(2))})
    match = re.search(r'"coluna"\s*:\s*(\d+).*?"linha"\s*:\s*(\d+)', text)
    if match:
        return ('atirar', {'linha': int(match.group(2)), 'coluna': int(match.group(1))})

    # Tenta extrair mover("direcao") ou mover(direcao)
    match = re.search(r'mover\s*\(\s*["\']?(cima|baixo|esquerda|direita)["\']?\s*\)', text_lower)
    if match:
        return ('mover', {'direcao': match.group(1)})

    # Tenta extrair direção do JSON-like
    match = re.search(r'"direcao"\s*:\s*"(cima|baixo|esquerda|direita)"', text_lower)
    if match:
        return ('mover', {'direcao': match.group(1)})

    # Tenta detectar menção de mover + direção no texto (ex: "vou mover para baixo")
    for direcao in ['cima', 'baixo', 'esquerda', 'direita']:
        if 'mover' in text_lower and direcao in text_lower:
            return ('mover', {'direcao': direcao})

    # Detecta direção isolada após "AÇÃO:" (ex: "AÇÃO: direita", "AÇÃO: cima")
    match = re.search(r'a[çc][ãa]o\s*:\s*(cima|baixo|esquerda|direita)', text_lower)
    if match:
        return ('mover', {'direcao': match.group(1)})

    # Tenta detectar parar
    if re.search(r'parar\s*\(', text_lower) or re.search(r'a[çc][ãa]o\s*:\s*parar', text_lower):
        return ('parar', {})

    return None


def execute_parsed_action(engine, action_name, action_args):
    """Executa uma ação parseada do texto."""
    if action_name == 'mover':
        direcao = action_args.get('direcao', 'cima')
        vec = DIRECOES.get(direcao, pygame.math.Vector2(0, -1))
        engine.execute_turn("MOVE", vec)
        return f"MOVER {direcao.upper()}"
    elif action_name == 'atirar':
        linha = int(action_args.get('linha', 0))
        coluna = int(action_args.get('coluna', 0))
        alvo_x = coluna * CELL_W + CELL_W / 2
        alvo_y = linha * CELL_H + CELL_H / 2
        alvo = pygame.math.Vector2(alvo_x, alvo_y)
        engine.execute_turn("SHOOT", alvo)
        return f"ATIRAR na célula ({linha}, {coluna})"
    elif action_name == 'parar':
        engine.execute_turn("STOP")
        return "PARAR"
    return "AÇÃO DESCONHECIDA"


def run_llm_game():
    """Loop principal com threading: pygame roda fluido enquanto LLM pensa."""
    client = Client(host=DEFAULT_OLLAMA_URL)
    engine = GameEngine()

    system_prompt = SYSTEM_PROMPT.format(
        grid=GRID_N,
        cell_w=CELL_W,
        cell_h=CELL_H,
        hp_max=engine.player.hp,
        max_idx=GRID_N - 1,
    )

    messages = [{"role": "system", "content": system_prompt}]
    turn_number = 0
    prev_events = []

    # Estado da thread LLM
    llm_thinking = False
    llm_result = None  # Guarda o resultado da LLM quando pronto
    llm_lock = threading.Lock()

    print("\n" + "=" * 50)
    print("  LLM PLAYER - TOP-DOWN SHOOTER TÁTICO")
    print("=" * 50)
    print(f"Modelo: {MODEL}")
    print(f"Grid: {GRID_N}x{GRID_N}")
    print("=" * 50 + "\n")

    def llm_think(turn_msg):
        """Roda em thread separada para não travar o pygame."""
        nonlocal llm_result
        messages.append({"role": "user", "content": turn_msg})
        try:
            response = client.chat(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
            )
            with llm_lock:
                llm_result = response
        except Exception as e:
            print(f"\n❌ Erro LLM: {e}")
            with llm_lock:
                llm_result = "ERROR"

    running = True
    while running:
        engine.clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                    break
                if engine.state == "GAME_OVER" and event.key == pygame.K_r:
                    engine.reset_game()
                    messages = [{"role": "system", "content": system_prompt}]
                    turn_number = 0
                    prev_events = []
                    llm_thinking = False
                    llm_result = None

        if not running:
            break

        # Renderiza sempre
        engine.render()

        # Simulação de física
        if engine.state == "SIMULATING":
            engine.update_physics()
            # Quando a simulação termina, salva os eventos para feedback
            if engine.state != "SIMULATING":
                prev_events = list(engine.turn_events)
            continue

        # Game over - só renderiza
        if engine.state == "GAME_OVER":
            continue

        # INPUT - dispara a LLM em thread se ainda não está pensando
        if engine.state == "INPUT" and not llm_thinking:
            turn_number += 1

            turn_msg = build_turn_message(engine, turn_number, prev_events)
            print(f"\n{'─' * 50}")
            print(f"  TURNO {turn_number}")
            print(f"{'─' * 50}")
            print(turn_msg)
            print("\n🤖 LLM pensando...")

            # Atualiza mensagem na tela
            engine.message = f"LLM pensando... (Turno {turn_number})"

            llm_thinking = True
            llm_result = None
            thread = threading.Thread(target=llm_think, args=(turn_msg,), daemon=True)
            thread.start()

        # Checa se a LLM terminou de pensar
        if llm_thinking:
            with llm_lock:
                result = llm_result

            if result is not None:
                llm_thinking = False

                if result == "ERROR":
                    print("Executando ação padrão: PARAR")
                    engine.execute_turn("STOP")
                    continue

                response = result

                # Mostra comentário da LLM
                if response.message.content:
                    print(f"\n💬 LLM: {response.message.content}")

                # Processa tool call
                if response.message.tool_calls:
                    tool_call = response.message.tool_calls[0]
                    action_desc = process_llm_action(engine, tool_call)
                    print(f"⚡ AÇÃO: {action_desc}")

                    messages.append(response.message)
                    messages.append({
                        'role': 'tool',
                        'content': f'Ação executada: {action_desc}',
                        'name': tool_call.function.name,
                    })
                else:
                    # Fallback: tenta parsear a ação do texto
                    parsed = parse_action_from_text(response.message.content or "")
                    if parsed:
                        action_name, action_args = parsed
                        action_desc = execute_parsed_action(engine, action_name, action_args)
                        print(f"⚡ AÇÃO (parseada do texto): {action_desc}")
                        messages.append({"role": "assistant", "content": response.message.content})
                    else:
                        print("\n⚠️  LLM não escolheu ação. Executando PARAR.")
                        engine.execute_turn("STOP")
                        messages.append({
                            "role": "assistant",
                            "content": response.message.content or "..."
                        })

                # Gerencia tamanho do histórico
                if len(messages) > 62:
                    messages = [messages[0]] + messages[-40:]

    pygame.quit()
    print("\n🏁 Jogo encerrado!")


if __name__ == "__main__":
    run_llm_game()
