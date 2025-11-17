import os
from typing import List, Dict, Any

import httpx


class Colibri2Client:
    """
    Minimal Colibri2 client skeleton.
    Note: Exact payloads depend on JVB version; this client is intentionally thin and may need adjustment per deployment.
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

    def allocate_audio_forwarders(self, room: str, endpoints: List[str]) -> List[Dict[str, Any]]:
        """
        Placeholder for allocating audio forwarders per endpoint.
        Real payloads vary; this returns a stub to be adapted to your JVB build.
        """
        raise NotImplementedError("Colibri2 forwarder allocation must be implemented for your JVB version.")

    def release(self, session_id: str) -> None:
        """
        Placeholder for releasing forwarders.
        """
        raise NotImplementedError("Colibri2 release must be implemented for your JVB version.")


def build_colibri2_from_env() -> Colibri2Client:
    base_url = os.environ.get("JVB_COLIBRI2_URL")
    ws_url = os.environ.get("JVB_COLIBRI2_WS")
    if not base_url:
        raise ValueError("JVB_COLIBRI2_URL is required to use Colibri2 client")
    return Colibri2Client(base_url=base_url, ws_url=ws_url)
