"""In-memory live game engine. One gunicorn worker owns all live games;
finished games are written to the database."""
import random
import threading
import time

MAX_POINTS = 1000


class Player:
    def __init__(self, sid, name):
        self.sid, self.name = sid, name
        self.score = 0
        self.correct = 0
        self.answer = None          # choice for the current question
        self.answer_time = None
        self.last_points = 0


class LiveGame:
    def __init__(self, pin, quiz_id, title, questions, host_id):
        self.pin, self.quiz_id, self.title, self.host_id = pin, quiz_id, title, host_id
        self.questions = questions  # list of dicts: text, options, correct, time_limit
        self.players = {}           # sid -> Player
        self.index = -1
        self.state = "lobby"        # lobby | question | reveal | finished
        self.started_at = None
        self.lock = threading.Lock()
        self.db_game_id = None

    # ------------------------------------------------------------- players
    def add_player(self, sid, name):
        name = (name or "").strip()[:20]
        if not name:
            return "Please enter a nickname"
        if self.state == "finished":
            return "This game has finished"
        if any(p.name.lower() == name.lower() for p in self.players.values()):
            return "That nickname is taken"
        self.players[sid] = Player(sid, name)
        return None

    def remove_player(self, sid):
        return self.players.pop(sid, None)

    # ------------------------------------------------------------- flow
    @property
    def current(self):
        return self.questions[self.index] if 0 <= self.index < len(self.questions) else None

    def next_question(self):
        with self.lock:
            self.index += 1
            if self.index >= len(self.questions):
                self.state = "finished"
                return None
            for p in self.players.values():
                p.answer, p.answer_time, p.last_points = None, None, 0
            self.state = "question"
            self.started_at = time.monotonic()
            return self.current

    def submit(self, sid, choice):
        with self.lock:
            p = self.players.get(sid)
            q = self.current
            if not p or not q or self.state != "question" or p.answer is not None:
                return False
            if not isinstance(choice, int) or not 0 <= choice < len(q["options"]):
                return False
            elapsed = time.monotonic() - self.started_at
            if elapsed > q["time_limit"] + 0.5:
                return False
            p.answer, p.answer_time = choice, elapsed
            return True

    def all_answered(self):
        return self.players and all(p.answer is not None for p in self.players.values())

    def reveal(self):
        """Score the current question. Faster correct answers earn more points."""
        with self.lock:
            if self.state != "question":
                return None
            q = self.current
            self.state = "reveal"
            dist = [0] * len(q["options"])
            for p in self.players.values():
                if p.answer is None:
                    continue
                dist[p.answer] += 1
                if p.answer == q["correct"]:
                    speed = max(0.0, 1 - p.answer_time / q["time_limit"])
                    p.last_points = int(MAX_POINTS / 2 + MAX_POINTS / 2 * speed)
                    p.score += p.last_points
                    p.correct += 1
            return {"correct": q["correct"], "distribution": dist, "leaderboard": self.leaderboard(),
                    "is_last": self.index == len(self.questions) - 1}

    def leaderboard(self, n=None):
        ranked = sorted(self.players.values(), key=lambda p: (-p.score, p.name.lower()))
        rows = [{"rank": i + 1, "name": p.name, "score": p.score, "correct": p.correct, "last": p.last_points}
                for i, p in enumerate(ranked)]
        return rows[:n] if n else rows

    def public_question(self):
        q = self.current
        return {"index": self.index, "total": len(self.questions), "text": q["text"],
                "options": q["options"], "time_limit": q["time_limit"]}


class GameRegistry:
    def __init__(self):
        self.games = {}
        self.lock = threading.Lock()

    def create(self, quiz_id, title, questions, host_id):
        with self.lock:
            while True:
                pin = f"{random.SystemRandom().randint(0, 999999):06d}"
                if pin not in self.games:
                    break
            g = LiveGame(pin, quiz_id, title, questions, host_id)
            self.games[pin] = g
            return g

    def get(self, pin):
        return self.games.get((pin or "").strip())

    def find_by_sid(self, sid):
        for g in self.games.values():
            if sid in g.players:
                return g
        return None

    def active_count(self):
        return sum(1 for g in self.games.values() if g.state != "finished")
