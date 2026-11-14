"""LiveQuiz - real-time classroom quiz platform.
Major Project: AWS + Git + Jenkins + Terraform + Ansible + Docker (one-click deployment).
"""
import io
import logging
import os
import secrets
import socket
import time
from functools import wraps

import qrcode
import qrcode.image.svg
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for)
from flask_socketio import SocketIO, emit, join_room
from sqlalchemy import func

from engine import GameRegistry
from models import Game, Question, Quiz, Result, User, db

VERSION = os.getenv("APP_VERSION", "dev")
BUILD = os.getenv("BUILD_NUMBER", "local")
COMMIT = os.getenv("GIT_COMMIT", "local")[:7]

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///livequiz.db"),
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
db.init_app(app)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins=None)
games = GameRegistry()

# Application event log -> stdout -> Docker awslogs driver -> CloudWatch Logs (/livequiz/app)
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [livequiz] %(message)s")
log = logging.getLogger("livequiz")


def client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr)


DEMO_QUIZ = ("DevOps & Cloud Challenge", "How well do you know the tools behind this very deployment?", [
    ("Which tool provisioned the AWS infrastructure running this quiz?", ["Ansible", "Terraform", "Jenkins", "Docker"], 1),
    ("Which AWS service hosts this application server?", ["S3", "Lambda", "EC2", "RDS"], 2),
    ("What did Ansible do in this pipeline?", ["Wrote the code", "Configured the server and deployed containers", "Created the VPC", "Ran unit tests"], 1),
    ("Which service stores the Docker image of this app?", ["Amazon ECR", "GitHub", "S3 Glacier", "CloudFront"], 0),
    ("What starts the whole deployment?", ["SSH into the server", "One click in Jenkins", "Uploading a ZIP file", "Restarting the laptop"], 1),
    ("Which protocol pushes these questions to your phone instantly?", ["FTP", "SMTP", "WebSocket", "DNS"], 2),
])


# ------------------------------------------------------------------ helpers
def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapper


@app.before_request
def load_user():
    uid = session.get("uid")
    g.user = db.session.get(User, uid) if uid else None
    if request.method == "POST" and not request.path.startswith("/socket.io"):
        token = request.form.get("csrf")
        if not token or not session.get("csrf") or not secrets.compare_digest(token, session["csrf"]):
            abort(400, "invalid form token")


@app.context_processor
def inject():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"csrf": session["csrf"], "user": g.get("user"), "version": VERSION, "build": BUILD,
            "commit": COMMIT, "server": socket.gethostname()}


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


def qr_svg(data):
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def seed():
    """Create tables, the admin host account and a demo quiz (idempotent)."""
    db.create_all()
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(username="admin")
        admin.set_password(os.getenv("ADMIN_PASSWORD") or "admin-change-me")
        db.session.add(admin)
        db.session.commit()
    if not Quiz.query.filter_by(title=DEMO_QUIZ[0]).first():
        q = Quiz(title=DEMO_QUIZ[0], description=DEMO_QUIZ[1], owner=admin)
        for i, (text, opts, correct) in enumerate(DEMO_QUIZ[2]):
            q.questions.append(Question(position=i, text=text, options=opts, correct=correct, time_limit=20))
        db.session.add(q)
        db.session.commit()


# ------------------------------------------------------------------ pages
@app.route("/")
def index():
    stats = {"quizzes": Quiz.query.count(), "games": Game.query.count(),
             "players": db.session.query(func.coalesce(func.sum(Game.player_count), 0)).scalar(),
             "live": games.active_count()}
    return render_template("index.html", stats=stats)


@app.route("/play", methods=["GET", "POST"])
def play():
    pin = request.values.get("pin", "")
    return render_template("play.html", pin=pin)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(username=request.form.get("username", "").strip()).first()
        if u and u.check_password(request.form.get("password", "")):
            session.clear()
            session["uid"] = u.id
            log.info("LOGIN ok user=%s ip=%s", u.username, client_ip())
            return redirect(request.args.get("next") or url_for("dashboard"))
        log.warning("LOGIN failed user=%s ip=%s", request.form.get("username", "")[:40], client_ip())
        flash("Wrong username or password")
    return render_template("login.html", mode="login")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        if not (3 <= len(name) <= 40) or len(pw) < 8:
            flash("Username 3-40 characters, password at least 8")
        elif User.query.filter_by(username=name).first():
            flash("That username is taken")
        else:
            u = User(username=name)
            u.set_password(pw)
            db.session.add(u)
            db.session.commit()
            session.clear()
            session["uid"] = u.id
            log.info("REGISTER new host user=%s ip=%s", u.username, client_ip())
            return redirect(url_for("dashboard"))
    return render_template("login.html", mode="register")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    quizzes = Quiz.query.filter_by(owner_id=g.user.id).order_by(Quiz.created.desc()).all()
    history = (Game.query.join(Quiz).filter(Quiz.owner_id == g.user.id).order_by(Game.started.desc()).limit(15).all())
    return render_template("dashboard.html", quizzes=quizzes, history=history)


@app.route("/quiz/new", methods=["GET", "POST"])
@login_required
def quiz_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:120]
        texts = request.form.getlist("q_text")
        questions = []
        for i, text in enumerate(texts):
            opts = [o.strip()[:80] for o in request.form.getlist(f"q{i}_opt") if o.strip()]
            try:
                correct = int(request.form.get(f"q{i}_correct", "0"))
                limit = max(5, min(120, int(request.form.get(f"q{i}_time", "20"))))
            except ValueError:
                correct, limit = -1, 20
            if text.strip() and 2 <= len(opts) <= 4 and 0 <= correct < len(opts):
                questions.append(Question(position=len(questions), text=text.strip()[:300], options=opts,
                                          correct=correct, time_limit=limit))
        if not title or not questions:
            flash("Give the quiz a title and at least one complete question (2-4 options, correct answer marked)")
            return render_template("quiz_new.html")
        quiz = Quiz(title=title, description=request.form.get("description", "")[:300], owner=g.user, questions=questions)
        log.info("QUIZ created title=%r questions=%d by=%s", title, len(questions), g.user.username)
        db.session.add(quiz)
        db.session.commit()
        flash(f"Quiz \"{title}\" saved with {len(questions)} questions")
        return redirect(url_for("dashboard"))
    return render_template("quiz_new.html")


@app.route("/quiz/<int:qid>/delete", methods=["POST"])
@login_required
def quiz_delete(qid):
    quiz = Quiz.query.filter_by(id=qid, owner_id=g.user.id).first_or_404()
    db.session.delete(quiz)
    db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/quiz/<int:qid>/host", methods=["POST"])
@login_required
def host(qid):
    quiz = Quiz.query.filter_by(id=qid, owner_id=g.user.id).first_or_404()
    qs = [{"text": q.text, "options": q.options, "correct": q.correct, "time_limit": q.time_limit} for q in quiz.questions]
    game = games.create(quiz.id, quiz.title, qs, g.user.id)
    log.info("GAME opened pin=%s quiz=%r host=%s", game.pin, quiz.title, g.user.username)
    return redirect(url_for("host_game", pin=game.pin))


@app.route("/host/<pin>")
@login_required
def host_game(pin):
    game = games.get(pin)
    if not game or game.host_id != g.user.id:
        abort(404)
    base = os.getenv("PUBLIC_URL") or request.host_url
    join_url = base.rstrip("/") + url_for("play", pin=pin)
    return render_template("host.html", game=game, join_url=join_url, qr=qr_svg(join_url))


@app.route("/game/<int:gid>")
@login_required
def game_report(gid):
    game = Game.query.join(Quiz).filter(Game.id == gid, Quiz.owner_id == g.user.id).first_or_404()
    return render_template("report.html", game=game)


@app.route("/healthz")
def healthz():
    db.session.execute(db.select(1))
    return jsonify(status="ok", version=VERSION, build=BUILD, commit=COMMIT, server=socket.gethostname())


@app.route("/api/stats")
def api_stats():
    top = (db.session.query(Result.nickname, func.max(Result.score).label("best"))
           .group_by(Result.nickname).order_by(func.max(Result.score).desc()).limit(5).all())
    return jsonify(quizzes=Quiz.query.count(), games=Game.query.count(), live_games=games.active_count(),
                   players=int(db.session.query(func.coalesce(func.sum(Game.player_count), 0)).scalar()),
                   hall_of_fame=[{"name": n, "best": b} for n, b in top], version=VERSION)


# ------------------------------------------------------------------ live game (WebSocket)
def host_room(pin):
    return f"host-{pin}"


@socketio.on("host_join")
def on_host_join(data):
    game = games.get(data.get("pin"))
    if not game or session.get("uid") != game.host_id:
        return {"ok": False}
    join_room(host_room(game.pin))
    return {"ok": True, "players": [p.name for p in game.players.values()], "state": game.state}


@socketio.on("join")
def on_join(data):
    game = games.get(data.get("pin"))
    if not game:
        return {"ok": False, "error": "No game with that PIN"}
    err = game.add_player(request.sid, data.get("name"))
    if err:
        return {"ok": False, "error": err}
    join_room(game.pin)
    log.info("PLAYER joined pin=%s name=%s players=%d ip=%s", game.pin, data.get("name", "")[:20], len(game.players), client_ip())
    emit("lobby", {"players": [p.name for p in game.players.values()]}, to=host_room(game.pin))
    return {"ok": True, "title": game.title, "state": game.state}


@socketio.on("disconnect")
def on_disconnect(*_):
    game = games.find_by_sid(request.sid)
    if game and game.state == "lobby":
        game.remove_player(request.sid)
        socketio.emit("lobby", {"players": [p.name for p in game.players.values()]}, to=host_room(game.pin))


@socketio.on("next")
def on_next(data):
    game = games.get(data.get("pin"))
    if not game or session.get("uid") != game.host_id or game.state in ("question", "finished"):
        return {"ok": False}
    if game.index == -1:
        with app.app_context():
            row = Game(quiz_id=game.quiz_id, pin=game.pin, player_count=len(game.players))
            db.session.add(row)
            db.session.commit()
            game.db_game_id = row.id
    q = game.next_question()
    if q is None:
        finish(game)
        return {"ok": True, "finished": True}
    payload = game.public_question()
    socketio.emit("question", payload, to=game.pin)
    socketio.emit("question", {**payload, "answered": 0, "players": len(game.players)}, to=host_room(game.pin))
    socketio.start_background_task(timer, game.pin, game.index, q["time_limit"])
    return {"ok": True}


def timer(pin, index, limit):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        game = games.get(pin)
        if not game or game.index != index or game.state != "question":
            return
        socketio.sleep(0.25)
    do_reveal(pin, index)


def do_reveal(pin, index):
    game = games.get(pin)
    if not game or game.index != index:
        return
    result = game.reveal()
    if result is None:
        return
    socketio.emit("reveal", result, to=host_room(pin))
    for p in game.players.values():
        rank = next(r["rank"] for r in result["leaderboard"] if r["name"] == p.name)
        socketio.emit("your_result", {"correct": p.answer == result["correct"], "answered": p.answer is not None,
                                      "points": p.last_points, "score": p.score, "rank": rank,
                                      "of": len(game.players), "correct_index": result["correct"]}, to=p.sid)


@socketio.on("answer")
def on_answer(data):
    game = games.find_by_sid(request.sid)
    if not game or not game.submit(request.sid, data.get("choice")):
        return {"ok": False}
    answered = sum(1 for p in game.players.values() if p.answer is not None)
    socketio.emit("answered", {"answered": answered, "players": len(game.players)}, to=host_room(game.pin))
    if game.all_answered():
        do_reveal(game.pin, game.index)
    return {"ok": True}


@socketio.on("skip")
def on_skip(data):
    game = games.get(data.get("pin"))
    if game and session.get("uid") == game.host_id and game.state == "question":
        do_reveal(game.pin, game.index)


def finish(game):
    game.state = "finished"
    board = game.leaderboard()
    log.info("GAME finished pin=%s players=%d winner=%s score=%s", game.pin, len(board),
             board[0]["name"] if board else "-", board[0]["score"] if board else 0)
    with app.app_context():
        row = db.session.get(Game, game.db_game_id) if game.db_game_id else None
        if row:
            row.ended = db.func.now()
            row.player_count = len(game.players)
            for r in board:
                db.session.add(Result(game_id=row.id, nickname=r["name"], score=r["score"], correct_count=r["correct"], rank=r["rank"]))
            db.session.commit()
    socketio.emit("finished", {"podium": board[:3], "leaderboard": board, "report": game.db_game_id}, to=host_room(game.pin))
    for p in game.players.values():
        rank = next(r["rank"] for r in board if r["name"] == p.name)
        socketio.emit("finished", {"rank": rank, "score": p.score, "of": len(board), "podium": board[:3]}, to=p.sid)


with app.app_context():
    seed()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8000, allow_unsafe_werkzeug=True)
