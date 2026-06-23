"""Control-panel renderer for RealtimeGym GUI / computer-use mode.

Takes a rendered game Surface and appends a row of clickable action buttons
below it, producing the composite frame shown to the agent, recorded to video,
and displayed to a human player. Button geometry comes from
``io_layer.button_layout`` so the drawn buttons and the click hit-testing are
guaranteed to match.
"""

from __future__ import annotations

import pygame

from ...io_layer import PANEL_HEIGHT, button_layout, button_specs

_BG = (28, 28, 30)
_BTN = (60, 63, 70)
_BTN_BORDER = (120, 124, 132)
_TEXT = (235, 235, 235)


def compose_frame(surface: pygame.Surface, game: str) -> pygame.Surface:
    """Return a new Surface = game image + action-button control bar below it.

    The button labels (e.g. "W  Up", "Space  Stay") tell both the model and a
    human which key / button maps to which action.
    """
    game_w, game_h = surface.get_size()
    out = pygame.Surface((game_w, game_h + PANEL_HEIGHT))
    out.fill(_BG)
    out.blit(surface, (0, 0))

    layout = button_layout(game, game_w, game_h)
    specs = dict(button_specs(game))
    font = pygame.font.Font(None, 24)

    for action_char, (bx, by, bw, bh) in layout.items():
        rect = pygame.Rect(bx, by, bw, bh)
        pygame.draw.rect(out, _BTN, rect, border_radius=8)
        pygame.draw.rect(out, _BTN_BORDER, rect, width=2, border_radius=8)
        label = specs.get(action_char, action_char)
        text = font.render(label, True, _TEXT)
        text_rect = text.get_rect(center=rect.center)
        out.blit(text, text_rect)

    return out
