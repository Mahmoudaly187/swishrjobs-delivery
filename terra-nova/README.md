# Terra Nova

A small, polished, turn-based strategy game that humans and AI agents play in the
same match. Humans play in the browser with no install and no login; agents play
over a plain HTTP/JSON API. It is one Python file plus one HTML file, standard
library only.

- **Live game:** https://work-1-heaabplxecqwbnnt.prod-runtime.all-hands.dev/
- **Rules:** see below (one paragraph).

## Rules

On a 5x5 board of plains, forest and mountain tiles, two to four players race to
control **eight tiles**. Each player starts on a corner with five influence. At
the start of your turn you collect one influence per tile you own, plus one for
each well on your tiles. You then take exactly one action: **claim** an unowned
tile orthogonally adjacent to your territory, paying its terrain cost (plains 1,
forest 2, mountain 3); **build** a well on one of your tiles for 3, raising that
tile's yield by one for the rest of the game; **raid** an enemy well adjacent to
your territory for 4, destroying it; or **pass**. Terrain cost makes a plains
rush cheap but land-poor, wells pay back over three turns, and a raid can erase
an opponent's investment, so no single line dominates. The first player to own
eight tiles wins; if the board fills first, the most tiles wins, ties broken by
influence.

### Why it is a game and not a race

- **Every turn is a real decision.** Claim (spend now, grow income), build (spend
  3 to gain +1 per turn forever), raid (spend 4 to deny an opponent's income), or
  pass (bank influence for an expensive mountain push).
- **No dominant strategy.** Cheap plains are the fastest route to eight tiles but
  leave you with weak income if the opponent builds wells; mountains are strong
  defensive buffers but slow to take; wells are pure investment that a single
  raid can undo.
- **Matches are short.** Bot-vs-bot games finish in roughly 10-14 turns; a human
  match is comfortably under ten minutes.

## How to run

No dependencies.

```bash
python3 terra_nova.py            # serves on http://0.0.0.0:12000 (PORT overrides)
```

Open the printed URL in a browser. Press **New match** to start, or **Join with
code** to take an open seat in an existing match. Empty seats are filled by a
bot, so one human can play immediately, and any seat can be taken over by an
agent through the API.

Play a full match from the command line with the sample bot:

```bash
python3 sample_bot.py --url http://localhost:12000
```

## Agent API

All responses are JSON. CORS is open. `POST` bodies are JSON.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/game` | Create a match. Body `{"players": 2..4, "name": "..."}`. Returns `gameId`, `code`, `token`, `player`, `state`. |
| `POST` | `/api/game/{id}/join` | Take an open seat. Body `{"name": "..."}`. Returns `token`, `player`, `state`. |
| `GET` | `/api/game/{id}/state?token=...` | Read the state. With a `token` you also get `you` and `legalActions`. |
| `POST` | `/api/game/{id}/move` | Submit one action. Body `{"token": "...", "action": {...}}`. |
| `GET` | `/api/game/{id}/log` | The full move log (the replay). |

An action is one of:

```json
{"type": "claim", "x": 1, "y": 0}
{"type": "build", "x": 0, "y": 0}
{"type": "raid",  "x": 1, "y": 0}
{"type": "pass"}
```

`legalActions` in the state lists exactly the actions that are legal for you
right now, so an agent can pick one without re-deriving the rules. An illegal
action returns HTTP `409` with an `error` string and the current state, and does
not change the match.

### Example: an agent plays a turn

```bash
# 1. create a match and read your token
curl -s -X POST http://localhost:12000/api/game \
  -H 'Content-Type: application/json' \
  -d '{"players": 2, "name": "my-agent"}'

# 2. read the state and the legal actions
curl -s "http://localhost:12000/api/game/GAMEID/state?token=TOKEN"

# 3. claim a tile
curl -s -X POST http://localhost:12000/api/game/GAMEID/move \
  -H 'Content-Type: application/json' \
  -d '{"token": "TOKEN", "action": {"type": "claim", "x": 1, "y": 0}}'
```

The bot seat in the browser and the API share one engine, so a human and an agent
in the same match see and obey exactly the same rules.

## Layout

- `terra_nova.py` - the engine (rules, bot, HTTP server). Pure standard library.
- `public/index.html` - the browser client, one self-contained file.
- `sample_bot.py` - a minimal agent that plays a full match over the API.

## Tests

```bash
python3 -c "import terra_nova"   # imports clean
python3 sample_bot.py           # plays a complete match end to end
```

The engine is deterministic for a given seed, so a match can be reproduced from
its `log`.
