"""
Distress Agent — polls ADO for stalled / at-risk work items and emits
DistressSignal events so the Ghost Market Hub can broadcast them.
"""

import logging
from typing import Any

from pydantic import BaseModel

from utils.ado_client import get_work_items

logger = logging.getLogger(__name__)

# Hours threshold below which a work item is considered "in distress"
DISTRESS_HOURS_THRESHOLD = 8

# Mapping from ADO area path keywords → required skill label
SKILL_MAP: dict[str, str] = {
    "backend": "Backend",
    "frontend": "Frontend",
    "devops": "DevOps",
    "qa": "QA",
    "ux": "UX",
    "design": "UX",
}


def _sanitize_team_id(raw: str) -> str:
    """Convert a team name to a URL-safe, lowercase ID (e.g. 'Team Alpha' → 'team-alpha')."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


class DistressSignal(BaseModel):
    team_id: str
    pbi_id: int
    required_skill: str
    hours_needed: int


def _infer_skill(work_item: dict[str, Any]) -> str:
    """Guess the required skill from the work item title or area path."""
    title = (work_item.get("title") or "").lower()
    for keyword, skill in SKILL_MAP.items():
        if keyword in title:
            return skill
    # Fallback: use the explicit field if present (from mock data)
    return work_item.get("required_skill", "General")


async def poll_distress_signals() -> list[DistressSignal]:
    """
    Poll ADO for active work items and return those that need help
    (i.e., remaining hours exceed the distress threshold).
    """
    work_items = await get_work_items(state="Active")
    signals: list[DistressSignal] = []

    for item in work_items:
        remaining = item.get("remaining_hours", 0) or 0
        if remaining >= DISTRESS_HOURS_THRESHOLD:
            signal = DistressSignal(
                team_id=_sanitize_team_id(str(item.get("assigned_to") or "unassigned")),
                pbi_id=int(item.get("id", 0)),
                required_skill=_infer_skill(item),
                hours_needed=remaining,
            )
            signals.append(signal)
            logger.info("Distress signal detected: %s", signal)

    return signals
