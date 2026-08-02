"""Package-level access to rendering and fitting."""

from render import (
    RenderError,
    ensure_tectonic,
    fit_to_one_page,
    render,
    scored_to_plain,
)

__all__ = [
    "RenderError",
    "ensure_tectonic",
    "fit_to_one_page",
    "render",
    "scored_to_plain",
]
