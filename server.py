# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi", "uvicorn", "qrcode"]
# ///
"""LAN server for a Trouble Brewing game (FastAPI).

Players open http://<laptop-ip>:<port>/ on their phones; the Storyteller opens the /st URL
printed at startup (it carries a secret key). Clients poll JSON state; all game logic lives in Game.

Run: uv run server.py [--port 8000]
"""

import argparse
import json
import secrets
import socket
import threading
from pathlib import Path

import qrcode
import qrcode.image.svg
import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game import Game, GameError
from roles import CHARACTERS

STATIC = Path(__file__).parent / "static"

# Game methods the Storyteller page may call as POST /api/st/<name>
ST_ACTIONS = {
    "add_player", "remove_player", "move_player", "deal", "set_character", "set_setup", "start_game",
    "ask", "resolve", "second_round", "send", "finish_step", "message", "start_day", "nominate", "record_votes",
    "slayer_shot", "end_day", "read_inbox", "kill", "revive", "set_poisoned", "set_ghost_vote", "declare_winner", "reset",
    "undo",
}


# undo-button text per action; {name} is the player named by the body's pid
ACTION_LABELS = {
    "add_player": "Seat {body_name}", "remove_player": "Remove {name}", "move_player": "Move {name}",
    "deal": "Deal characters", "set_character": "Change {name}'s character", "set_setup": "Save red herring and bluffs",
    "start_game": "Start the game", "ask": "Ask again", "resolve": "Work out a night step", "second_round": "Second buzz",
    "send": "Hold info for dawn", "finish_step": "Skip or reopen a night step", "message": "Message {name}",
    "start_day": "Start the day", "nominate": "Nomination", "record_votes": "Record votes", "slayer_shot": "Slayer shot",
    "end_day": "End the day", "kill": "Kill {name}", "revive": "Bring back {name}", "set_poisoned": "Change poison",
    "set_ghost_vote": "Change {name}'s ghost vote", "declare_winner": "End the game", "reset": "Reset to the lobby",
}
# not undoable: marking notes read, and undo itself
NO_UNDO = {"read_inbox", "undo"}


class JoinBody(BaseModel):
    """POST /api/join payload."""
    name: str


class NoteBody(BaseModel):
    """POST /api/note payload: the player's secret token and their note to the Storyteller."""
    token: str
    text: str


class TapBody(BaseModel):
    """POST /api/tap payload: the player's secret token and the button they pressed."""
    token: str
    option: str


class ChooseBody(BaseModel):
    """POST /api/choose payload: the player's secret token and chosen pids."""
    token: str
    choices: list[str]


def create_app(game: Game, st_key: str, join_url: str) -> FastAPI:
    """Build the FastAPI app around one game.

    Algorithm: every route that touches the game takes a single lock (sync routes run in a thread
    pool). State-changing routes bump game.version so polling clients know to re-render.
    GameError and malformed Storyteller calls become 400 {"error": msg}.

    Args:
        game (Game): the game to serve.
        st_key (str): secret required on every /api/st call.
        join_url (str): URL players open, encoded in /qr.svg.

    Returns:
        FastAPI: the app.
    """
    app = FastAPI(title="Trouble Brewing")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    lock = threading.Lock()

    @app.exception_handler(GameError)
    def game_error(_: Request, e: GameError) -> JSONResponse:
        return JSONResponse({"error": str(e)}, status_code=400)

    def check_key(key: str) -> None:
        if key != st_key:
            raise GameError("Wrong storyteller key")

    def action_label(action: str, body: dict) -> str:
        pid = body.get("pid")
        name = next((p.name for p in game.players if p.pid == pid), "a player")
        return ACTION_LABELS[action].format(name=name, body_name=body.get("name", "a player"))

    def phone_view() -> str:
        # exactly what each phone receives, minus the version counter
        views = [{k: x for k, x in game.player_view(p.token).items() if k != "version"} for p in game.players]
        return json.dumps(views, sort_keys=True, default=str)

    def st_state() -> dict:
        return {**game.storyteller_view(), "join_url": join_url}

    # --- pages ---

    @app.get("/")
    def player_page() -> FileResponse:
        return FileResponse(STATIC / "player.html", headers={"Cache-Control": "no-store"})

    @app.get("/st")
    def storyteller_page() -> FileResponse:
        return FileResponse(STATIC / "storyteller.html", headers={"Cache-Control": "no-store"})

    @app.get("/qr.svg")
    def join_qr() -> Response:
        svg = qrcode.make(join_url, image_factory=qrcode.image.svg.SvgPathImage).to_string()
        return Response(svg, media_type="image/svg+xml")

    # --- player api ---

    @app.get("/api/characters")
    def characters() -> dict:
        return CHARACTERS

    @app.get("/api/state")
    def state(token: str = "") -> dict:
        with lock:
            return game.player_view(token) if token else game.public_view()

    @app.post("/api/join")
    def join(body: JoinBody) -> dict:
        with lock:
            token = game.add_player(body.name).token
            game.version += 1
            return {"token": token}

    @app.post("/api/choose")
    def choose(body: ChooseBody) -> dict:
        with lock:
            game.choose(body.token, body.choices)
            game.version += 1
            return {}

    @app.post("/api/tap")
    def tap(body: TapBody) -> dict:
        with lock:
            game.tap(body.token, body.option)
            game.version += 1
            return {}

    @app.post("/api/note")
    def note(body: NoteBody) -> dict:
        with lock:
            game.note_to_storyteller(body.token, body.text)
            game.version += 1
            return {}

    # --- storyteller api ---

    @app.get("/api/st")
    def st_view(key: str = "") -> dict:
        with lock:
            check_key(key)
            return st_state()

    @app.post("/api/st/{action}")
    def st_action(action: str, key: str = "", body: dict = Body(default={})) -> dict:
        with lock:
            check_key(key)
            if action not in ST_ACTIONS:
                raise GameError(f"Unknown action {action}")
            before = None if action in NO_UNDO else game.snapshot()
            shown = phone_view()
            try:
                getattr(game, action)(**body)
            except TypeError as e:
                raise GameError(f"Bad arguments for {action}: {e}") from e
            if before is not None:
                game.push_undo(action_label(action, body), before, seen=phone_view() != shown)
            game.version += 1
            return st_state()

    return app


def lan_ip() -> str:
    """This machine's address on the local network (UDP connect sends no packets)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main() -> None:
    """Start the server and print the player join URL (with QR) and the secret Storyteller URL."""
    parser = argparse.ArgumentParser(description="Trouble Brewing LAN server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    join_url = f"http://{lan_ip()}:{args.port}/"
    st_key = secrets.token_urlsafe(6)
    app = create_app(Game(), st_key, join_url)

    qr = qrcode.QRCode(border=1)
    qr.add_data(join_url)
    qr.print_ascii(invert=True)
    print(f"\nPlayers join:              {join_url}")
    print(f"Storyteller (keep secret): http://localhost:{args.port}/st?key={st_key}\n", flush=True)
    # access log off: every phone polls each second
    uvicorn.run(app, host="0.0.0.0", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
