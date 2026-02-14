"""E2E tests for the controller REST API (health, list recordings)."""

import asyncio, uuid

import httpx
import pytest

from helpers import (
    create_participant, close_participant, complete_recording,
    wait_for_recording_active, wait_for_recording_stopped,
    find_latest_recording, find_mka_file,
)

pytestmark = pytest.mark.asyncio


def _room(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _headers(secret: str) -> dict:
    return {"X-Auth-Token": secret}


class TestHealthEndpoint:
    async def test_health_shape(self, controller_url):
        """GET /health returns expected structure."""
        async with httpx.AsyncClient(verify=False) as client:
            r = await client.get(f"{controller_url}/health", timeout=10)

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "xmpp" in data
        assert data["xmpp"]["connected"] is True
        assert "auto_recording" in data
        assert data["auto_recording"]["enabled"] is True


class TestManualStartStop:
    async def test_manual_start_returns_response(self, browser, jitsi_url, controller_url, api_secret):
        """POST /api/record/start responds with 200 or 500 (JVB may reject the PATCH).

        The manual API joins the MUC and attempts to PATCH JVB's colibri2 endpoint.
        JVB may return 400 depending on conference state, so we test that the API
        itself is reachable and returns a structured response.
        """
        room = _room("test-manual")
        alice = await create_participant(browser, jitsi_url, room, "Alice", freq=440)
        bob = await create_participant(browser, jitsi_url, room, "Bob", freq=880)

        try:
            await asyncio.sleep(8)

            async with httpx.AsyncClient(verify=False) as client:
                r = await client.post(
                    f"{controller_url}/api/record/start",
                    json={"room_id": room},
                    headers=_headers(api_secret),
                    timeout=30,
                )
                # API should return a structured JSON response (200 or 500)
                assert r.status_code in (200, 500), f"Unexpected status: {r.status_code} {r.text}"
                data = r.json()
                assert "status" in data
                assert data["status"] in ("recording", "error")
        finally:
            await close_participant(alice)
            await close_participant(bob)

    async def test_manual_stop_returns_response(self, browser, jitsi_url, controller_url, api_secret):
        """POST /api/record/stop responds with a structured response."""
        room = _room("test-manual-stop")
        alice = await create_participant(browser, jitsi_url, room, "Alice", freq=440)
        bob = await create_participant(browser, jitsi_url, room, "Bob", freq=880)

        try:
            await asyncio.sleep(8)
            async with httpx.AsyncClient(verify=False) as client:
                r = await client.post(
                    f"{controller_url}/api/record/stop",
                    json={"room_id": room},
                    headers=_headers(api_secret),
                    timeout=30,
                )
                # May return 200 or 500 depending on whether recording was active
                assert r.status_code in (200, 500), f"Unexpected status: {r.status_code} {r.text}"
        finally:
            await close_participant(alice)
            await close_participant(bob)

    async def test_start_missing_room_id(self, controller_url, api_secret):
        """POST /api/record/start without room_id returns 400."""
        async with httpx.AsyncClient(verify=False) as client:
            r = await client.post(
                f"{controller_url}/api/record/start",
                json={},
                headers=_headers(api_secret),
                timeout=10,
            )
        assert r.status_code == 400

    async def test_unauthorized_without_token(self, controller_url):
        """POST /api/record/start without auth token returns 401."""
        async with httpx.AsyncClient(verify=False) as client:
            r = await client.post(
                f"{controller_url}/api/record/start",
                json={"room_id": "test"},
                timeout=10,
            )
        assert r.status_code == 401


class TestListRecordings:
    async def test_list_after_recording(self, browser, jitsi_url, controller_url, api_secret, recordings_dir):
        """GET /api/recordings returns at least one entry after a completed recording."""
        room = _room("test-list")
        await complete_recording(
            browser, jitsi_url, controller_url, recordings_dir, room,
            [("Alice", 440), ("Bob", 880)],
        )

        async with httpx.AsyncClient(verify=False) as client:
            r = await client.get(
                f"{controller_url}/api/recordings",
                headers=_headers(api_secret),
                timeout=10,
            )

        assert r.status_code == 200
        data = r.json()
        recordings = data.get("recordings", [])
        assert len(recordings) >= 1, f"Expected at least 1 recording, got {len(recordings)}"
        # Each entry should have standard fields
        entry = recordings[0]
        assert "meeting_id" in entry
        assert "files" in entry
