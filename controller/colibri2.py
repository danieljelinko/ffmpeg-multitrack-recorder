import os
from typing import List, Dict, Any, Optional

import httpx


class Colibri2Client:
    """
    Minimal Colibri2 client skeleton.
    NOTE: Colibri2 payload formats can vary by JVB version. This client uses a generic JSON shape
    that matches the forwarder concept. Adjust the payload keys to match your deployment if JVB rejects them.
    """

    def __init__(self, base_url: str, ws_url: str | None = None, timeout: float = 5.0, simulate: bool = False):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self.timeout = timeout
        self.simulate = simulate
        self.session = httpx.Client(timeout=timeout) if not simulate else None

    def about(self) -> Dict[str, Any]:
        if self.simulate:
            return {"simulate": True}
        resp = self.session.get(f"{self.base_url}/about")
        resp.raise_for_status()
        return resp.json()

    def allocate_audio_forwarders(self, room: str, endpoints: List[str]) -> Dict[str, Any]:
        """
        Attempt to allocate audio RTP forwarders for the given endpoints.
        Expected to return a dict containing session_id and per-endpoint RTP info.
        The payload is intentionally generic; adjust if your JVB expects different keys.
        """
        if self.simulate:
            base_port = int(os.environ.get("COLIBRI2_SIM_PORT_BASE", "50000"))
            eps = []
            for idx, ep in enumerate(endpoints):
                port = base_port + idx * 2
                eps.append({"id": ep, "audio": {"ip": "127.0.0.1", "port": port, "ssrc": 12345 + idx}})
            return {"session_id": "simulated-session", "endpoints": eps}

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
        if self.simulate:
            return
        resp = self.session.delete(f"{self.base_url}/forward/{session_id}")
        resp.raise_for_status()


def build_colibri2_from_env() -> Colibri2Client:
    base_url = os.environ.get("JVB_COLIBRI2_URL")
    ws_url = os.environ.get("JVB_COLIBRI2_WS")
    simulate = os.environ.get("COLIBRI2_SIMULATE", "0") == "1"
    if simulate:
        base_url = base_url or "http://colibri2-sim"
    if not base_url:
        raise ValueError("JVB_COLIBRI2_URL is required to use Colibri2 client")
    return Colibri2Client(base_url=base_url, ws_url=ws_url, simulate=simulate)
