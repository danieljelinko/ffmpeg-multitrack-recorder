import os
from typing import List, Dict, Any

import httpx


class Colibri2Client:
    """
    Minimal Colibri2 client skeleton.
    NOTE: Colibri2 payload formats can vary by JVB version. This client uses a generic JSON shape
    that matches the forwarder concept. Adjust the payload keys to match your deployment if JVB rejects them.
    """

    def __init__(self, base_url: str, ws_url: str | None = None, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self.timeout = timeout
        self.session = httpx.Client(timeout=timeout)

    def about(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/about")
        resp.raise_for_status()
        return resp.json()

    def allocate_audio_forwarders(self, room: str, endpoints: List[str]) -> Dict[str, Any]:
        """
        Attempt to allocate audio RTP forwarders for the given endpoints.
        Expected to return a dict containing session_id and per-endpoint RTP info.
        The payload is intentionally generic; adjust if your JVB expects different keys.
        """
        payload = {
            "conference": room,
            "endpoints": [{"id": ep, "media": ["audio"]} for ep in endpoints],
        }
        resp = self.session.post(f"{self.base_url}/forward", json=payload)
        resp.raise_for_status()
        return resp.json()

    def release(self, session_id: str) -> None:
        """
        Release previously allocated forwarders.
        """
        resp = self.session.delete(f"{self.base_url}/forward/{session_id}")
        resp.raise_for_status()


def build_colibri2_from_env() -> Colibri2Client:
    base_url = os.environ.get("JVB_COLIBRI2_URL")
    ws_url = os.environ.get("JVB_COLIBRI2_WS")
    if not base_url:
        raise ValueError("JVB_COLIBRI2_URL is required to use Colibri2 client")
    return Colibri2Client(base_url=base_url, ws_url=ws_url)
