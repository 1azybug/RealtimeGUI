"""Generic, environment-agnostic trajectory recorder for the Holo agent.

Records exactly what crosses the agent loop — the observation the model saw and
what it produced (note / thought / structured tool_call / reasoning) — plus the
environment's per-step ``info`` dict, verbatim. It knows nothing about OSWorld,
games, or any specific environment; it just consumes the agent's ``on_step``
hook and the agent's own system prompt. Any runner (OSWorld, RealtimeGym, a new
environment) wires it in the same way and gets a consistent ``traj.jsonl`` +
observation screenshots that the HTML report (``holo_agent.report``) can replay.

Usage::

    rec = TrajectoryRecorder(out_dir)
    agent = HoloComputerAgent(..., on_step=rec.on_step)
    rec.dump_system_prompt(agent.system_prompt())
    agent.run()
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

from PIL import Image


class TrajectoryRecorder:
    """Writes ``traj.jsonl`` + per-step observation PNGs into ``out_dir``."""

    def __init__(self, out_dir: str) -> None:
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.traj_path = os.path.join(out_dir, "traj.jsonl")

    def dump_system_prompt(self, text: str) -> None:
        """Persist the exact system prompt the model was given (for inspection)."""
        with open(os.path.join(self.out_dir, "system_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(text or "")

    def on_step(self, step_idx: int, image: Image.Image, step: Any, info: Any, reasoning: str) -> None:
        """``HoloComputerAgent`` on_step hook: save the observation + one traj line.

        ``image`` is the screenshot the model saw this step; ``step`` is the parsed
        ``{note, thought, tool_call}``; ``info`` is the environment's StepResult
        info dict (recorded verbatim); ``reasoning`` is the model's reasoning_content.
        """
        ts = datetime.datetime.now().strftime("%Y%m%d@%H%M%S%f")
        img_name = f"step_{step_idx + 1}_{ts}.png"
        try:
            image.convert("RGB").save(os.path.join(self.out_dir, img_name))
        except Exception:  # noqa: BLE001 — never let logging break the run
            img_name = None

        tc = step.tool_call
        record = {
            "step_num": step_idx + 1,
            "timestamp": ts,
            "note": step.note,
            "thought": step.thought,
            "tool_name": tc.tool_name,
            "tool_call": tc.model_dump(),
            "reasoning": reasoning,
            "screenshot_file": img_name,
            "info": info if isinstance(info, dict) else {"value": info},
        }
        with open(self.traj_path, "a", encoding="utf-8") as f:
            # default=str keeps any non-JSON-serializable env info from breaking logging.
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
