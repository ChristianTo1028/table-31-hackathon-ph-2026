import os
import json
import logging
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ADO_ORG = os.getenv("ADO_ORG", "")
ADO_PROJECT = os.getenv("ADO_PROJECT", "")
ADO_PAT = os.getenv("ADO_PAT", "")
USE_MOCK = os.getenv("USE_MOCK", "false").lower() == "true"

MOCK_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "mock_ado_data.json")

BASE_URL = f"https://dev.azure.com/{ADO_ORG}/{ADO_PROJECT}/_apis"


def _load_mock_data() -> dict[str, Any]:
    """Load the mock ADO data from the local JSON file."""
    try:
        with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Mock data file not found at {MOCK_DATA_PATH}. "
            "Ensure mock_ado_data.json exists in the ghost-market-api directory."
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Mock data file at {MOCK_DATA_PATH} contains invalid JSON: {exc}"
        ) from exc


async def get_work_items(state: str = "Active") -> list[dict[str, Any]]:
    """Fetch active work items from ADO, falling back to mock data if needed."""
    if USE_MOCK or not ADO_PAT:
        logger.info("Using mock ADO data for work items.")
        data = _load_mock_data()
        items = data.get("work_items", [])
        return [item for item in items if item.get("state") == state]

    url = f"{BASE_URL}/wit/wiql?api-version=7.1"
    query = {
        "query": (
            f"SELECT [System.Id], [System.Title], [System.State], "
            f"[System.AssignedTo], [Microsoft.VSTS.Scheduling.RemainingWork] "
            f"FROM WorkItems WHERE [System.State] = '{state}'"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json=query,
                auth=("", ADO_PAT),
            )
            response.raise_for_status()
            return response.json().get("workItems", [])
    except httpx.HTTPError as exc:
        logger.warning("ADO request failed (%s). Falling back to mock data.", exc)
        data = _load_mock_data()
        items = data.get("work_items", [])
        return [item for item in items if item.get("state") == state]


async def get_teams() -> list[dict[str, Any]]:
    """Fetch teams from ADO, falling back to mock data if needed."""
    if USE_MOCK or not ADO_PAT:
        logger.info("Using mock ADO data for teams.")
        data = _load_mock_data()
        return data.get("teams", [])

    url = f"https://dev.azure.com/{ADO_ORG}/_apis/teams?api-version=7.1"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, auth=("", ADO_PAT))
            response.raise_for_status()
            return response.json().get("value", [])
    except httpx.HTTPError as exc:
        logger.warning("ADO teams request failed (%s). Falling back to mock data.", exc)
        data = _load_mock_data()
        return data.get("teams", [])
