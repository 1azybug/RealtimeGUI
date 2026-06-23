"""Generic computer-use environment interface (the Agent/Env boundary).

This is the contract that decouples the agent from any specific environment. A
``HoloComputerAgent`` only ever sees a ``ComputerEnv``: it reads the current
``task`` string, takes a ``screenshot()``, and applies an ``InputEvent`` via
``step()`` (which returns a ``StepResult``). It has no idea whether the screen
behind the interface is a game, a web browser, or a real desktop.

This package contains ZERO Holo/agent knowledge — no tool definitions, no
structured-output schema. The agent's action vocabulary lives entirely on the
Agent side (``holo_agent.tools``); the only thing that crosses this boundary is
``InputEvent(tool_name, params)``, which the environment dispatches on. To target
a new environment, implement ``ComputerEnv`` there — the agent code does not
change, and the environment never imports the agent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from PIL import Image


@dataclass
class InputEvent:
    """A task-agnostic input event produced by the agent.

    ``tool_name`` is the action kind (e.g. "click", "write", "press_key",
    "hotkey", "scroll", "drag", "wait", "answer"). ``params`` carries the
    arguments; any coordinate fields (x, y, to_x, to_y) have ALREADY been
    scaled from the model's [0,1000] space to pixels by the agent loop, using
    the environment's screen size. The environment dispatches on ``tool_name``
    and interprets ``params`` however it needs (key mapping, pyautogui, etc.).

    Backwards-compatible convenience: ``type``/``key``/``x``/``y`` are still
    accepted and map onto tool_name/params, so existing game code keeps working.
    """

    tool_name: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    # Legacy fields (still supported for the game adapter).
    type: Optional[str] = None
    key: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None

    def __post_init__(self) -> None:
        # Map legacy (type/key/x/y) construction onto tool_name/params.
        if not self.tool_name and self.type is not None:
            if self.type == "key":
                self.tool_name = "press_key"
                self.params = {"key": self.key}
            elif self.type == "click":
                self.tool_name = "click"
                self.params = {"x": self.x, "y": self.y}
        # Mirror params back onto convenience attrs for click/key consumers.
        if self.tool_name == "press_key" and self.key is None:
            self.key = self.params.get("key")
        if self.tool_name in ("click", "double_click", "right_click"):
            if self.x is None:
                self.x = self.params.get("x")
            if self.y is None:
                self.y = self.params.get("y")

    def describe(self) -> str:
        if self.tool_name == "press_key":
            return f'press_key("{self.params.get("key")}")'
        if self.tool_name in ("click", "double_click", "right_click"):
            return f"{self.tool_name}({self.params.get('x')}, {self.params.get('y')})"
        return f"{self.tool_name}({self.params})"


@dataclass
class StepResult:
    """Result of applying one ``InputEvent`` to a ``ComputerEnv``.

    ``done`` — whether the episode/task has terminated as a consequence.
    ``info`` — free-form per-step details (reward, the executed command, a
    ``tool_output`` string the agent feeds back into the conversation, etc.).
    """

    done: bool = False
    info: dict[str, Any] = field(default_factory=dict)


class ComputerEnv(ABC):
    """Abstract computer-use environment the agent operates against."""

    #: Natural-language goal for the current task. Injected by the environment
    #: (and overridable by the user). The agent reads this; it is the ONLY
    #: task-specific information the agent receives.
    task: str = ""

    @abstractmethod
    def screenshot(self) -> Image.Image:
        """Return the current screen as a PIL image."""

    @abstractmethod
    def step(self, event: InputEvent) -> StepResult:
        """Apply one input event; return a ``StepResult(done, info)``."""

    @abstractmethod
    def is_done(self) -> bool:
        """Whether the episode/task has terminated."""

    def screen_size(self) -> tuple[int, int]:
        """(width, height) in pixels of the current screenshot."""
        img = self.screenshot()
        return img.size
