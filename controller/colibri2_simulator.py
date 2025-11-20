"""
Colibri2 simulator for testing without XMPP/JVB
"""
from typing import List, Dict, Any


class Colibri2Simulator:
    """Simulates Colibri2 responses for testing"""

    def __init__(self):
        self.next_port = 50000
        self.next_ssrc = 1000000

    def allocate_forwarders(self, room: str, endpoints: List[Dict[str, str]]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Simulate allocation of RTP forwarders for endpoints.
        Returns (participants, session_meta)
        """
        participants = []

        for ep in endpoints:
            ep_id = ep["id"]
            ep_name = ep.get("name", "")

            # Allocate fake RTP endpoint
            port = self.next_port
            self.next_port += 2  # Skip ports for RTCP

            ssrc = self.next_ssrc
            self.next_ssrc += 1

            participants.append({
                "id": ep_id,
                "name": ep_name,
                "rtp_url": f"rtp://127.0.0.1:{port}",
                "ssrc": ssrc,
                "pt": 111,  # Opus
                "simulated": True
            })

        session_meta = {
            "simulated": True,
            "room": room,
            "endpoint_ids": [ep["id"] for ep in endpoints]
        }

        return participants, session_meta
