"""
Provider Agent — scores teams against open distress signals and returns
ranked provider offers for the Ghost Market Hub to broadcast.
"""

import logging
from typing import Any

from pydantic import BaseModel

from agents.distress import DistressSignal
from utils.ado_client import get_teams

logger = logging.getLogger(__name__)


class ProviderOffer(BaseModel):
    team_id: str
    team_name: str
    pbi_id: int
    skill_match: str
    available_hours: int
    score: float  # 0.0 – 1.0, higher is better


def _score_team(team: dict[str, Any], signal: DistressSignal) -> float:
    """
    Simple scoring heuristic:
      - +0.6 if the team has the required skill
      - +0.4 proportional to available hours vs hours needed (capped at 1.0)
    """
    skills: list[str] = [s.lower() for s in team.get("skills", [])]
    available: int = team.get("available_hours", 0)

    skill_score = 0.6 if signal.required_skill.lower() in skills else 0.0
    hours_score = 0.4 * min(available / max(signal.hours_needed, 1), 1.0)
    return round(skill_score + hours_score, 4)


async def find_providers(signals: list[DistressSignal]) -> list[ProviderOffer]:
    """
    For each distress signal, find teams that can help and rank them by score.
    Returns a flat list of ProviderOffer objects (all signals combined).
    """
    if not signals:
        return []

    teams = await get_teams()
    offers: list[ProviderOffer] = []

    for signal in signals:
        for team in teams:
            score = _score_team(team, signal)
            if score > 0:
                offer = ProviderOffer(
                    team_id=team.get("team_id", ""),
                    team_name=team.get("name", ""),
                    pbi_id=signal.pbi_id,
                    skill_match=signal.required_skill,
                    available_hours=team.get("available_hours", 0),
                    score=score,
                )
                offers.append(offer)
                logger.info("Provider offer: %s", offer)

    # Sort by score descending so the best matches come first
    offers.sort(key=lambda o: o.score, reverse=True)
    return offers
