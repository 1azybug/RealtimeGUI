"""OSWorld adapter: presents an OSWorld ``DesktopEnv`` as a generic ``ComputerEnv``.

The only adaptation needed to run the decoupled Holo agent
(``holo_agent.HoloComputerAgent``) on OSWorld. ALL OSWorld-specific and
pyautogui-specific knowledge lives here; the agent is never modified and never
imports anything from OSWorld. This module depends only on the ``computer_env``
contract — it has no Holo knowledge and never imports the agent.

The agent drives this object through the ``ComputerEnv`` contract: ``task``
(goal string), ``screenshot()``, ``step(InputEvent) -> StepResult``, ``is_done()``,
``screen_size()``. Coordinate fields inside an ``InputEvent`` arrive ALREADY
scaled to pixels (the agent scales [0,1000]->px using ``screen_size()``), so we
only emit the matching pyautogui code. The ``answer`` tool is terminal and ends
the agent loop *before* reaching ``step()``; the runner inspects the final
answer and issues the OSWorld special action (DONE / FAIL) for scoring.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image

from computer_env import ComputerEnv, InputEvent, StepResult


# Holo key name -> pyautogui key name.
_KEYMAP = {
    "return": "enter",
    "enter": "enter",
    "space": "space",
    "spacebar": "space",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "escape": "esc",
    "esc": "esc",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "home": "home",
    "end": "end",
    "insert": "insert",
    "capslock": "capslock",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "meta": "win",
    "super": "win",
    "win": "win",
    "cmd": "win",
    "command": "win",
}
for _i in range(1, 13):
    _KEYMAP[f"f{_i}"] = f"f{_i}"


def _map_key(k: str) -> str:
    return _KEYMAP.get(str(k).strip().lower(), str(k).strip().lower())


class OSWorldComputerEnv(ComputerEnv):
    """Wraps a (already-reset) OSWorld ``DesktopEnv`` as a ``ComputerEnv``."""

    def __init__(self, env: Any, instruction: str, pause: float = 1.0) -> None:
        self.env = env
        self.task = instruction
        self.pause = pause
        self._w = int(env.screen_width)
        self._h = int(env.screen_height)
        self._obs = env._get_obs()
        self._done = False
        self.executed: list[str] = []  # pyautogui code strings actually sent

    # --- ComputerEnv interface --------------------------------------------- #
    def screenshot(self) -> Image.Image:
        return Image.open(BytesIO(self._obs["screenshot"]))

    def screen_size(self) -> tuple[int, int]:
        return (self._w, self._h)

    def is_done(self) -> bool:
        return self._done

    def step(self, event: InputEvent) -> StepResult:
        action = self._event_to_action(event)
        obs, reward, done, info = self.env.step(action, self.pause)
        self._obs = obs
        self._done = bool(done)
        if action not in ("WAIT", "DONE", "FAIL"):
            self.executed.append(action)
        return StepResult(
            done=self._done,
            info={
                "reward": reward,
                "done": self._done,
                "info": info,
                "pyautogui": action,
                "tool_output": "Action executed. The new screenshot follows.",
            },
        )

    # --- tool_call -> pyautogui ------------------------------------------- #
    def _event_to_action(self, event: InputEvent) -> str:
        name = event.tool_name
        p = event.params or {}

        if name == "click":
            return f"import pyautogui\npyautogui.click({p['x']}, {p['y']})"
        if name == "double_click":
            return f"import pyautogui\npyautogui.doubleClick({p['x']}, {p['y']})"
        if name == "right_click":
            return f"import pyautogui\npyautogui.click({p['x']}, {p['y']}, button='right')"
        if name == "write":
            code = "import pyautogui\npyautogui.write({!r}, interval=0.02)".format(p.get("content", ""))
            if p.get("press_enter"):
                code += "\npyautogui.press('enter')"
            return code
        if name == "press_key":
            return f"import pyautogui\npyautogui.press({_map_key(p.get('key',''))!r})"
        if name == "hotkey":
            keys = ", ".join(repr(_map_key(k)) for k in p.get("keys", []))
            return f"import pyautogui\npyautogui.hotkey({keys})"
        if name == "scroll":
            x, y = p["x"], p["y"]
            amount = max(1, int(p.get("amount", 3)))
            clicks = amount * 100
            direction = p.get("direction", "down")
            if direction in ("up", "down"):
                signed = clicks if direction == "up" else -clicks
                return f"import pyautogui\npyautogui.moveTo({x}, {y})\npyautogui.scroll({signed})"
            signed = clicks if direction == "right" else -clicks
            return f"import pyautogui\npyautogui.moveTo({x}, {y})\npyautogui.hscroll({signed})"
        if name == "drag":
            return (
                f"import pyautogui\npyautogui.moveTo({p['x']}, {p['y']})\n"
                f"pyautogui.dragTo({p['to_x']}, {p['to_y']}, duration=0.5, button='left')"
            )
        if name == "wait":
            return "WAIT"
        # `answer` is terminal and handled by the runner; anything unknown -> wait.
        return "WAIT"
