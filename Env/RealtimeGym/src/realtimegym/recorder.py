"""MP4 trajectory recorder for RealtimeGym GUI / computer-use mode.

Wraps imageio (+imageio-ffmpeg) to write each composite frame to an MP4, with
a small info banner overlaid on top showing the turn number, the action taken,
and whether it came from the agent or a human. Lets us replay and inspect a
full episode after the fact.
"""

from __future__ import annotations

from typing import Optional

import imageio.v2 as imageio
import numpy as np
import pygame

_BANNER_H = 30
_BANNER_BG = (0, 0, 0)
_BANNER_FG = (0, 255, 120)


class TrajectoryRecorder:
    """Collects annotated frames and writes them to an MP4 on close."""

    def __init__(self, path: str, fps: int = 2) -> None:
        self.path = path
        self.fps = fps
        self._frames: list[np.ndarray] = []
        self._font: Optional[pygame.font.Font] = None

    def _ensure_font(self) -> pygame.font.Font:
        if self._font is None:
            if not pygame.font.get_init():
                pygame.font.init()
            self._font = pygame.font.Font(None, 26)
        return self._font

    def add(
        self,
        frame: pygame.Surface,
        turn: int,
        action: str,
        source: str = "agent",
        raw_event: str = "",
    ) -> None:
        """Add one composite frame with an info banner on top."""
        w, h = frame.get_size()
        canvas = pygame.Surface((w, h + _BANNER_H))
        canvas.fill(_BANNER_BG)
        canvas.blit(frame, (0, _BANNER_H))

        font = self._ensure_font()
        info = f"Turn {turn} | action: {action} | {source}"
        if raw_event:
            info += f" | {raw_event}"
        text = font.render(info, True, _BANNER_FG)
        canvas.blit(text, (8, 4))

        arr = pygame.surfarray.array3d(canvas).swapaxes(0, 1)
        self._frames.append(arr.astype(np.uint8))

    def close(self) -> None:
        """Write all collected frames to the MP4 file."""
        if not self._frames:
            return
        # macro_block_size=1 avoids ffmpeg resizing odd dimensions.
        with imageio.get_writer(
            self.path, fps=self.fps, macro_block_size=1, codec="libx264"
        ) as writer:
            for arr in self._frames:
                writer.append_data(arr)
