"""Terra Nova - a turn-based multiplayer strategy game for humans and agents.

Rules (one paragraph). On a 5x5 board of plains, forest and mountain tiles, two
to four players race to control eight tiles. Each player starts on a corner with
five influence. At the start of your turn you collect one influence per tile you
own, plus one for each well on your tiles. You then take exactly one action:
claim an unowned tile orthogonally adjacent to your territory, paying its terrain
cost (plains 1, forest 2, mountain 3); build a well on one of your tiles for 3,
raising that tile's yield by one for the rest of the game; raid an enemy well
adjacent to your territory for 4, destroying it; or pass. Terrain cost makes a
plains rush cheap but land-poor, wells pay back over three turns, and a raid can
erase an opponent's investment, so no single line dominates. The first player to
own eight tiles wins; if the board fills first, the most tiles wins, ties broken
by influence.

The module is standard library only, so it runs with no install.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

WIDTH = 5
HEIGHT = 5
WIN_TILES = 8
START_INFLUENCE = 5
WELL_COST = 3
RAID_COST = 4

#: Claim cost per terrain. Yield is flat (one per tile) so terrain is purely a
#: cost decision: plains are cheap, mountains are expensive to take.
TERRAIN_COST = {"plains": 1, "forest": 2, "mountain": 3}
TERRAIN_WEIGHT = {"plains": 60, "forest": 25, "mountain": 15}

COLORS = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9"]
CORNERS = [(0, 0), (WIDTH - 1, HEIGHT - 1), (0, HEIGHT - 1), (WIDTH - 1, 0)]


class RuleError(Exception):
    """Raised when an action is not legal for the current game state."""


def _terrain(rng: random.Random) -> str:
    kinds = list(TERRAIN_WEIGHT)
    return rng.choices(kinds, weights=[TERRAIN_WEIGHT[k] for k in kinds], k=1)[0]


class Game:
    """One match. All mutation goes through :meth:`apply`."""

    def __init__(self, players: int, seed: int | None = None,
                 names: list[str] | None = None) -> None:
        if not 2 <= players <= 4:
            raise RuleError("players must be between 2 and 4")
        self.rng = random.Random(seed)
        self.width, self.height = WIDTH, HEIGHT
        self.tiles: list[dict[str, Any]] = [
            {"terrain": _terrain(self.rng), "owner": None, "well": False}
            for _ in range(WIDTH * HEIGHT)
        ]
        self.players = [
            {
                "id": i,
                "name": (names[i] if names and i < len(names) else f"Player {i + 1}"),
                "color": COLORS[i],
                "influence": START_INFLUENCE,
                "is_bot": False,
            }
            for i in range(players)
        ]
        for i, (x, y) in enumerate(CORNERS[:players]):
            self.tiles[self._idx(x, y)]["owner"] = i
        self.turn = 0
        self.current = 0
        self.status = "playing"
        self.winner: int | None = None
        self.log: list[dict[str, Any]] = []
        self._turn_counter = 0
        # The starting player collects income at the start of the first turn too.
        self._collect_income()

    # -- coordinates ------------------------------------------------------

    def _idx(self, x: int, y: int) -> int:
        return y * self.width + x

    def _xy(self, idx: int) -> tuple[int, int]:
        return idx % self.width, idx // self.width

    def _neighbours(self, idx: int) -> list[int]:
        x, y = self._xy(idx)
        out = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.width and 0 <= ny < self.height:
                out.append(self._idx(nx, ny))
        return out

    def _owned(self, player: int) -> list[int]:
        return [i for i, t in enumerate(self.tiles) if t["owner"] == player]

    def _adjacent_to(self, player: int, idx: int) -> bool:
        return any(self.tiles[n]["owner"] == player for n in self._neighbours(idx))

    def _income(self, player: int) -> int:
        tiles = self._owned(player)
        return len(tiles) + sum(1 for i in tiles if self.tiles[i]["well"])

    def _collect_income(self) -> None:
        self.players[self.current]["influence"] += self._income(self.current)

    # -- actions ----------------------------------------------------------

    def _cost(self, action: dict[str, Any]) -> int:
        kind = action.get("type")
        if kind == "claim":
            return TERRAIN_COST[self.tiles[self._idx(action["x"], action["y"])]["terrain"]]
        if kind == "build":
            return WELL_COST
        if kind == "raid":
            return RAID_COST
        return 0

    def legal_actions(self, player: int) -> list[dict[str, Any]]:
        """Every action the player could take right now (used by the bot and the UI)."""
        out: list[dict[str, Any]] = [{"type": "pass"}]
        inf = self.players[player]["influence"]
        for idx, tile in enumerate(self.tiles):
            x, y = self._xy(idx)
            if tile["owner"] is None and self._adjacent_to(player, idx):
                if TERRAIN_COST[tile["terrain"]] <= inf:
                    out.append({"type": "claim", "x": x, "y": y})
            elif tile["owner"] == player and not tile["well"] and WELL_COST <= inf:
                out.append({"type": "build", "x": x, "y": y})
            elif (tile["owner"] not in (None, player) and tile["well"]
                  and self._adjacent_to(player, idx) and RAID_COST <= inf):
                out.append({"type": "raid", "x": x, "y": y})
        return out

    def apply(self, player: int, action: dict[str, Any]) -> dict[str, Any]:
        """Apply one action for ``player`` and advance the turn. Raises RuleError."""
        if self.status != "playing":
            raise RuleError("the match is over")
        if player != self.current:
            raise RuleError(f"it is not player {player}'s turn")
        if not isinstance(action, dict):
            raise RuleError("action must be an object")
        kind = action.get("type")
        if kind == "pass":
            return self._end_turn(player, {"type": "pass"})
        if kind not in ("claim", "build", "raid"):
            raise RuleError("action type must be claim, build, raid or pass")
        if not isinstance(action.get("x"), int) or not isinstance(action.get("y"), int):
            raise RuleError("x and y must be integers")
        x, y = action["x"], action["y"]
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise RuleError("that tile is off the board")
        idx = self._idx(x, y)
        tile = self.tiles[idx]
        cost = self._cost(action)
        if cost > self.players[player]["influence"]:
            raise RuleError(
                f"{kind} costs {cost} influence; player {player} has "
                f"{self.players[player]['influence']}"
            )
        if kind == "claim":
            if tile["owner"] is not None:
                raise RuleError("that tile is already owned")
            if not self._adjacent_to(player, idx):
                raise RuleError("you can only claim a tile adjacent to your territory")
            tile["owner"] = player
        elif kind == "build":
            if tile["owner"] != player:
                raise RuleError("you can only build a well on your own tile")
            if tile["well"]:
                raise RuleError("that tile already has a well")
            tile["well"] = True
        else:  # raid
            if tile["owner"] in (None, player):
                raise RuleError("you can only raid an enemy tile")
            if not tile["well"]:
                raise RuleError("there is no well on that tile to raid")
            if not self._adjacent_to(player, idx):
                raise RuleError("you can only raid a tile adjacent to your territory")
            tile["well"] = False
        self.players[player]["influence"] -= cost
        return self._end_turn(player, {"type": kind, "x": x, "y": y, "cost": cost})

    def _end_turn(self, player: int, entry: dict[str, Any]) -> dict[str, Any]:
        self._turn_counter += 1
        entry["turn"] = self._turn_counter
        entry["player"] = player
        self.log.append(entry)
        if self._check_win():
            return self.log[-1]
        self.current = (self.current + 1) % len(self.players)
        if self.current == 0:
            self.turn += 1
        self._collect_income()
        return self.log[-1]

    def _check_win(self) -> bool:
        for p in self.players:
            if len(self._owned(p["id"])) >= WIN_TILES:
                self.status = "finished"
                self.winner = p["id"]
                return True
        if all(t["owner"] is not None for t in self.tiles):
            self.status = "finished"
            best = max(
                self.players,
                key=lambda p: (len(self._owned(p["id"])), p["influence"]),
            )
            self.winner = best["id"]
            return True
        return False

    # -- views ------------------------------------------------------------

    def public_state(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "winTiles": WIN_TILES,
            "tiles": [
                {"terrain": t["terrain"], "owner": t["owner"], "well": t["well"]}
                for t in self.tiles
            ],
            "players": [
                {"id": p["id"], "name": p["name"], "color": p["color"],
                 "influence": p["influence"], "tiles": len(self._owned(p["id"])),
                 "is_bot": p["is_bot"]}
                for p in self.players
            ],
            "current": self.current,
            "turn": self.turn,
            "status": self.status,
            "winner": self.winner,
            "log": self.log[-40:],
        }

    def state_for(self, player: int | None) -> dict[str, Any]:
        state = self.public_state()
        state["you"] = player
        state["legalActions"] = self.legal_actions(player) if player is not None else []
        return state


class Bot:
    """A small heuristic opponent: expand on cheap land, invest, then raid."""

    def __init__(self, game: Game, player: int) -> None:
        self.game = game
        self.player = player

    def choose(self) -> dict[str, Any]:
        g = self.game
        actions = g.legal_actions(self.player)
        claims = [a for a in actions if a["type"] == "claim"]
        builds = [a for a in actions if a["type"] == "build"]
        raids = [a for a in actions if a["type"] == "raid"]

        def cost(a: dict[str, Any]) -> int:
            if a["type"] == "claim":
                return TERRAIN_COST[g.tiles[g._idx(a["x"], a["y"])]["terrain"]]
            return WELL_COST if a["type"] == "build" else RAID_COST

        # Winning move first: take the cheapest claim that reaches the goal.
        for a in sorted(claims, key=cost):
            if len(g._owned(self.player)) + 1 >= WIN_TILES:
                return a
        # A well pays back in three turns; build early, but not while land is cheap
        # and plentiful.
        owned = len(g._owned(self.player))
        if builds and g.players[self.player]["influence"] >= WELL_COST + 2 and owned >= 3:
            return builds[0]
        if claims:
            return sorted(claims, key=cost)[0]
        if builds:
            return builds[0]
        if raids:
            return raids[0]
        return {"type": "pass"}


class Store:
    """In-memory games and tokens, guarded by one lock."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.games: dict[str, Game] = {}
        self.tokens: dict[str, tuple[str, int]] = {}
        self.codes: dict[str, str] = {}

    def new_game(self, players: int, names: list[str] | None = None,
                 seed: int | None = None) -> tuple[str, Game]:
        with self.lock:
            gid = secrets.token_hex(4)
            self.games[gid] = Game(players, seed=seed, names=names)
            self.codes[gid] = gid.upper()
            return gid, self.games[gid]

    def token(self, gid: str, player: int) -> str:
        tok = secrets.token_urlsafe(12)
        with self.lock:
            self.tokens[tok] = (gid, player)
        return tok

    def resolve(self, tok: str) -> tuple[Game, int] | None:
        with self.lock:
            hit = self.tokens.get(tok)
            if not hit:
                return None
            gid, player = hit
            return self.games[gid], player

    def by_code(self, code: str) -> str | None:
        for gid, c in self.codes.items():
            if c == code.strip().upper():
                return gid
        return None

    def bot_move(self, gid: str) -> None:
        """If it is a bot's turn, take one action (called after every change)."""
        for _ in range(len(self.games[gid].players) + 1):
            g = self.games[gid]
            if g.status != "playing":
                return
            cur = g.players[g.current]
            if not cur["is_bot"]:
                return
            action = Bot(g, g.current).choose()
            try:
                g.apply(g.current, action)
            except RuleError:
                g.apply(g.current, {"type": "pass"})


STORE = Store()


def _fill_bots(g: Game) -> None:
    """Mark seats with no human as bots so a lone player still gets a match."""
    for p in g.players:
        if not p.get("claimed"):
            p["is_bot"] = True


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

ROUTE_GAME = re.compile(r"^/api/game/([0-9a-f]+)$")
ROUTE_JOIN = re.compile(r"^/api/game/([0-9a-f]+)/join$")
ROUTE_STATE = re.compile(r"^/api/game/([0-9a-f]+)/state$")
ROUTE_MOVE = re.compile(r"^/api/game/([0-9a-f]+)/move$")
ROUTE_LOG = re.compile(r"^/api/game/([0-9a-f]+)/log$")


def handle_api(method: str, path: str, query: dict[str, str],
               body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    """Pure routing for the JSON API, so it can be tested without a socket."""
    if method == "POST" and path == "/api/game":
        body = body or {}
        players = body.get("players", 2)
        if not isinstance(players, int) or not 2 <= players <= 4:
            return 400, {"error": "players must be 2, 3 or 4"}
        seed = body.get("seed") if isinstance(body.get("seed"), int) else None
        gid, g = STORE.new_game(players, seed=seed)
        tok = STORE.token(gid, 0)
        g.players[0]["name"] = str(body.get("name") or "You")[:24]
        g.players[0]["claimed"] = True
        for p in g.players[1:]:
            p["is_bot"] = True
        return 200, {"gameId": gid, "code": gid.upper(), "token": tok,
                     "player": 0, "state": g.state_for(0)}

    m = ROUTE_JOIN.match(path)
    if method == "POST" and m:
        gid = m.group(1)
        if gid not in STORE.games:
            return 404, {"error": "no such game"}
        g = STORE.games[gid]
        seat = next((p["id"] for p in g.players if p.get("is_bot")), None)
        if seat is None:
            return 409, {"error": "no open seat"}
        g.players[seat]["is_bot"] = False
        g.players[seat]["claimed"] = True
        g.players[seat]["name"] = str((body or {}).get("name") or f"Player {seat + 1}")[:24]
        return 200, {"gameId": gid, "token": STORE.token(gid, seat), "player": seat,
                     "state": g.state_for(seat)}

    m = ROUTE_STATE.match(path)
    if method == "GET" and m:
        gid = m.group(1)
        if gid not in STORE.games:
            return 404, {"error": "no such game"}
        g = STORE.games[gid]
        viewer = None
        tok = query.get("token")
        if tok:
            hit = STORE.resolve(tok)
            if hit and hit[0] is g:
                viewer = hit[1]
        return 200, g.state_for(viewer)

    m = ROUTE_MOVE.match(path)
    if method == "POST" and m:
        gid = m.group(1)
        if gid not in STORE.games:
            return 404, {"error": "no such game"}
        g = STORE.games[gid]
        tok = (body or {}).get("token") or query.get("token")
        hit = STORE.resolve(tok) if tok else None
        if not hit or hit[0] is not g:
            return 403, {"error": "a valid token is required to move"}
        try:
            entry = g.apply(hit[1], (body or {}).get("action") or {})
        except RuleError as exc:
            return 409, {"error": str(exc), "state": g.state_for(hit[1])}
        STORE.bot_move(gid)
        return 200, {"applied": entry, "state": g.state_for(hit[1])}

    m = ROUTE_LOG.match(path)
    if method == "GET" and m:
        gid = m.group(1)
        if gid not in STORE.games:
            return 404, {"error": "no such game"}
        return 200, {"log": STORE.games[gid].log}

    if method == "GET" and path == "/api/health":
        return 200, {"status": "ok", "games": len(STORE.games)}

    return 404, {"error": f"no route for {method} {path}"}


def make_handler(public_dir: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TerraNova/1.0"

        def log_message(self, *args: Any) -> None:  # keep stdout clean
            pass

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def _read_body(self) -> dict[str, Any] | None:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return None
            raw = self.rfile.read(n)
            try:
                return json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return None

        def _static(self, path: str) -> None:
            if path == "/":
                path = "/index.html"
            safe = os.path.normpath(path).lstrip("/")
            if safe.startswith(".."):
                return self._json(403, {"error": "forbidden"})
            full = os.path.join(public_dir, safe)
            if not os.path.isfile(full):
                return self._json(404, {"error": "not found"})
            ctype = "text/html" if full.endswith(".html") else "text/plain"
            if full.endswith(".js"):
                ctype = "application/javascript"
            if full.endswith(".css"):
                ctype = "text/css"
            with open(full, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _dispatch(self, method: str) -> None:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                body = self._read_body() if method in ("POST", "PUT") else None
                status, payload = handle_api(method, parsed.path, query, body)
                return self._json(status, payload)
            if method != "GET":
                return self._json(405, {"error": "method not allowed"})
            return self._static(parsed.path)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description="Terra Nova game server")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "12000")))
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    public = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(public))
    print(f"Terra Nova on http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
