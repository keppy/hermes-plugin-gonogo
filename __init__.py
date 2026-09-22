"""gonogo plugin — a deployment decision for a pilot-scale eval score.

Registers three tools and one bundled skill. No hooks, no network, no
credentials: every call reads a results file the caller points at and returns
gonogo's verdict.
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    from . import schemas, tools
except ImportError:  # pragma: no cover - pytest imports the plugin root as a top-level module
    import schemas  # type: ignore
    import tools  # type: ignore

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent / "skills"


def register(ctx):
    """Wire the three schemas to their handlers and register the bundled skill."""
    ctx.register_tool(name="gonogo_decide", toolset="gonogo",
                      schema=schemas.GONOGO_DECIDE, handler=tools.gonogo_decide)
    ctx.register_tool(name="gonogo_report", toolset="gonogo",
                      schema=schemas.GONOGO_REPORT, handler=tools.gonogo_report)
    ctx.register_tool(name="gonogo_compare", toolset="gonogo",
                      schema=schemas.GONOGO_COMPARE, handler=tools.gonogo_compare)

    if _SKILLS_DIR.is_dir():
        for child in sorted(_SKILLS_DIR.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)