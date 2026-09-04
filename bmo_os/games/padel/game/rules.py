"""Placar. Duas formas de contar, com a mesma interface:

Match (padel oficial):
- pontos 0 / 15 / 30 / 40, deuce e vantagem (AD)
- game: 4 pontos com 2 de diferenca
- set: `games_per_set` games com 2 de diferenca; tie-break em N x N (7 pontos, 2 de diferenca)
- o time sacador alterna a cada game; no tie-break o 1o ponto e do sacador da vez e depois alterna a cada 2
- troca de lado nos games impares (1, 3, 5, ...) e a cada 6 pontos no tie-break
- dupla falta = ponto do recebedor

ArcadeScore (limite de pontos, GAMEPLAY.md):
- primeiro a chegar em `limit` pontos vence; saque alterna de time a cada 2 pontos

`server` e sempre o INDICE DO TIME que saca.
"""

POINT_NAMES = ["0", "15", "30", "40"]


class _Base:
    def __init__(self, first_server=0):
        self.points = [0, 0]
        self.games = [0, 0]
        self.sets = [0, 0]
        self.history = []
        self.server = first_server
        self.faults = 0
        self.finished = False
        self.winner = None
        self.change_ends = False
        self.tiebreak = False
        self.rally = 0
        self.longest_rally = 0

    def serve_side(self):
        """'deuce' (lado direito do sacador) nos pontos pares, 'ad' nos impares."""
        return "deuce" if sum(self.points) % 2 == 0 else "ad"

    def fault(self):
        """Registra uma falta de saque. Devolve True se foi dupla falta."""
        self.faults += 1
        if self.faults >= 2:
            self.faults = 0
            return True
        return False

    def _start_point(self):
        self.faults = 0
        self.longest_rally = max(self.longest_rally, self.rally)
        self.rally = 0

    def leader(self):
        """Quem esta na frente (para o fim por tempo). None se empate."""
        a = (self.sets[0], self.games[0], self.points[0])
        b = (self.sets[1], self.games[1], self.points[1])
        if a == b:
            return None
        return 0 if a > b else 1

    def force_finish(self, winner):
        self.finished = True
        self.winner = winner

    def is_deuce(self):
        return False


class Match(_Base):
    kind = "padel"

    def __init__(self, games_per_set=6, sets_to_win=1, first_server=0):
        super().__init__(first_server)
        self.gps = games_per_set
        self.sets_to_win = sets_to_win
        self.tb_first = None

    def score_text(self, i):
        if self.tiebreak:
            return str(self.points[i])
        p, q = self.points[i], self.points[1 - i]
        if p >= 3 and q >= 3:
            if p == q:
                return "40"
            return "AD" if p > q else "40"
        return POINT_NAMES[min(p, 3)]

    def meta_text(self):
        if self.tiebreak:
            return f"TB {self.games[0]}-{self.games[1]}"
        return f"GAMES {self.games[0]}-{self.games[1]}"

    def is_deuce(self):
        return not self.tiebreak and self.points[0] == self.points[1] >= 3

    def serve_turn(self):
        """Chave que muda sempre que comeca uma nova 'vez de saque' (um game, ou 2 pontos no tie-break)."""
        if self.tiebreak:
            return ("tb", (sum(self.points) + 1) // 2)
        return ("g", self.games[0] + self.games[1])

    def point_won(self, i):
        self._start_point()
        j = 1 - i
        self.points[i] += 1
        if self.tiebreak:
            if self.points[i] >= 7 and self.points[i] - self.points[j] >= 2:
                return self._game_won(i)
            total = sum(self.points)
            self.server = self.tb_first if ((total + 1) // 2) % 2 == 0 else 1 - self.tb_first
            if total % 6 == 0:
                self.change_ends = True
            return "point"
        if self.points[i] >= 4 and self.points[i] - self.points[j] >= 2:
            return self._game_won(i)
        return "point"

    def _game_won(self, i):
        j = 1 - i
        self.games[i] += 1
        self.points = [0, 0]
        was_tb = self.tiebreak
        if was_tb:
            self.tiebreak = False
            self.server = 1 - self.tb_first
        else:
            self.server = 1 - self.server
            if (self.games[0] + self.games[1]) % 2 == 1:
                self.change_ends = True
        if was_tb or (self.games[i] >= self.gps and self.games[i] - self.games[j] >= 2):
            return self._set_won(i)
        if self.games[0] == self.gps and self.games[1] == self.gps:
            self.tiebreak = True
            self.tb_first = self.server
        return "game"

    def _set_won(self, i):
        self.sets[i] += 1
        self.history.append(tuple(self.games))
        self.games = [0, 0]
        if self.sets[i] >= self.sets_to_win:
            self.finished = True
            self.winner = i
            return "match"
        return "set"


class ArcadeScore(_Base):
    kind = "pontos"

    def __init__(self, limit=11, first_server=0):
        super().__init__(first_server)
        self.limit = limit
        self.first = first_server

    def score_text(self, i):
        return str(self.points[i])

    def meta_text(self):
        return f"ATÉ {self.limit}"

    def serve_turn(self):
        return ("p", sum(self.points) // 2)

    def point_won(self, i):
        self._start_point()
        self.points[i] += 1
        if self.points[i] >= self.limit:
            self.finished = True
            self.winner = i
            return "match"
        total = sum(self.points)
        self.server = self.first if (total // 2) % 2 == 0 else 1 - self.first
        return "point"
