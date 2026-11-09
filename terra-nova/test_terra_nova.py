"""Tests for the Terra Nova engine and API. Run: python3 test_terra_nova.py"""

import terra_nova as tn


def test_deterministic_for_seed():
    a = tn.Game(2, seed=7)
    b = tn.Game(2, seed=7)
    assert [t["terrain"] for t in a.tiles] == [t["terrain"] for t in b.tiles]


def test_players_start_on_corners_with_income():
    g = tn.Game(4, seed=1)
    for p in g.players:
        assert len(g._owned(p["id"])) == 1
    assert g.players[0]["influence"] == tn.START_INFLUENCE + 1


def test_claim_must_be_adjacent():
    g = tn.Game(2, seed=2)
    g.current = 0
    try:
        g.apply(0, {"type": "claim", "x": 4, "y": 4})  # far corner
    except tn.RuleError as exc:
        assert "adjacent" in str(exc) or "owned" in str(exc)
    else:
        raise AssertionError("distant claim should be refused")


def test_claim_costs_terrain():
    g = tn.Game(2, seed=2)
    g.current = 0
    tile = next(i for i in range(len(g.tiles)) if g._adjacent_to(0, i) and g.tiles[i]["owner"] is None)
    x, y = g._xy(tile)
    cost = tn.TERRAIN_COST[g.tiles[tile]["terrain"]]
    before = g.players[0]["influence"]
    g.apply(0, {"type": "claim", "x": x, "y": y})
    assert g.players[0]["influence"] == before - cost
    assert g.tiles[tile]["owner"] == 0


def test_build_and_raid_round_trip():
    g = tn.Game(2, seed=5)
    g.players[0]["influence"] = 20
    own = g._owned(0)[0]
    ox, oy = g._xy(own)
    g.current = 0
    g.apply(0, {"type": "build", "x": ox, "y": oy})
    assert g.tiles[own]["well"]
    assert g._income(0) == 2
    # Give an adjacent tile to player 1 with a well, then raid it from the corner.
    adj = g._neighbours(own)[0]
    ax, ay = g._xy(adj)
    g.tiles[adj]["owner"] = 1
    g.tiles[adj]["well"] = True
    g.current = 0
    g.players[0]["influence"] = 20
    g.apply(0, {"type": "raid", "x": ax, "y": ay})
    assert not g.tiles[adj]["well"]


def test_wrong_turn_refused():
    g = tn.Game(2, seed=1)
    g.current = 0
    try:
        g.apply(1, {"type": "pass"})
    except tn.RuleError as exc:
        assert "turn" in str(exc)
    else:
        raise AssertionError("out-of-turn move should be refused")


def test_bot_games_terminate():
    for seed in range(15):
        g = tn.Game(2, seed=seed)
        for p in g.players:
            p["is_bot"] = True
        for _ in range(600):
            if g.status != "playing":
                break
            try:
                g.apply(g.current, tn.Bot(g, g.current).choose())
            except tn.RuleError:
                g.apply(g.current, {"type": "pass"})
        assert g.status == "finished", seed


def test_api_create_state_move():
    status, created = tn.handle_api("POST", "/api/game", {}, {"players": 2, "name": "T"})
    assert status == 200
    gid, token = created["gameId"], created["token"]
    status, state = tn.handle_api("GET", f"/api/game/{gid}/state", {"token": token}, None)
    assert status == 200 and state["you"] == 0
    status, res = tn.handle_api("POST", f"/api/game/{gid}/move", {},
                                {"token": token, "action": {"type": "pass"}})
    assert status == 200 and res["state"]["status"] in ("playing", "finished")


def test_api_rejects_bad_token():
    _, created = tn.handle_api("POST", "/api/game", {}, {"players": 2})
    gid = created["gameId"]
    status, res = tn.handle_api("POST", f"/api/game/{gid}/move", {},
                                {"token": "nope", "action": {"type": "pass"}})
    assert status == 403


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(fns)} tests passed")
