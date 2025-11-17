import os
from dataclasses import dataclass

@dataclass
class XMPPSettings:
    host: str
    port: int
    domain: str
    jid: str
    password: str
    bridge_muc: str
    mode: str  # "client" or "component"


def load_xmpp_settings() -> XMPPSettings:
    # Component mode wins if component secret/jid provided
    comp_secret = os.environ.get("XMPP_COMPONENT_SECRET")
    comp_jid = os.environ.get("XMPP_COMPONENT_JID")
    if comp_secret and comp_jid:
        host = os.environ.get("XMPP_COMPONENT_HOST") or "xmpp.meet.jitsi"
        port = int(os.environ.get("XMPP_COMPONENT_PORT", "5347"))
        domain = os.environ.get("XMPP_DOMAIN") or "meet.jitsi"
        bridge_muc = os.environ.get("JVB_BRIDGE_MUC", "jvbbrewery@internal-muc.meet.jitsi")
        return XMPPSettings(
            host=host,
            port=port,
            domain=domain,
            jid=comp_jid,
            password=comp_secret,
            bridge_muc=bridge_muc,
            mode="component",
        )

    host = os.environ.get("XMPP_HOST") or os.environ.get("XMPP_SERVER") or "xmpp.meet.jitsi"
    port = int(os.environ.get("XMPP_PORT", "5222"))
    domain = os.environ.get("XMPP_DOMAIN") or "meet.jitsi"
    jid = os.environ.get("XMPP_JID")
    password = os.environ.get("XMPP_PASSWORD")
    bridge_muc = os.environ.get("JVB_BRIDGE_MUC", "jvbbrewery@internal-muc.meet.jitsi")
    if not jid or not password:
        raise ValueError("XMPP_JID and XMPP_PASSWORD (or component creds) are required")
    return XMPPSettings(
        host=host,
        port=port,
        domain=domain,
        jid=jid,
        password=password,
        bridge_muc=bridge_muc,
        mode="client",
    )
