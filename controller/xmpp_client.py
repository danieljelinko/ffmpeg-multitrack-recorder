import asyncio
import os
from typing import Dict, Any, List, Optional, Callable

from slixmpp import ClientXMPP
from slixmpp.xmlstream import ET, register_stanza_plugin


class Colibri2IQ:
    """
    Lightweight Colibri2 IQ builder/parser.
    NOTE: This is a placeholder; real Colibri2 stanza structure should be aligned to the deployed jitsi-xmpp-extensions version.
    """

    NAMESPACE = "urn:xmpp:colibri2"

    @staticmethod
    def build_allocate(conference_id: str, endpoint_id: str) -> ET.Element:
        iq = ET.Element("{jabber:client}iq", {"type": "set"})
        colibri = ET.SubElement(iq, f"{{{Colibri2IQ.NAMESPACE}}}conference", {"id": conference_id})
        ET.SubElement(colibri, "endpoint", {"id": endpoint_id})
        ET.SubElement(colibri, "media", {"type": "audio"})
        return iq


class XMPPBot(ClientXMPP):
    def __init__(self, jid: str, password: str, bridge_muc: str, logger: Optional[Callable[[str], None]] = None):
        super().__init__(jid, password)
        self.bridge_muc = bridge_muc
        self.logger = logger or (lambda msg: None)
        self.bridge_jid: Optional[str] = None
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("muc::%s::got_online" % bridge_muc, self.muc_online)

    async def start(self, event):
        self.logger("XMPP session started")
        self.send_presence()
        await self.get_roster()
        try:
            self.plugin["xep_0045"].join_muc(self.bridge_muc, self.boundjid.user, wait=True)
        except Exception as e:
            self.logger(f"Failed to join bridge MUC: {e}")

    def muc_online(self, presence):
        occupant = presence["muc"]["jid"]
        if occupant and occupant.bare and "@internal" in occupant.bare:
            self.bridge_jid = occupant.bare
            self.logger(f"Discovered bridge JID: {self.bridge_jid}")

    async def allocate_forwarder(self, conference_id: str, endpoint_id: str) -> Dict[str, Any]:
        if not self.bridge_jid:
            raise RuntimeError("Bridge JID not discovered")
        iq = Colibri2IQ.build_allocate(conference_id, endpoint_id)
        iq.attrib["to"] = self.bridge_jid
        result = await self._send_iq_async(iq)
        # Placeholder parse: adapt to real response
        return {"id": endpoint_id, "bridge_jid": self.bridge_jid, "payload": result}

    async def _send_iq_async(self, iq_elem: ET.Element) -> ET.Element:
        future = self.Iq()
        future.append(iq_elem[0])
        future["to"] = iq_elem.attrib.get("to")
        future["type"] = "set"
        resp = await future.send()
        return resp.xml


def create_xmpp_bot_from_env(logger: Optional[Callable[[str], None]] = None) -> XMPPBot:
    jid = os.environ.get("XMPP_JID")
    password = os.environ.get("XMPP_PASSWORD") or os.environ.get("XMPP_COMPONENT_SECRET")
    bridge_muc = os.environ.get("JVB_BRIDGE_MUC", "jvbbrewery@internal-muc.meet.jitsi")
    if not jid or not password:
        raise ValueError("XMPP_JID and XMPP_PASSWORD (or XMPP_COMPONENT_SECRET) are required")
    return XMPPBot(jid=jid, password=password, bridge_muc=bridge_muc, logger=logger)
