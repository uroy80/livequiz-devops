"""Database models (PostgreSQL in production, SQLite for tests)."""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    pw_hash = db.Column(db.String(256), nullable=False)
    created = db.Column(db.DateTime(timezone=True), default=now)
    quizzes = db.relationship("Quiz", backref="owner", lazy=True)

    def set_password(self, pw):
        self.pw_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.pw_hash, pw)


class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created = db.Column(db.DateTime(timezone=True), default=now)
    questions = db.relationship("Question", backref="quiz", lazy=True, order_by="Question.position",
                                cascade="all, delete-orphan")
    games = db.relationship("Game", backref="quiz", lazy=True, cascade="all, delete-orphan")


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id"), nullable=False)
    position = db.Column(db.Integer, default=0)
    text = db.Column(db.String(300), nullable=False)
    options = db.Column(db.JSON, nullable=False)          # list of 2-4 strings
    correct = db.Column(db.Integer, nullable=False)        # index into options
    time_limit = db.Column(db.Integer, default=20)         # seconds


class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id"), nullable=False)
    pin = db.Column(db.String(6), nullable=False)
    started = db.Column(db.DateTime(timezone=True), default=now)
    ended = db.Column(db.DateTime(timezone=True))
    player_count = db.Column(db.Integer, default=0)
    results = db.relationship("Result", backref="game", lazy=True, order_by="Result.rank",
                              cascade="all, delete-orphan")


class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    nickname = db.Column(db.String(24), nullable=False)
    score = db.Column(db.Integer, default=0)
    correct_count = db.Column(db.Integer, default=0)
    rank = db.Column(db.Integer, default=0)
