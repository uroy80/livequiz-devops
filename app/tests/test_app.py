import re
import pytest
from app import app, socketio, games, db
from models import Quiz, Game, Result
from engine import LiveGame


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    return app.test_client()


def csrf(c):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', c.get("/login").get_data(as_text=True)).group(1)


def login(c, user="admin", pw="test-admin-pass"):
    return c.post("/login", data={"username": user, "password": pw, "csrf": csrf(c)})


# ---------------- engine
def test_scoring_rewards_correct_and_fast():
    g = LiveGame("123456", 1, "t", [{"text": "q", "options": ["a", "b"], "correct": 1, "time_limit": 10}], 1)
    assert g.add_player("s1", "Asha") is None and g.add_player("s2", "Ravi") is None
    assert g.add_player("s3", "asha") == "That nickname is taken"
    g.next_question()
    assert g.submit("s1", 1) and g.submit("s2", 0)
    assert not g.submit("s1", 0)                       # cannot answer twice
    r = g.reveal()
    assert r["distribution"] == [1, 1] and r["correct"] == 1
    board = {p["name"]: p["score"] for p in r["leaderboard"]}
    assert board["Asha"] >= 500 and board["Ravi"] == 0
    assert g.next_question() is None and g.state == "finished"


def test_invalid_answers_rejected():
    g = LiveGame("1", 1, "t", [{"text": "q", "options": ["a", "b"], "correct": 0, "time_limit": 10}], 1)
    g.add_player("s1", "A"); g.next_question()
    assert not g.submit("s1", 7) and not g.submit("s1", "0") and not g.submit("nobody", 0)


# ---------------- web
def test_home_and_health(client):
    assert b"Real-time quizzes" in client.get("/").data
    assert client.get("/healthz").get_json()["status"] == "ok"
    assert "quizzes" in client.get("/api/stats").get_json()


def test_dashboard_requires_login(client):
    assert client.get("/dashboard").status_code == 302


def test_login_and_demo_quiz_seeded(client):
    login(client)
    page = client.get("/dashboard").get_data(as_text=True)
    assert "DevOps &amp; Cloud Challenge" in page


def test_wrong_password_and_csrf(client):
    assert b"Wrong username" in login(client, pw="nope").data
    assert client.post("/login", data={"username": "admin", "password": "x"}).status_code == 400   # no CSRF token


def test_fresh_visitor_cannot_post_without_token():
    fresh = app.test_client()          # never loaded a page, so no session token exists
    assert fresh.post("/login", data={"username": "admin", "password": "test-admin-pass"}).status_code == 400
    assert fresh.post("/login", data={"username": "admin", "password": "test-admin-pass", "csrf": ""}).status_code == 400


def test_register_and_create_quiz(client):
    t = csrf(client)
    client.post("/register", data={"username": "teacher1", "password": "secret-pass-1", "csrf": t})
    t = re.search(r'name="csrf" value="([0-9a-f]+)"', client.get("/quiz/new").get_data(as_text=True)).group(1)   # new session after login
    r = client.post("/quiz/new", data={"csrf": t, "title": "Capitals", "q_text": ["Capital of India?"],
                                       "q0_opt": ["Mumbai", "New Delhi", "", ""], "q0_correct": "1", "q0_time": "15"}, follow_redirects=True)
    assert b"saved with 1 questions" in r.data
    with app.app_context():
        q = Quiz.query.filter_by(title="Capitals").one()
        assert q.questions[0].options == ["Mumbai", "New Delhi"] and q.questions[0].correct == 1


# ---------------- full live game over WebSockets
def test_live_game_end_to_end(client):
    login(client)
    with app.app_context():
        qid = Quiz.query.filter_by(title="DevOps & Cloud Challenge").one().id
    r = client.post(f"/quiz/{qid}/host", data={"csrf": csrf(client)})
    pin = r.headers["Location"].rsplit("/", 1)[1]
    assert b"svg" in client.get(f"/host/{pin}").data                          # QR code rendered
    host = socketio.test_client(app, flask_test_client=client)
    assert host.emit("host_join", {"pin": pin}, callback=True)["ok"]
    p1, p2 = socketio.test_client(app), socketio.test_client(app)
    assert p1.emit("join", {"pin": pin, "name": "Asha"}, callback=True)["ok"]
    assert p2.emit("join", {"pin": pin, "name": "Ravi"}, callback=True)["ok"]
    assert not socketio.test_client(app).emit("join", {"pin": "000000", "name": "x"}, callback=True)["ok"]
    game = games.get(pin)
    for i, q in enumerate(game.questions):
        assert host.emit("next", {"pin": pin}, callback=True)["ok"]
        assert p1.emit("answer", {"choice": q["correct"]}, callback=True)["ok"]       # Asha always right
        assert p2.emit("answer", {"choice": (q["correct"] + 1) % 4}, callback=True)["ok"]
        assert game.state == "reveal"
    assert host.emit("next", {"pin": pin}, callback=True).get("finished")
    events = [e["name"] for e in p1.get_received()]
    assert "question" in events and "your_result" in events and "finished" in events
    with app.app_context():
        row = Game.query.filter_by(pin=pin).one()
        winner = Result.query.filter_by(game_id=row.id, rank=1).one()
        assert winner.nickname == "Asha" and winner.correct_count == 6 and row.player_count == 2
    assert client.get(f"/game/{row.id}").status_code == 200


def test_player_cannot_control_game(client):
    login(client)
    with app.app_context():
        qid = Quiz.query.filter_by(title="DevOps & Cloud Challenge").one().id
    pin = client.post(f"/quiz/{qid}/host", data={"csrf": csrf(client)}).headers["Location"].rsplit("/", 1)[1]
    intruder = socketio.test_client(app)
    assert not intruder.emit("next", {"pin": pin}, callback=True)["ok"]
    assert not intruder.emit("host_join", {"pin": pin}, callback=True)["ok"]
