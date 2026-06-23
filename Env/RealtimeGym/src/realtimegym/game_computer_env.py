"""RealtimeGym game adapter: presents a game as a generic ComputerEnv.

This is where ALL game-specific knowledge lives (rendering, the control-button
panel, the key→discrete-action mapping, scoring). The agent never imports this;
it only sees the ``ComputerEnv`` interface. Swapping in a real desktop later
means writing a sibling adapter, with the agent untouched.
"""

from __future__ import annotations

from typing import Any, Optional

import pygame
from PIL import Image

import realtimegym
from computer_env import ComputerEnv, InputEvent, StepResult
from realtimegym.environments.render.control_panel import compose_frame
from realtimegym.io_layer import InputController

_LOAD_TO_VERSION = {"E": "0", "M": "1", "H": "2"}

# Per-game goal description used as the env's `task`. States the GOAL only —
# deliberately NOT the key semantics (the agent infers those from the on-screen
# button panel). Users can override via the `task` constructor arg.
_DEFAULT_TASK = {
    "freeway": (
        "Play Freeway. You are the chicken at the bottom center. Reach the goal "
        "marker at the very top center while avoiding the moving vehicles. Cross "
        "as quickly as possible."
    ),
    "snake": (
        "Play Snake. Guide the snake to eat the apples and grow, while avoiding "
        "the walls, obstacles, and the snake's own body."
    ),
    "overcooked": (
        "Play Overcooked. Cooperatively prepare and deliver dishes: gather "
        "ingredients, cook them, plate the result, and deliver it to score."
    ),
}


def _to_pil(surface: pygame.Surface) -> Image.Image:
    arr = pygame.surfarray.array3d(surface)
    return Image.fromarray(arr.swapaxes(0, 1))


class GameComputerEnv(ComputerEnv):
    """Wraps a RealtimeGym game (freeway/snake/overcooked) as a ComputerEnv."""

    def __init__(
        self,
        game: str,
        cognitive_load: str = "E",
        seed: int = 0,
        task: Optional[str] = None,
    ) -> None:
        if not pygame.get_init():
            pygame.init()
        if not pygame.font.get_init():
            pygame.font.init()

        self.game = game
        self.cognitive_load = cognitive_load
        version = _LOAD_TO_VERSION[cognitive_load]
        self._env, self.real_seed, self._render = realtimegym.make(
            f"{game.capitalize()}-v{version}", seed=seed, render=True
        )
        self._obs, self._done = self._env.reset()
        self._game_surf = self._render.render(self._env)
        gw, gh = self._game_surf.get_size()
        self._controller = InputController(game, screen_w=gw, game_h=gh)
        self.task = task or _DEFAULT_TASK[game]

    # --- ComputerEnv interface ---------------------------------------------

    def screenshot(self) -> Image.Image:
        return _to_pil(compose_frame(self._game_surf, self.game))

    def step(self, event: InputEvent) -> StepResult:
        # Translate the generic InputEvent into the io_layer's event dict, then
        # resolve to a discrete game action (applying paper default-action rules).
        if event.tool_name == "press_key":
            io_event = {"type": "key", "value": event.params.get("key") or ""}
        elif event.tool_name == "click":
            io_event = {
                "type": "click",
                "x": event.params.get("x"),
                "y": event.params.get("y"),
            }
        else:
            io_event = None  # unknown tool -> default action
        action = self._controller.resolve_event(io_event)

        self._obs, self._done, reward, reset_flag = self._env.step(action)
        self._env.summary()
        self._game_surf = self._render.render(self._env)
        return StepResult(
            done=bool(self._done),
            info={
                "action": action,
                "reward": reward,
                "done": self._done,
                "reset": reset_flag,
                "game_turn": self._env.game_turn,
                "tool_output": f"action={action}, reward={reward}, turn={self._env.game_turn}",
            },
        )

    def is_done(self) -> bool:
        return bool(self._done)

    # --- scoring passthrough (used by the eval assembly layer) -------------

    @property
    def total_reward(self) -> float:
        return self._env.reward

    @property
    def game_turn(self) -> int:
        return self._env.game_turn
