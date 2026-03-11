import logging
import os
from typing import Any

import pusher
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.distress import DistressSignal, poll_distress_signals
from agents.provider import ProviderOffer, find_providers

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Ghost Market Hub",
    description=(
        "Central FastAPI hub that receives data from Distress and Provider agents "
        "and broadcasts events to the Pusher 'ghost-market' channel."
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Pusher client (replace env vars with real credentials or set in .env)
# ---------------------------------------------------------------------------
PUSHER_CHANNEL = "ghost-market"

_pusher_app_id = os.getenv("PUSHER_APP_ID", "")
_pusher_key = os.getenv("PUSHER_KEY", "")
_pusher_secret = os.getenv("PUSHER_SECRET", "")
_pusher_cluster = os.getenv("PUSHER_CLUSTER", "")

_pusher_configured = all([_pusher_app_id, _pusher_key, _pusher_secret, _pusher_cluster])

pusher_client: pusher.Pusher | None = None
if _pusher_configured:
    pusher_client = pusher.Pusher(
        app_id=_pusher_app_id,
        key=_pusher_key,
        secret=_pusher_secret,
        cluster=_pusher_cluster,
        ssl=True,
    )
else:
    logger.warning(
        "Pusher credentials not configured. Set PUSHER_APP_ID, PUSHER_KEY, "
        "PUSHER_SECRET, and PUSHER_CLUSTER in your .env file. "
        "Broadcast calls will be no-ops until credentials are provided."
    )


def _trigger(channel: str, event: str, data: dict) -> None:
    """Emit a Pusher event, or log a warning if Pusher is not configured."""
    if pusher_client is not None:
        pusher_client.trigger(channel, event, data)
    else:
        logger.warning(
            "Pusher not configured — skipping trigger: channel=%s event=%s", channel, event
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AgentMessage(BaseModel):
    agent_type: str  # "Distress" or "Provider"
    team: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", tags=["Health"])
async def root() -> dict[str, str]:
    """Health check — confirms the hub is running."""
    return {"status": "Ghost Market Hub is live 👻"}


@app.post("/broadcast", tags=["Market"])
async def broadcast_to_market(msg: AgentMessage) -> dict[str, str]:
    """
    Generic broadcast endpoint.

    Accepts an AgentMessage and pushes it to the 'ghost-market' Pusher channel
    under the 'market-event' event name.
    """
    _trigger(PUSHER_CHANNEL, "market-event", msg.model_dump())
    logger.info("Broadcasted market-event: agent=%s team=%s", msg.agent_type, msg.team)
    return {"status": "Message Sent to Market"}


@app.post("/broadcast/distress", tags=["Market"])
async def broadcast_distress(signal: DistressSignal) -> dict[str, str]:
    """
    Broadcast a single Distress Signal directly to the Ghost Market.

    This endpoint is the 'secret weapon' you can hit from Swagger /docs
    to manually trigger a distress event without any frontend code.
    """
    _trigger(PUSHER_CHANNEL, "new-signal", signal.model_dump())
    logger.info("Broadcasted distress signal: %s", signal)
    return {"status": "Broadcasted"}


@app.post("/agents/run", tags=["Agents"])
async def run_agents() -> dict[str, Any]:
    """
    Trigger the full agent pipeline:
      1. Distress Agent polls ADO for at-risk work items.
      2. Provider Agent scores teams against each distress signal.
      3. Both results are broadcast to Pusher.

    Returns a summary of what was found and broadcast.
    """
    try:
        signals = await poll_distress_signals()
    except Exception as exc:
        logger.exception("Distress agent failed.")
        raise HTTPException(status_code=500, detail=f"Distress agent error: {exc}") from exc

    try:
        offers = await find_providers(signals)
    except Exception as exc:
        logger.exception("Provider agent failed.")
        raise HTTPException(status_code=500, detail=f"Provider agent error: {exc}") from exc

    # Broadcast distress signals
    for signal in signals:
        _trigger(PUSHER_CHANNEL, "new-signal", signal.model_dump())

    # Broadcast provider offers
    for offer in offers:
        _trigger(PUSHER_CHANNEL, "provider-offer", offer.model_dump())

    return {
        "distress_signals": [s.model_dump() for s in signals],
        "provider_offers": [o.model_dump() for o in offers],
    }


@app.get("/agents/distress", tags=["Agents"])
async def get_distress_signals() -> list[dict[str, Any]]:
    """Poll ADO and return current distress signals (read-only, no broadcast)."""
    signals = await poll_distress_signals()
    return [s.model_dump() for s in signals]


@app.get("/agents/providers", tags=["Agents"])
async def get_provider_offers() -> list[dict[str, Any]]:
    """Return provider offers for all current distress signals (read-only, no broadcast)."""
    signals = await poll_distress_signals()
    offers = await find_providers(signals)
    return [o.model_dump() for o in offers]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Use 127.0.0.1 for local development. Change to "0.0.0.0" only in a
    # containerised / production environment behind a reverse proxy.
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
