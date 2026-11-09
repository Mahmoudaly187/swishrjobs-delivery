#!/usr/bin/env python3
"""A minimal Terra Nova agent.

Plays a full match over the HTTP API: create a game, read the state, pick an
action, submit it, repeat. It is deliberately small so it reads as an example of
the agent API rather than as a strong opponent.

    python3 sample_bot.py --url http://localhost:12000
"""

from __future__ import annotations

import argparse
import json
import urllib.request

COST = {"plains": 1, "forest": 2, "mountain": 3}


def call(url: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def choose(state: dict) -> dict:
    legal = state.get("legalActions") or [{"type": "pass"}]
    claims = sorted(
        (a for a in legal if a["type"] == "claim"),
        key=lambda a: COST[state["tiles"][a["y"] * state["width"] + a["x"]]["terrain"]],
    )
    builds = [a for a in legal if a["type"] == "build"]
    if builds and state["players"][state["you"]]["tiles"] >= 3:
        return builds[0]
    if claims:
        return claims[0]
    return legal[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:12000")
    ap.add_argument("--players", type=int, default=2)
    args = ap.parse_args()

    created = call(args.url, "POST", "/api/game", {"players": args.players, "name": "Sample bot"})
    token, game_id = created["token"], created["gameId"]
    print(f"joined match {created['code']} as player {created['player']}")
    state = created["state"]

    for _ in range(400):
        if state["status"] != "playing":
            break
        if state["you"] == state["current"]:
            result = call(args.url, "POST", f"/api/game/{game_id}/move",
                          {"token": token, "action": choose(state)})
            state = result["state"]
        else:
            state = call(args.url, "GET", f"/api/game/{game_id}/state?token={token}")

    if state["winner"] is not None:
        print(f"winner: {state['players'][state['winner']]['name']}")
    else:
        print("match did not finish")


if __name__ == "__main__":
    main()
