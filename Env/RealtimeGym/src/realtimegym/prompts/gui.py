"""GUI (vision) prompts for RealtimeGym computer-use mode.

These prompts turn each game into a *visual* GUI task: instead of feeding the
agent a textual ASCII grid, we render the current game frame to a screenshot
(with an on-screen action-button panel) and ask the model to look at the image
and act like a human — by pressing a key or clicking a button.

The game rules are kept faithful to the original text baselines
(`prompts/<game>.py`), only the *observation* (screenshot) and the *action
interface* (keyboard / mouse events) change. The model answers with a single
``Key("...")`` or ``Click(x, y)`` event, parsed by ``realtimegym.io_layer``.

Keyboard convention (traditional game keys):
  W/A/S/D = up/left/down/right, F = interact, Space = stop.
"""

from typing import Any

# Per-game legal keys (shown to the model) and metadata.
GAME_ACTIONS: dict[str, dict[str, Any]] = {
    "freeway": {
        "all_actions": "UDS",
        "keys": '"W" (up), "S" (down), "Space" (stay)',
        "key_help": (
            "- `Key(\"W\")`: move UP one row (toward the goal at the top).\n"
            "- `Key(\"S\")`: move DOWN one row.\n"
            "- `Key(\"Space\")`: STAY in the current row."
        ),
        "rules": (
            "You are the chicken at the bottom center of the board. Your goal is "
            "to reach the red pin marker at the TOP center, moving straight up "
            "column by column. Cars drive horizontally across the lanes between "
            "you and the goal. If a car overlaps your cell when you are on its "
            "lane, you get pushed back to the start. Each turn you choose ONE "
            "action. Moving up onto a lane the same turn a car passes does not "
            "count as a collision for that lane."
        ),
    },
    "snake": {
        "all_actions": "UDLR",
        "keys": '"W" (up), "S" (down), "A" (left), "D" (right)',
        "key_help": (
            "- `Key(\"W\")`: move the snake head UP.\n"
            "- `Key(\"S\")`: move the snake head DOWN.\n"
            "- `Key(\"A\")`: move the snake head LEFT.\n"
            "- `Key(\"D\")`: move the snake head RIGHT."
        ),
        "rules": (
            "You control the snake. The snake head is highlighted; its body "
            "trails behind it. Eat the apple to grow and score points. Avoid "
            "running into the walls, obstacles, or the snake's own body, which "
            "ends the game. You cannot reverse directly into your own neck. "
            "Each turn you choose ONE direction (the snake never stops moving)."
        ),
    },
    "overcooked": {
        "all_actions": "UDLRIS",
        "keys": (
            '"W" (up), "S" (down), "A" (left), "D" (right), '
            '"F" (interact), "Space" (stay)'
        ),
        "key_help": (
            "- `Key(\"W\")`/`Key(\"S\")`/`Key(\"A\")`/`Key(\"D\")`: move the chef "
            "UP/DOWN/LEFT/RIGHT.\n"
            "- `Key(\"F\")`: INTERACT with the tile the chef is facing (pick up / "
            "drop / use station).\n"
            "- `Key(\"Space\")`: STAY (do nothing this turn)."
        ),
        "rules": (
            "You control a chef in a kitchen. Cooperatively prepare and deliver "
            "dishes: gather ingredients, put them in pots to cook, plate the "
            "finished soup, and deliver it to the serving station to score. "
            "Each turn you choose ONE action."
        ),
    },
}

_TEMPLATE = """You are an expert game-playing agent operating a computer, just like a human player. You are looking at a live screenshot of the game **{game_title}**. Below the game there is a panel of clickable action buttons.

## Game rules
{rules}

## How to act (keyboard or mouse)
You act exactly like a human: press a key, or click one of the on-screen action buttons.

Keyboard keys for this game:
{key_help}

Mouse: you may instead click an action button shown at the bottom of the screenshot using `Click(x, y)` with pixel coordinates.

## Current frame
Look carefully at the screenshot above (turn {game_turn}). Reason briefly about the safest/best move, then commit to exactly ONE action for THIS turn.

## Answer format
End your response with a single action event, either a key press or a click, for example:
`Key("W")`   or   `Click(120, 560)`
Use only these keys: {keys}.
"""


def build_gui_prompt(game: str, game_turn: int) -> dict[str, Any]:
    """Return text prompt + action metadata for the given game.

    Returns a dict with keys: ``text``, ``all_actions``.
    """
    if game not in GAME_ACTIONS:
        raise ValueError(f"Unknown game for GUI prompt: {game}")
    cfg = GAME_ACTIONS[game]
    text = _TEMPLATE.format(
        game_title=game.capitalize(),
        rules=cfg["rules"],
        key_help=cfg["key_help"],
        game_turn=game_turn,
        keys=cfg["keys"],
    )
    return {
        "text": text,
        "all_actions": cfg["all_actions"],
    }
