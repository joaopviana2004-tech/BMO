import pygame
import random
import math
import heapq

# ==========================================
# CONFIGURAÇÕES GERAIS E VARIÁVEIS
# ==========================================
WIDTH, HEIGHT = 800, 800
FPS = 60
FRICTION = 0.8
MOVE_FORCE = 15.0
PROJECTILE_SPEED = 20.0

# Variáveis das Entidades
NUM_BOTS = 4
PLAYER_HP = 3
BOT_HP = 1

# Configurações do Grid Principal (Level Design e A*)
GRID_N = 20               # Define a malha (ex: 6x6 = 36 células)
OBSTACLE_PROB = 0.1       # Probabilidade de cada célula ter um obstáculo
DEBUG_MODE = True          # Desenha as linhas do grid para debug

CELL_W = WIDTH // GRID_N
CELL_H = HEIGHT // GRID_N

# Cores
BG_COLOR = (30, 30, 30)
PLAYER_COLOR = (50, 150, 255)
BOT_COLOR = (255, 50, 50)
OBSTACLE_COLOR = (120, 120, 120)
TEXT_COLOR = (255, 255, 255)
GRID_LINE_COLOR = (50, 200, 50)

# ==========================================
# FUNÇÕES MATEMÁTICAS E DE COLISÃO
# ==========================================
def point_to_segment_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0: return math.hypot(px - x1, py - y1)
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x, proj_y = x1 + t * dx, y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)

def line_intersects_segment(p1, p2, p3, p4):
    def ccw(A, B, C): return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)

# ==========================================
# CLASSES DE ENTIDADE E OBJETOS
# ==========================================
class Obstacle:
    def __init__(self, shape_type, points):
        self.shape_type = shape_type
        self.points = points
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        self.rect = pygame.Rect(min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys))

    def collides_with_circle(self, cx, cy, radius):
        if not self.rect.inflate(radius*2, radius*2).collidepoint(cx, cy): return False
        n = len(self.points)
        for i in range(n):
            p1, p2 = self.points[i], self.points[(i+1)%n]
            if point_to_segment_dist(cx, cy, p1[0], p1[1], p2[0], p2[1]) < radius:
                return True
        return False

    def blocks_line_of_sight(self, start, end):
        n = len(self.points)
        for i in range(n):
            if line_intersects_segment(start, end, self.points[i], self.points[(i+1)%n]): return True
        return False

    def draw(self, surface):
        if self.shape_type == 'rect': pygame.draw.rect(surface, OBSTACLE_COLOR, self.rect)
        else: pygame.draw.polygon(surface, OBSTACLE_COLOR, self.points)

class Entity:
    def __init__(self, x, y, radius, hp, color):
        self.pos = pygame.math.Vector2(x, y)
        self.vel = pygame.math.Vector2(0, 0)
        self.radius = radius
        self.hp = hp
        self.color = color
        self.is_dead = False
        self.reload_cooldown = 0

    def update_physics(self):
        self.pos += self.vel
        self.vel *= FRICTION
        if self.vel.length() < 0.5: self.vel.update(0, 0)

        if self.pos.x - self.radius < 0: self.pos.x, self.vel.x = self.radius, self.vel.x * -1
        elif self.pos.x + self.radius > WIDTH: self.pos.x, self.vel.x = WIDTH - self.radius, self.vel.x * -1
        if self.pos.y - self.radius < 0: self.pos.y, self.vel.y = self.radius, self.vel.y * -1
        elif self.pos.y + self.radius > HEIGHT: self.pos.y, self.vel.y = HEIGHT - self.radius, self.vel.y * -1

    def draw(self, surface):
        pygame.draw.circle(surface, self.color, (int(self.pos.x), int(self.pos.y)), self.radius)

class Projectile:
    def __init__(self, pos, direction, owner):
        self.pos = pygame.math.Vector2(pos)
        self.vel = direction.normalize() * PROJECTILE_SPEED if direction.length() > 0 else pygame.math.Vector2(0,0)
        self.radius = 5
        self.is_dead = False
        self.hit_target = False
        self.owner = owner

    def update_physics(self):
        self.pos += self.vel
        if not (0 <= self.pos.x <= WIDTH and 0 <= self.pos.y <= HEIGHT): self.is_dead = True

    def draw(self, surface):
        pygame.draw.circle(surface, (255, 255, 0), (int(self.pos.x), int(self.pos.y)), self.radius)

# ==========================================
# MOTOR DO JOGO E IA
# ==========================================
class GameEngine:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Top-Down Tático - State Map")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 24)
        self.turn_events = []
        self.reset_game()

    def generate_obstacles(self):
        self.obstacles = []
        self.map_grid = [[0 for _ in range(GRID_N)] for _ in range(GRID_N)]
        
        max_obstacles = (GRID_N * GRID_N) - (NUM_BOTS + 1)
        
        for r in range(GRID_N):
            for c in range(GRID_N):
                if random.random() < OBSTACLE_PROB and len(self.obstacles) < max_obstacles:
                    self.map_grid[r][c] = 1 
                    tipo = random.choice(['rect', 'triangle']) 
                    base_x, base_y = c * CELL_W, r * CELL_H
                    
                    if tipo == 'rect':
                        pts = [(base_x, base_y), (base_x+CELL_W, base_y), (base_x+CELL_W, base_y+CELL_H), (base_x, base_y+CELL_H)]
                        self.obstacles.append(Obstacle('rect', pts))
                    else:
                        pts = [(base_x, base_y+CELL_H), (base_x + CELL_W/2, base_y), (base_x+CELL_W, base_y+CELL_H)]
                        self.obstacles.append(Obstacle('polygon', pts))

    def reset_game(self):
        self.turn_events = []  # Log de eventos do turno para feedback
        self.generate_obstacles()
        self.bots = []
        
        empty_cells = [(c, r) for r in range(GRID_N) for c in range(GRID_N) if self.map_grid[r][c] == 0]
        random.shuffle(empty_cells)
        
        if empty_cells:
            pc, pr = empty_cells.pop()
            self.player = Entity(pc * CELL_W + CELL_W/2, pr * CELL_H + CELL_H/2, 15, PLAYER_HP, PLAYER_COLOR)
                
        for i in range(NUM_BOTS):
            if empty_cells:
                bc, br = empty_cells.pop()
                bot = Entity(bc * CELL_W + CELL_W/2, br * CELL_H + CELL_H/2, 15, BOT_HP, BOT_COLOR)
                bot.id = i
                self.bots.append(bot)

        self.projectiles = []
        self.state = "INPUT"
        self.message = "Seu Turno! WASD: Andar | Espaço: Parar | Clique: Atirar"
        
        # Printa o mapa inicial no terminal
        self.print_state_map()

    # ==========================================
    # MAPEAMENTO DE ESTADO (NOVA FUNÇÃO)
    # ==========================================
    def get_state_map(self):
        """Gera uma matriz de strings representando o estado atual do jogo."""
        state_grid = []
        
        # Passo 1: Preenche com vazios (-) e obstáculos (+)
        for r in range(GRID_N):
            row = []
            for c in range(GRID_N):
                if self.map_grid[r][c] == 1:
                    row.append('+')
                else:
                    row.append('-')
            state_grid.append(row)
            
        # Passo 2: Adiciona os Bots (b)
        for bot in self.bots:
            bc = int(bot.pos.x // CELL_W)
            br = int(bot.pos.y // CELL_H)
            if 0 <= bc < GRID_N and 0 <= br < GRID_N:
                state_grid[br][bc] = 'b'
                
        # Passo 3: Adiciona o Player (p)
        if hasattr(self, 'player') and not self.player.is_dead:
            pc = int(self.player.pos.x // CELL_W)
            pr = int(self.player.pos.y // CELL_H)
            if 0 <= pc < GRID_N and 0 <= pr < GRID_N:
                state_grid[pr][pc] = 'p'
                
        return state_grid

    def print_state_map(self):
        """Imprime o mapa de estado no CMD de forma formatada."""
        print("\n=== MAPA DE ESTADO (RODADA) ===")
        grid = self.get_state_map()
        for row in grid:
            print("  ".join(row))
        print("===============================\n")

    # ==========================================
    # LÓGICA DO JOGO E A*
    # ==========================================
    def a_star(self, start_pos, goal_pos):
        start_c, start_r = int(start_pos.x // CELL_W), int(start_pos.y // CELL_H)
        goal_c, goal_r = int(goal_pos.x // CELL_W), int(goal_pos.y // CELL_H)
        
        start_c, start_r = max(0, min(GRID_N-1, start_c)), max(0, min(GRID_N-1, start_r))
        goal_c, goal_r = max(0, min(GRID_N-1, goal_c)), max(0, min(GRID_N-1, goal_r))

        if self.map_grid[goal_r][goal_c] == 1: return None
            
        open_set = []
        heapq.heappush(open_set, (0, (start_c, start_r)))
        came_from, g_score = {}, {(start_c, start_r): 0}
        
        while open_set:
            _, current = heapq.heappop(open_set)
            
            if current == (goal_c, goal_r):
                path = []
                while current in came_from:
                    path.append(current)
                    current = came_from[current]
                path.append((start_c, start_r))
                return path[::-1]
                
            cc, cr = current
            neighbors = [(cc+1, cr), (cc-1, cr), (cc, cr+1), (cc, cr-1), (cc+1, cr+1), (cc-1, cr-1), (cc+1, cr-1), (cc-1, cr+1)]
            
            for nc, nr in neighbors:
                if 0 <= nc < GRID_N and 0 <= nr < GRID_N and self.map_grid[nr][nc] == 0:
                    if nc != cc and nr != cr:
                        if self.map_grid[cr][nc] == 1 or self.map_grid[nr][cc] == 1: continue
                            
                    tentative_g = g_score[current] + (1.41 if nc != cc and nr != cr else 1.0)
                    if (nc, nr) not in g_score or tentative_g < g_score[(nc, nr)]:
                        came_from[(nc, nr)] = current
                        g_score[(nc, nr)] = tentative_g
                        f_score = tentative_g + math.hypot(goal_c - nc, goal_r - nr)
                        heapq.heappush(open_set, (f_score, (nc, nr)))
        return None

    def has_line_of_sight(self, start_pos, end_pos):
        return not any(obs.blocks_line_of_sight((start_pos.x, start_pos.y), (end_pos.x, end_pos.y)) for obs in self.obstacles)

    def check_safe_direction(self, pos, direcao, radius, look_ahead=50):
        if direcao.length() == 0: return True
        future_pos = pos + direcao.normalize() * look_ahead
        if future_pos.x - radius < 0 or future_pos.x + radius > WIDTH or future_pos.y - radius < 0 or future_pos.y + radius > HEIGHT: return False
        if any(obs.collides_with_circle(future_pos.x, future_pos.y, radius + 10) for obs in self.obstacles): return False
        return True

    def andar_para(self, entidade, direcao):
        if direcao.length() > 0: entidade.vel += direcao.normalize() * MOVE_FORCE

    def atirar(self, entidade, alvo_pos):
        direcao = alvo_pos - entidade.pos
        self.projectiles.append(Projectile(entidade.pos, direcao, owner=entidade))

    def process_bot_ai(self):
        for bot in self.bots:
            if bot.pos.distance_to(self.player.pos) < 450 and bot.reload_cooldown == 0 and self.has_line_of_sight(bot.pos, self.player.pos):
                if random.random() < 0.8:
                    erro = pygame.math.Vector2(random.randint(-20, 20), random.randint(-20, 20))
                    self.atirar(bot, self.player.pos + erro)
                    continue

            offset = pygame.math.Vector2(random.choice([-60, 60]), random.choice([-60, 60])) if bot.id % 2 != 0 else pygame.math.Vector2(0, 0)
            alvo_movimento = self.player.pos + offset
            caminho = self.a_star(bot.pos, alvo_movimento)
            
            if caminho and len(caminho) > 0:
                if len(caminho) == 1:
                    direcao = alvo_movimento - bot.pos
                else:
                    prox_c, prox_r = caminho[1]
                    prox_no = pygame.math.Vector2(prox_c * CELL_W + CELL_W/2, prox_r * CELL_H + CELL_H/2)
                    direcao = prox_no - bot.pos
                
                if self.check_safe_direction(bot.pos, direcao, bot.radius, look_ahead=55): self.andar_para(bot, direcao)
                else:
                    desvio = direcao.rotate(45)
                    if self.check_safe_direction(bot.pos, desvio, bot.radius, look_ahead=40): self.andar_para(bot, desvio)
                    else: bot.vel.update(0, 0)
            else:
                if random.random() < 0.5:
                    movimento_seguro = False
                    for _ in range(4):
                        dir_aleatoria = pygame.math.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
                        if self.check_safe_direction(bot.pos, dir_aleatoria, bot.radius, look_ahead=50):
                            self.andar_para(bot, dir_aleatoria)
                            movimento_seguro = True
                            break
                    if not movimento_seguro: bot.vel.update(0, 0)
                else: bot.vel.update(0, 0)

    def execute_turn(self, player_action, target_vec=None):
        self.turn_events = []  # Limpa eventos do turno anterior
        self._pre_turn_hp = self.player.hp if hasattr(self, 'player') else 0
        self._pre_turn_bots = {bot.id: bot.hp for bot in self.bots}

        if player_action == "MOVE": self.andar_para(self.player, target_vec)
        elif player_action == "SHOOT":
            if hasattr(self, 'player') and self.player.reload_cooldown > 0:
                self.message = "Arma recarregando! Mova-se ou Pare."
                self.turn_events.append("ARMA_RECARREGANDO: Você tentou atirar mas a arma está em cooldown.")
                return
            self.atirar(self.player, target_vec)
        elif player_action == "STOP":
            if hasattr(self, 'player'): self.player.vel.update(0, 0)

        self.process_bot_ai()
        self.state = "SIMULATING"
        self.sim_frames = 0
        self.message = "Simulando Ações..."

    def end_turn(self):
        if hasattr(self, 'player') and self.player.reload_cooldown > 0: self.player.reload_cooldown -= 1
        for bot in self.bots:
            if bot.reload_cooldown > 0: bot.reload_cooldown -= 1

        self.state = "INPUT"
        self.message = "Seu Turno! WASD: Andar | Espaço: Parar | Clique: Atirar"
        
        if not hasattr(self, 'player') or self.player.is_dead or self.player.hp <= 0:
            self.state = "GAME_OVER"
            self.message = "GAME OVER! (Pressione R para reiniciar)"
        elif len(self.bots) == 0:
            self.state = "GAME_OVER"
            self.message = "VITÓRIA! (Pressione R para reiniciar)"
            
        # Imprime o mapa de estado no CMD assim que o turno acaba
        self.print_state_map()

    def handle_collisions(self):
        todas_entidades = self.bots.copy()
        if hasattr(self, 'player') and not self.player.is_dead: todas_entidades.append(self.player)

        for ent in todas_entidades:
            for obs in self.obstacles:
                if obs.collides_with_circle(ent.pos.x, ent.pos.y, ent.radius):
                    ent.hp -= 1
                    if ent == self.player:
                        self.turn_events.append(f"COLISÃO_OBSTÁCULO: Você colidiu com um obstáculo! HP restante: {ent.hp}")
                    else:
                        bc, br = int(ent.pos.x // CELL_W), int(ent.pos.y // CELL_H)
                        self.turn_events.append(f"BOT_COLISÃO: Bot (linha={br}, coluna={bc}) colidiu com obstáculo.")
                    if ent.hp <= 0: ent.is_dead = True
                    dir_fuga = ent.pos - pygame.math.Vector2(obs.rect.center)
                    if dir_fuga.length() > 0: ent.vel = dir_fuga.normalize() * (MOVE_FORCE * 0.8)
                    ent.pos += ent.vel

        for proj in self.projectiles:
            if proj.is_dead: continue
            if any(obs.collides_with_circle(proj.pos.x, proj.pos.y, proj.radius) for obs in self.obstacles):
                proj.is_dead = True
                proj.owner.reload_cooldown = 2
                if proj.owner == self.player:
                    self.turn_events.append("TIRO_BLOQUEADO: Seu projétil atingiu um obstáculo e foi destruído. Arma em cooldown (2 turnos).")
                else:
                    self.turn_events.append("TIRO_INIMIGO_BLOQUEADO: Projétil de um bot atingiu um obstáculo.")

            for ent in todas_entidades:
                if ent.is_dead or ent == proj.owner: continue
                if proj.pos.distance_to(ent.pos) < proj.radius + ent.radius:
                    ent.hp -= 1
                    if proj.owner == self.player and ent != self.player:
                        bc, br = int(ent.pos.x // CELL_W), int(ent.pos.y // CELL_H)
                        if ent.hp <= 0:
                            self.turn_events.append(f"KILL: Você MATOU o bot na célula (linha={br}, coluna={bc})!")
                        else:
                            self.turn_events.append(f"ACERTO: Seu tiro ACERTOU o bot na célula (linha={br}, coluna={bc})! HP restante do bot: {ent.hp}")
                    elif ent == self.player:
                        self.turn_events.append(f"DANO_RECEBIDO: Você levou um tiro de um bot! Seu HP: {ent.hp}")
                    if ent.hp <= 0: ent.is_dead = True
                    proj.is_dead = True
                    proj.hit_target = True
                    proj.owner.reload_cooldown = 0

        for proj in self.projectiles:
            if proj.is_dead and not proj.hit_target and proj.owner.reload_cooldown == 0:
                proj.owner.reload_cooldown = 2
                if proj.owner == self.player:
                    self.turn_events.append("TIRO_ERROU: Seu projétil saiu do mapa sem acertar nada. Arma em cooldown (2 turnos).")

        self.bots = [b for b in self.bots if not b.is_dead]
        self.projectiles = [p for p in self.projectiles if not p.is_dead]

    def update_physics(self):
        if hasattr(self, 'player'): self.player.update_physics()
        for bot in self.bots: bot.update_physics()
        for proj in self.projectiles: proj.update_physics()

        self.handle_collisions()

        self.sim_frames += 1

        entidades_vivas = self.bots.copy()
        if hasattr(self, 'player') and not self.player.is_dead: entidades_vivas.append(self.player)

        settled = all(e.vel.length() < 1.0 for e in entidades_vivas) and len(self.projectiles) == 0
        timed_out = self.sim_frames > 300  # ~5 segundos a 60fps

        if timed_out:
            # Força parar todas as entidades presas
            for e in entidades_vivas:
                e.vel.update(0, 0)
            self.projectiles.clear()

        if settled or timed_out:
            self.end_turn()

    def draw_ui(self):
        hp = self.player.hp if hasattr(self, 'player') else 0
        cooldown = self.player.reload_cooldown if hasattr(self, 'player') else 0
        
        self.screen.blit(self.font.render(f"HP: {hp}", True, TEXT_COLOR), (10, 10))
        self.screen.blit(self.font.render(f"Bots: {len(self.bots)}", True, TEXT_COLOR), (10, 35))
        
        status = "PRONTO" if cooldown == 0 else f"RECARREGA ({cooldown})"
        self.screen.blit(self.font.render(f"Arma: {status}", True, (50, 255, 50) if cooldown == 0 else (255, 100, 100)), (10, 60))
        self.screen.blit(self.font.render(self.message, True, (255, 255, 0)), (10, HEIGHT - 30))

    def render(self):
        self.screen.fill(BG_COLOR)
        
        if DEBUG_MODE:
            for x in range(0, WIDTH, CELL_W): pygame.draw.line(self.screen, GRID_LINE_COLOR, (x, 0), (x, HEIGHT), 1)
            for y in range(0, HEIGHT, CELL_H): pygame.draw.line(self.screen, GRID_LINE_COLOR, (0, y), (WIDTH, y), 1)

        for obs in self.obstacles: obs.draw(self.screen)
        for bot in self.bots: bot.draw(self.screen)
        for proj in self.projectiles: proj.draw(self.screen)
        if hasattr(self, 'player') and not self.player.is_dead: self.player.draw(self.screen)
        self.draw_ui()
        pygame.display.flip()

    def run(self):
        running = True
        while running:
            self.clock.tick(FPS)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                if event.type == pygame.KEYDOWN:
                    if self.state == "GAME_OVER" and event.key == pygame.K_r:
                        self.reset_game()
                        continue
                    if self.state == "INPUT":
                        direcao = pygame.math.Vector2(0, 0)
                        if event.key in (pygame.K_w, pygame.K_UP): direcao.y = -1
                        elif event.key in (pygame.K_s, pygame.K_DOWN): direcao.y = 1
                        elif event.key in (pygame.K_a, pygame.K_LEFT): direcao.x = -1
                        elif event.key in (pygame.K_d, pygame.K_RIGHT): direcao.x = 1
                        
                        if direcao.length() > 0: self.execute_turn("MOVE", direcao)
                        elif event.key == pygame.K_SPACE: self.execute_turn("STOP")

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.state == "INPUT":
                        self.execute_turn("SHOOT", pygame.math.Vector2(pygame.mouse.get_pos()))

            if self.state == "SIMULATING": self.update_physics()
            self.render()
        pygame.quit()

if __name__ == "__main__":
    game = GameEngine()
    game.run()