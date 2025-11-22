import asyncio
import json
import logging
import os
from typing import Dict, Any, Optional, Callable, List

import requests
import slixmpp
from slixmpp import ClientXMPP, ComponentXMPP
from slixmpp.xmlstream import ET
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.media import MediaBlackhole

from xmpp_config import XMPPSettings, load_xmpp_settings
from jingle_sdp import jingle_to_sdp, sdp_to_jingle_accept, extract_ssrcs_from_jingle


class Colibri2IQ:
    """
    Colibri2 IQ builder/parser for jitsi-videobridge stable-10590.
    Implements conference-modify/conference-modified IQ stanzas.
    """

    # Based on jitsi-xmpp-extensions Colibri2 namespace
    NAMESPACE = "urn:xmpp:jitsi-videobridge:colibri2"
    ICE_UDP_NS = "urn:xmpp:jingle:transports:ice-udp:1"
    SOURCES_NS = "urn:xmpp:jitsi:colibri2:sources"

    @staticmethod
    def build_allocate(conference_id: str, endpoint_id: str) -> ET.Element:
        """
        Build a conference-modify IQ to allocate an audio endpoint.

        This requests JVB to create/allocate an endpoint with audio media
        and transport configured for receiving RTP.
        """
        iq = ET.Element("{jabber:client}iq", {"type": "set"})

        # conference-modify element with meeting-id and create flag
        conf_modify = ET.SubElement(
            iq,
            f"{{{Colibri2IQ.NAMESPACE}}}conference-modify",
            {
                "meeting-id": conference_id,
                "create": "true"
            }
        )

        # endpoint element
        endpoint = ET.SubElement(
            conf_modify,
            f"{{{Colibri2IQ.NAMESPACE}}}endpoint",
            {
                "id": endpoint_id,
                "create": "true"
            }
        )

        # media element for audio
        media = ET.SubElement(
            endpoint,
            f"{{{Colibri2IQ.NAMESPACE}}}media",
            {"type": "audio"}
        )

        # Add common Opus payload type
        ET.SubElement(
            media,
            f"{{{Colibri2IQ.NAMESPACE}}}payload-type",
            {
                "id": "111",
                "name": "opus",
                "clockrate": "48000",
                "channels": "2"
            }
        )

        # transport element (required for RTP forwarders)
        transport = ET.SubElement(
            endpoint,
            f"{{{Colibri2IQ.NAMESPACE}}}transport"
        )

        return iq

    @staticmethod
    def parse_allocate_response(response_xml: ET.Element) -> Dict[str, Any]:
        """
        Parse conference-modified IQ response from JVB.

        Extracts IP, port, SSRC, and payload type from the response.
        """
        # Find conference-modified element
        conf_modified = response_xml.find(f".//{{{Colibri2IQ.NAMESPACE}}}conference-modified")
        if conf_modified is None:
            raise ValueError("No conference-modified element in response")

        # Find endpoint
        endpoint = conf_modified.find(f".//{{{Colibri2IQ.NAMESPACE}}}endpoint")
        if endpoint is None:
            raise ValueError("No endpoint in response")

        endpoint_id = endpoint.get("id")

        # Extract transport info - look for ICE candidate
        candidate = endpoint.find(f".//{{{Colibri2IQ.ICE_UDP_NS}}}candidate")
        if candidate is not None:
            ip = candidate.get("ip")
            port = int(candidate.get("port"))
        else:
            # Fallback: try to find transport with relay info
            transport = endpoint.find(f".//{{{Colibri2IQ.NAMESPACE}}}transport")
            # If no candidate, this might be a relay or we need to handle differently
            ip = "127.0.0.1"  # Default fallback
            port = 50000  # Default fallback

        # Extract SSRC from sources
        ssrc = None
        source = endpoint.find(f".//{{{Colibri2IQ.SOURCES_NS}}}source")
        if source is not None:
            ssrc_str = source.get("id")
            if ssrc_str:
                try:
                    ssrc = int(ssrc_str)
                except ValueError:
                    pass

        # Extract payload type
        pt = 111  # Default Opus
        payload_type = endpoint.find(f".//{{{Colibri2IQ.NAMESPACE}}}payload-type")
        if payload_type is not None:
            pt_str = payload_type.get("id")
            if pt_str:
                try:
                    pt = int(pt_str)
                except ValueError:
                    pass

        return {
            "endpoint_id": endpoint_id,
            "ip": ip,
            "port": port,
            "ssrc": ssrc,
            "pt": pt
        }

    @staticmethod
    def build_release(conference_id: str, endpoint_id: str) -> ET.Element:
        """
        Build a conference-modify IQ to release/expire an endpoint.

        This requests JVB to remove an endpoint from a conference.
        """
        iq = ET.Element("{jabber:client}iq", {"type": "set"})

        # conference-modify element with meeting-id (no create flag)
        conf_modify = ET.SubElement(
            iq,
            f"{{{Colibri2IQ.NAMESPACE}}}conference-modify",
            {"meeting-id": conference_id}
        )

        # endpoint element with expire flag
        ET.SubElement(
            conf_modify,
            f"{{{Colibri2IQ.NAMESPACE}}}endpoint",
            {
                "id": endpoint_id,
                "expire": "true"
            }
        )

        return iq


class XMPPBot(ClientXMPP):
    def __init__(self, settings: XMPPSettings, logger: Optional[Callable[[str], None]] = None):
        super().__init__(settings.jid, settings.password)
        self.settings = settings
        self.logger = logger or (lambda msg: None)
        self.bridge_jid: Optional[str] = None
        self.ready = asyncio.Event()  # Set when session_start fires and bridge discovered
        # Fix: Use asyncio.Future() instead of get_event_loop().create_future()
        # The loop will be set when the Future is created in async context
        self.disconnected: Optional[asyncio.Future] = None

        # Colibri protocol support flags (determined via XEP-0030 Service Discovery)
        self.supports_colibri_v1: bool = False
        self.supports_colibri_v2: bool = False

        # WebRTC peer connections (session ID → RTCPeerConnection)
        self.peer_connections: Dict[str, RTCPeerConnection] = {}

        # Conference participant tracking (room → participant_id → participant_data)
        # Structure: {
        #   "room-name@muc.meet.jitsi": {
        #     "participant-jid": {
        #       "jid": "room@conference/fullJID",
        #       "display_name": "John Doe",
        #       "stats_id": "abc123",
        #       "audio_muted": false,
        #       "video_muted": false,
        #       "joined_at": "2024-11-20T12:00:00Z",
        #       "ssrcs": {"audio": 12345, "video": 67890}
        #     }
        #   }
        # }
        self.conference_participants: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Map MUC room names to Colibri conference IDs (Bridge Session IDs)
        # This is required because JVB expects the UUID, not the MUC name
        self.conference_ids: Dict[str, str] = {}

        # JVB REST API configuration for multitrack recording
        self.jvb_rest_url = os.getenv("JVB_REST_URL", "http://jvb:8080")
        self.recorder_ws_url = os.getenv("RECORDER_WS_URL", "ws://recorder:8989/record")

        # Phase 3: Callback system for participant changes (join/leave)
        self.participant_change_callbacks: List[Callable] = []

        # Enable slixmpp XML stream logging for debugging
        # This will show all SEND/RECV stanzas including MUC join presence
        xmpp_logger = logging.getLogger('slixmpp')
        xmpp_logger.setLevel(logging.DEBUG)
        # Force explicit stream handler to ensure logs appear in FastAPI/Uvicorn
        if not xmpp_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('[%(name)s] %(levelname)s: %(message)s'))
            xmpp_logger.addHandler(handler)

        # Disable TLS certificate verification for development
        self.use_ipv6 = False
        self['feature_mechanisms'].unencrypted_plain = True

        # Register plugins before connecting
        self.register_plugin('xep_0030')  # Service Discovery
        self.register_plugin('xep_0045')  # MUC
        self.register_plugin('xep_0199')  # XMPP Ping
        
        # Register Jingle features so Jicofo knows we support media
        # This is critical for JVB allocation to succeed
        self['xep_0030'].add_feature('urn:xmpp:jingle:1')
        self['xep_0030'].add_feature('urn:xmpp:jingle:transports:ice-udp:1')
        self['xep_0030'].add_feature('urn:xmpp:jingle:apps:rtp:1')
        self['xep_0030'].add_feature('urn:xmpp:jingle:apps:rtp:audio')
        self['xep_0030'].add_feature('urn:xmpp:jingle:apps:rtp:video')
        self['xep_0030'].add_feature('urn:xmpp:jingle:apps:dtls:0')
        
        # Register Jibri feature to identify as a recorder
        # This tells Jicofo we are a Jibri, which changes allocation behavior
        self['xep_0030'].add_feature('http://jitsi.org/protocol/jibri')
        
        # Note: xep_0166 (Jingle) not available in Slixmpp 1.8.4
        # Using raw handler instead (see register_handler below)

        self.add_event_handler("session_start", self.on_session_start)
        self.add_event_handler("disconnected", self.on_disconnected)
        self.add_event_handler("muc::%s::got_online" % settings.bridge_muc, self.muc_online)

        # Register Jingle handler for session offers from Jicofo
        self.register_handler(
            slixmpp.Callback(
                'Jingle Session Initiate',
                slixmpp.MatchXPath("{jabber:client}iq/{urn:xmpp:jingle:1}jingle[@action='session-initiate']"),
                self._handle_jingle_session_initiate
            )
        )

        # Register Jingle transport-info handler for trickle ICE candidates
        self.register_handler(
            slixmpp.Callback(
                'Jingle Transport Info',
                slixmpp.MatchXPath("{jabber:client}iq/{urn:xmpp:jingle:1}jingle[@action='transport-info']"),
                self._handle_jingle_transport_info
            )
        )

        # Register handler for Colibri2 conference-modify (allocation requests)
        # This is critical to prevent Jicofo from timing out and kicking participants
        self.register_handler(
            slixmpp.Callback(
                'Colibri2 Conference Modify',
                slixmpp.MatchXPath("{jabber:client}iq/{urn:xmpp:jitsi-videobridge:colibri2}conference-modify"),
                self._handle_colibri2_conference_modify
            )
        )

    async def on_session_start(self, event):
        """Called when XMPP session is established"""
        self.logger("XMPP session_start")
        self.logger(f"Client JID: {self.boundjid}")
        self.send_presence()
        self.logger("Sent presence")
        await self.get_roster()
        self.logger("Got roster")

        # Join brewery MUC with timeout (blocking until confirmed or timeout)
        try:
            nick = self.settings.jid.split('@')[0]  # Use first part of JID as nick
            self.logger(f"Attempting to join MUC {self.settings.bridge_muc} as {nick}")

            # Fix: Use join_muc_wait() to wait for join confirmation
            # This will raise TimeoutError if join fails, converting silent failure to loud exception
            try:
                self.plugin["xep_0045"].join_muc(
                    self.settings.bridge_muc,
                    nick
                )
                self.logger(f"Successfully joined MUC {self.settings.bridge_muc}")
                # Roster check removed to avoid TypeError
                # Wait briefly for existing occupants' presence stanzas
                self.logger("Waiting for bridge discovery via muc_online events...")
                # Don't set ready yet - let muc_online handler set it when bridge is found

            except asyncio.TimeoutError:
                self.logger(f"TIMEOUT: MUC join did not complete within 10 seconds")
                self.logger("This indicates the MUC join request was not acknowledged by Prosody")
                # Don't set ready - the bot is not ready without MUC access
                raise

        except Exception as e:
            self.logger(f"Failed to join bridge MUC: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")
            # Don't set ready on error
            raise

    def on_disconnected(self, event=None):
        """Called when XMPP connection is lost"""
        self.logger("XMPP disconnected")
        if self.disconnected and not self.disconnected.done():
            self.disconnected.set_result(True)

    def muc_online(self, presence):
        """Called when a MUC occupant comes online"""
        occupant = presence["muc"]["jid"]
        # JVB typically appears as jvb@auth.meet.jitsi or jvb@internal...
        # Look for jvb in the username part of the JID
        if occupant and occupant.bare and occupant.bare.startswith("jvb@"):
            self.bridge_jid = occupant.bare
            self.logger(f"Discovered bridge JID: {self.bridge_jid}")
            
            # Log the full presence stanza to inspect for conference IDs
            self.logger(f"JVB Presence Payload: {presence}")
            self.logger(f"Presence Type: {type(presence)}")
            
            # Check for Colibri stats
            # Try accessing xml directly if find is missing
            try:
                if hasattr(presence, 'xml'):
                    stats = presence.xml.find("{http://jitsi.org/protocol/colibri}stats")
                elif hasattr(presence, 'find'):
                    stats = presence.find("{http://jitsi.org/protocol/colibri}stats")
                else:
                    stats = None
                    
                if stats is not None:
                    self.logger("Found Colibri stats in presence")
                    for stat in stats:
                        self.logger(f"Stat: {stat.attrib}")
            except Exception as e:
                self.logger(f"Error parsing stats: {e}")

            # Probe JVB capabilities to determine protocol support
            asyncio.create_task(self.check_bridge_capabilities())

            # Fix: Set ready event when bridge is discovered
            # This ensures ready is only set after successful MUC join AND bridge discovery
            if not self.ready.is_set():
                self.ready.set()
                self.logger("Bot ready event set (bridge discovered via muc_online)")

    async def check_bridge_capabilities(self):
        """
        Probe JVB capabilities using XEP-0030 Service Discovery.
        This definitively determines which Colibri protocol versions are supported.
        """
        if not self.bridge_jid:
            self.logger("⚠️  Cannot probe capabilities: No bridge JID")
            return

        self.logger(f"🔍 PROBING CAPABILITIES for {self.bridge_jid}...")
        try:
            # Send Disco#info query using XEP-0030
            info = await self['xep_0030'].get_info(jid=self.bridge_jid, timeout=5)

            # Extract all supported features
            features = info['disco_info']['features']
            self.logger(f"📋 JVB ADVERTISED FEATURES ({len(features)} total):")
            for feature in sorted(features):
                self.logger(f"   - {feature}")

            # Check specifically for Colibri protocol versions
            has_colibri_v1 = 'http://jitsi.org/protocol/colibri' in features
            has_colibri_v2 = 'urn:xmpp:jitsi-videobridge:colibri2' in features

            self.logger("")
            self.logger("=" * 70)
            self.logger("COLIBRI PROTOCOL SUPPORT MATRIX:")
            self.logger(f"  ✅ Colibri v1 (legacy): {has_colibri_v1}")
            self.logger(f"  {'✅' if has_colibri_v2 else '❌'} Colibri v2 (modern): {has_colibri_v2}")
            self.logger("=" * 70)
            self.logger("")

            # Store capabilities for use in allocation
            self.supports_colibri_v1 = has_colibri_v1
            self.supports_colibri_v2 = has_colibri_v2

            if not has_colibri_v2:
                self.logger("⚠️  WARNING: Colibri2 NOT supported by this JVB version!")
                self.logger("⚠️  Recorder will need to use Colibri v1 (legacy protocol)")

            if not has_colibri_v1 and not has_colibri_v2:
                self.logger("❌ CRITICAL: JVB supports NEITHER Colibri v1 nor v2!")
                self.logger("❌ Recording allocation will fail!")

        except asyncio.TimeoutError:
            self.logger("❌ Capability probe timed out (JVB not responding to disco#info)")
        except Exception as e:
            self.logger(f"❌ Capability probe failed: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")

    def _handle_jingle_session_initiate(self, iq):
        """
        Handler for incoming Jingle session-initiate IQ from another participant.
        Establishes WebRTC connection using aiortc.
        """
        # Schedule async handler (Jingle handler runs in non-async context)
        asyncio.create_task(self._handle_jingle_session_initiate_async(iq))

    async def _handle_jingle_session_initiate_async(self, iq):
        """
        Async handler for Jingle session-initiate. Establishes WebRTC connection.
        """
        self.logger("=" * 80)
        self.logger("🎉 RECEIVED JINGLE SESSION OFFER!")
        self.logger("=" * 80)

        try:
            # Extract Jingle element
            jingle = iq.xml.find('{urn:xmpp:jingle:1}jingle')
            if jingle is None:
                self.logger("❌ No jingle element found in IQ")
                return

            # DEBUG: Log raw Jingle XML to debug missing Bridge Session ID
            import xml.etree.ElementTree as ET
            raw_xml = ET.tostring(jingle, encoding='unicode')
            self.logger(f"📜 Raw Jingle XML: {raw_xml[:500]}...") # Log first 500 chars

            sid = jingle.get('sid')
            initiator = jingle.get('initiator')
            self.logger(f"Session ID: {sid}")
            self.logger(f"Initiator: {initiator}")

            # Extract Bridge Session ID (Colibri Conference ID)
            # Namespace: http://jitsi.org/protocol/focus
            bridge_session = jingle.find('{http://jitsi.org/protocol/focus}bridge-session')
            if bridge_session is not None:
                bs_id = bridge_session.get('id')
                if bs_id:
                    self.logger(f"✅ Discovered Bridge Session ID: {bs_id}")
                    # Store it for the room
                    # Use the IQ 'from' attribute to get the room JID (e.g. room@muc/focus)
                    iq_from = str(iq['from'])
                    if '@muc.' in iq_from:
                        room_name = iq_from.split('/')[0]
                        self.conference_ids[room_name] = bs_id
                        
                        # Also store short name mapping for API lookups
                        if "@" in room_name:
                            short_name = room_name.split("@")[0]
                            self.conference_ids[short_name] = bs_id
                            self.logger(f"   Mapped room {short_name} -> {bs_id}")
                            
                        self.logger(f"   Mapped room {room_name} -> {bs_id}")
                    else:
                        self.logger(f"⚠️ Could not extract room from IQ source: {iq_from}")

            # Extract SSRCs from Jingle offer (Phase 1.2: SSRC Discovery)
            ssrcs = extract_ssrcs_from_jingle(jingle)
            if ssrcs:
                self.logger(f"📊 Extracted SSRCs from {initiator}:")
                for media_type, ssrc_info in ssrcs.items():
                    self.logger(f"   {media_type}: SSRC={ssrc_info['ssrc']}, cname={ssrc_info.get('cname', 'N/A')}")
                
                # Map SSRC to participant in conference tracking
                # NOTE: In Jitsi, Jicofo (focus) sends Jingle offers on behalf of participants
                # so the initiator JID is usually "room@muc.domain/focus-id", not the participant
                participant_updated = False
                
                # Extract the room name from initiator MUC JID
                # initiator format: "testroom@muc.meet.jitsi/7ab5d390"
                if '@muc.' in initiator:
                    room_from_init = initiator.split('/')[0]  # "testroom@muc.meet.jitsi"
                    
                    if room_from_init in self.conference_participants:
                        participants = self.conference_participants[room_from_init]
                        
                        # Heuristic: Assign SSRCs to most recently joined participant without SSRCs
                        # This works because Jicofo sends session-initiate shortly after participant joins
                        self.logger(f"   Checking {len(participants)} participants for SSRC mapping...")
                        for jid in reversed(list(participants.keys())):
                            participant = participants[jid]
                            self.logger(f"   - Checking {jid} (ssrcs={bool(participant.get('ssrcs'))})")
                            
                            # Skip if this participant already has SSRCs or is focus/jibri
                            if participant.get('ssrcs') or 'focus' in jid or 'jibri' in jid or jid == 'recorder-bot':
                                self.logger(f"     Skipping {jid}")
                                continue
                            
                            # Assign SSRCs to this participant
                            participant['ssrcs'] = ssrcs
                            nick = participant.get('nick', jid)
                            self.logger(f"✅ Mapped SSRCs to participant {nick} (JID: {jid}) in room {room_from_init}")
                            participant_updated = True
                            
                            # Phase 1.3: Automatically allocate forwarder for this participant
                            self.logger(f"🔄 Allocating forwarder for participant {nick}...")
                            allocation_success = await self.allocate_forwarder_for_participant(room_from_init, jid)
                            if allocation_success:
                                self.logger(f"🎯 Participant {nick} ready for recording with SSRC and forwarder!")
                            
                            break  # Only assign to one participant
                
                if not participant_updated:
                    self.logger(f"⚠️ Could not find suitable participant to map SSRCs from {initiator}")

            else:
                self.logger(f"⚠️ No SSRCs found in Jingle offer from {initiator}")


            # Convert Jingle XML to SDP offer
            sdp_offer = jingle_to_sdp(jingle)

            self.logger(f"📄 Converted SDP offer:\n{sdp_offer}")

            # Create RTCPeerConnection
            pc = RTCPeerConnection()
            self.peer_connections[sid] = pc

            # Track handler - log received tracks and consume them
            @pc.on("track")
            async def on_track(track):
                self.logger(f"🎵 Received {track.kind} track from {initiator}")
                self.logger(f"   Track ID: {track.id}")

                # For Phase 2, just consume the track (prevent buffer overflow)
                # Phase 3 will pipe to FFmpeg
                blackhole = MediaBlackhole()
                blackhole.addTrack(track)
                await blackhole.start()

            # ICE connection state handler
            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                self.logger(f"🔌 ICE connection state: {pc.connectionState}")
                if pc.connectionState == "failed":
                    self.logger("❌ ICE connection failed")
                elif pc.connectionState == "connected":
                    self.logger("✅ ICE connection established!")

            # Set remote description (offer)
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp_offer, type="offer"))
            self.logger("✅ Set remote description (offer)")

            # Create answer
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            self.logger("✅ Created local description (answer)")

            # Wait for ICE gathering to complete (so we send candidates in session-accept)
            # This avoids the need for complex Trickle ICE implementation for now
            self.logger("⏳ Waiting for ICE gathering to complete...")
            gather_start = asyncio.get_event_loop().time()
            while pc.iceGatheringState != "complete":
                if asyncio.get_event_loop().time() - gather_start > 5.0:
                    self.logger("⚠️ ICE gathering timed out (5s), proceeding with what we have")
                    break
                await asyncio.sleep(0.1)
            self.logger(f"✅ ICE gathering complete (State: {pc.iceGatheringState})")

            # Convert SDP answer to Jingle session-accept XML
            jingle_accept = sdp_to_jingle_accept(
                sdp_answer=pc.localDescription.sdp,
                session_id=sid,
                initiator=initiator,
                responder=str(self.boundjid.bare)
            )

            # Build session-accept IQ response
            response_iq = self.make_iq_result(iq['id'])
            response_iq['to'] = iq['from']
            response_iq.append(jingle_accept)

            # Send session-accept
            self.logger(f"📤 Sending session-accept to {iq['from']}")
            await response_iq.send()
            self.logger("✅ Sent session-accept! WebRTC negotiation complete.")

        except Exception as e:
            self.logger(f"❌ Error handling Jingle session-initiate: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")

    def _handle_jingle_transport_info(self, iq):
        """
        Handler for incoming Jingle transport-info IQ (trickle ICE candidates).
        """
        # Schedule async handler
        asyncio.create_task(self._handle_jingle_transport_info_async(iq))

    async def _handle_jingle_transport_info_async(self, iq):
        """
        Async handler for Jingle transport-info. Adds ICE candidates to peer connection.
        """
        try:
            # Extract Jingle element
            jingle = iq.xml.find('{urn:xmpp:jingle:1}jingle')
            if jingle is None:
                self.logger("❌ No jingle element in transport-info")
                return

            sid = jingle.get('sid')
            if not sid or sid not in self.peer_connections:
                self.logger(f"⚠️  Received transport-info for unknown session: {sid}")
                return

            pc = self.peer_connections[sid]

            # Extract ICE candidates from all content/transport elements
            contents = jingle.findall('{urn:xmpp:jingle:1}content')
            candidate_count = 0
            added_count = 0

            for content in contents:
                mid = content.get('name')  # Media stream ID (e.g., "0" for audio, "1" for video)

                transport = content.find('{urn:xmpp:jingle:transports:ice-udp:1}transport')
                if transport is None:
                    continue

                candidates = transport.findall('{urn:xmpp:jingle:transports:ice-udp:1}candidate')
                for cand_elem in candidates:
                    # Extract candidate attributes
                    foundation = cand_elem.get('foundation', '0')
                    component = cand_elem.get('component', '1')
                    protocol = cand_elem.get('protocol', 'udp')
                    priority = cand_elem.get('priority', '0')
                    ip = cand_elem.get('ip')
                    port = cand_elem.get('port')
                    typ = cand_elem.get('type', 'host')
                    rel_addr = cand_elem.get('rel-addr')
                    rel_port = cand_elem.get('rel-port')

                    if not ip or not port:
                        continue

                    candidate_count += 1

                    # Build ICE candidate string for logging
                    candidate_str = f"candidate:{foundation} {component} {protocol} {priority} {ip} {port} typ {typ}"
                    if rel_addr and rel_port:
                        candidate_str += f" raddr {rel_addr} rport {rel_port}"

                    self.logger(f"🧊 ICE candidate [{mid}]: {candidate_str}")

                    try:
                        # Create RTCIceCandidate object
                        ice_candidate = RTCIceCandidate(
                            component=int(component),
                            foundation=foundation,
                            ip=ip,
                            port=int(port),
                            priority=int(priority),
                            protocol=protocol,
                            type=typ,
                            relatedAddress=rel_addr if rel_addr else None,
                            relatedPort=int(rel_port) if rel_port else None,
                            sdpMid=mid,
                            sdpMLineIndex=int(mid) if mid and mid.isdigit() else None
                        )

                        # Add candidate to peer connection
                        await pc.addIceCandidate(ice_candidate)
                        added_count += 1
                        self.logger(f"✅ Added ICE candidate to peer connection")

                    except Exception as e:
                        self.logger(f"⚠️  Failed to add ICE candidate: {e}")

            if candidate_count > 0:
                self.logger(f"📥 Received {candidate_count} ICE candidates, added {added_count} to session {sid}")

            # Send IQ result to acknowledge
            response_iq = self.make_iq_result(iq['id'])
            response_iq['to'] = iq['from']
            await response_iq.send()

        except Exception as e:
            self.logger(f"❌ Error handling transport-info: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")

    def _handle_colibri2_conference_modify(self, iq):
        """
        Handle Colibri2 conference-modify IQs from Jicofo.
        
        This handler serves two purposes:
        1. Acknowledge the IQ to prevent Jicofo from timing out
        2. Extract conference ID mappings for multitrack recording
        
        Example Colibri2 message structure:
        <iq type='set' from='focus@...' to='jvb@...'>
          <conference-modify xmlns='urn:xmpp:jitsi-videobridge:colibri2'
                             meeting-id='c15ac2a1-8537-4bf9-8e06-22e53b0f7aaa'
                             name='testroom@muc.meet.jitsi'>
            <!-- Conference configuration -->
          </conference-modify>
        </iq>
        """
        self.logger(f"Received Colibri2 conference-modify from {iq['from']}")
        
        try:
            # Extract conference ID and room name for multitrack recording mapping
            conf_modify = iq.xml.find('{urn:xmpp:jitsi-videobridge:colibri2}conference-modify')
            if conf_modify is not None:
                meeting_id = conf_modify.get('meeting-id')
                room_name = conf_modify.get('name')
                
                if meeting_id and room_name:
                    # Store the mapping: room JID -> conference ID
                    self.conference_ids[room_name] = meeting_id
                    self.logger(f"🔗 Mapped conference: {room_name} -> {meeting_id}")
                else:
                    self.logger(f"⚠️  Colibri2 message missing meeting-id or name attributes")
            else:
                self.logger(f"⚠️  No conference-modify element found in Colibri2 IQ")
                
        except Exception as e:
            self.logger(f"⚠️  Error extracting conference ID from Colibri2 message: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")
        
        # Send result IQ to acknowledge (prevents Jicofo timeout)
        iq.reply().send()
        self.logger("✅ Sent Colibri2 acknowledgement")

    async def join_conference_muc(self, room: str):
        """
        Join a conference MUC as a participant (not the brewery MUC).
        This triggers Jicofo to send us a Jingle session offer.

        Args:
            room: Conference room name (e.g., "test-conference")
        """
        conference_muc = f"{room}@muc.{self.settings.domain}"
        nick = "recorder-bot"

        self.logger(f"🚪 Joining conference MUC: {conference_muc} as {nick}")

        # Retry logic for MUC join
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self.logger(f"🚪 Joining conference MUC: {conference_muc} (Attempt {attempt+1}/{max_retries})")
                # Join the MUC first (without custom presence)
                # Use join_muc (non-blocking) instead of join_muc_wait to avoid startup hangs
                self.plugin["xep_0045"].join_muc(
                    conference_muc,
                    nick
                )
                self.logger(f"✅ Initiated join for conference MUC: {conference_muc}")
                # Since join_muc is non-blocking, we don't get immediate confirmation.
                # We'll rely on presence stanzas to confirm actual join.
                # For now, assume success and break the retry loop.
                break # Success!
            except Exception as e: # Catch any other potential errors during join initiation
                self.logger(f"❌ Error initiating MUC join for {conference_muc}: {e}")
                import traceback
                self.logger(f"Traceback: {traceback.format_exc()}")
                if attempt < max_retries - 1:
                    self.logger("Retrying join in 5 seconds...")
                    await asyncio.sleep(5.0)
                else:
                    self.logger("❌ Max retries reached. Proceeding with caution (might not be connected).")
                    # Wait a bit longer to give the join more time to actually complete
                    await asyncio.sleep(5.0)
            except Exception as e:
                self.logger(f"❌ Error joining conference MUC: {e}")
                import traceback
                self.logger(f"Traceback: {traceback.format_exc()}")
                raise

        # Always send custom muted presence and register handlers
        # (Even if join_muc_wait timed out, we should be in the room now after the extra wait)
        try:
            # Immediately send custom presence with audiomuted=true and videomuted=true
            # This prevents Jicofo from allocating Colibri2 endpoints for the bot
            presence = self.make_presence(pto=f"{conference_muc}/{nick}")
            presence['type'] = 'available'
            
            # Add Jitsi-specific status elements to indicate muted state
            # This should prevent Jicofo from trying to allocate bridge resources
            audiomuted = ET.Element('{http://jitsi.org/jitmeet/audio}audiomuted')
            audiomuted.text = 'true'
            presence.append(audiomuted)
            
            videomuted = ET.Element('{http://jitsi.org/jitmeet/video}videomuted')
            videomuted.text = 'true'
            presence.append(videomuted)
            
            presence.send()
            self.logger(f"✅ Sent muted presence to {conference_muc}")

            
            # Register MUC presence handlers for this conference room
            # This allows us to track participants joining/leaving
            self.add_event_handler(
                f"muc::{conference_muc}::got_online",
                lambda pres: self._on_conference_participant_online(conference_muc, pres)
            )
            self.add_event_handler(
                f"muc::{conference_muc}::got_offline",
                lambda pres: self._on_conference_participant_offline(conference_muc, pres)
            )
            self.logger(f"✅ Registered participant tracking handlers for {conference_muc}")
            
            # Track existing participants in the room
            await asyncio.sleep(0.5)  # Brief wait for roster to populate
            roster = self.plugin["xep_0045"].get_roster(conference_muc)
            if roster:
                self.logger(f"📋 Found {len(roster)} existing participants in {conference_muc}")
                for participant_nick in roster:
                    # Skip ourselves
                    if participant_nick == nick:
                        continue
                    # We'll get presence stanzas for these participants shortly
                    # No need to manually track them here

        except Exception as e:
            self.logger(f"❌ Error setting up participant tracking: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")

    def _parse_participant_from_presence(self, presence) -> Dict[str, Any]:
        """
        Parse participant metadata from MUC presence stanza.
        
        Extracts:
        - JID (from <item jid=...>)
        - Display name (from <nick>)
        - Stats ID (from <stats-id>)
        - Audio/video muted status (from Jitsi extensions)
        
        Args:
            presence: slixmpp presence stanza
            
        Returns:
            Dictionary with participant metadata
        """
        from datetime import datetime
        
        participant_data = {
            "jid": str(presence['from']),
            "display_name": None,
            "stats_id": None,
            "audio_muted": False,
            "video_muted": False,
            "joined_at": datetime.utcnow().isoformat() + "Z",
            "ssrcs": {}
        }
        
        
        # Extract stats-id from Jitsi extension
        stats_elem = presence.xml.find('{http://jitsi.org/jitmeet}stats-id')
        if stats_elem is not None and stats_elem.text:
            participant_data["stats_id"] = stats_elem.text
        
        # Extract muted status from Jitsi extensions
        audio_muted = presence.xml.find('{http://jitsi.org/jitmeet/audio}audiomuted')
        if audio_muted is not None and audio_muted.text:
            participant_data["audio_muted"] = audio_muted.text.lower() == 'true'
        
        video_muted = presence.xml.find('{http://jitsi.org/jitmeet/video}videomuted')
        if video_muted is not None and video_muted.text:
            participant_data["video_muted"] = video_muted.text.lower() == 'true'
        
        return participant_data

    def _track_participant_join(self, room: str, participant_id: str, participant_data: Dict[str, Any]):
        """
        Track a participant joining a conference room.
        
        Args:
            room: Full MUC JID (e.g., "room-name@muc.meet.jitsi")
            participant_id: Participant nick or unique identifier
            participant_data: Metadata dict from _parse_participant_from_presence
        """
        if room not in self.conference_participants:
            self.conference_participants[room] = {}
        
        self.conference_participants[room][participant_id] = participant_data
        
        display_name = participant_data.get("display_name", participant_id)
        self.logger(f"👤 Participant joined [{room}]: {display_name} (ID: {participant_id})")
        
        # Phase 3: Notify callbacks of participant join
        asyncio.create_task(self._notify_participant_change(room, "joined", participant_id))
        self.logger(f"   Audio muted: {participant_data['audio_muted']}, Video muted: {participant_data['video_muted']}")

    def _track_participant_leave(self, room: str, participant_id: str):
        """
        Track a participant leaving a conference room.
        
        Args:
            room: Full MUC JID
            participant_id: Participant identifier
        """
        removed_participant = None
        if room in self.conference_participants and participant_id in self.conference_participants[room]:
            removed_participant = self.conference_participants[room].pop(participant_id)
            display_name = removed_participant.get("display_name", participant_id)
        if removed_participant:
            self.logger(f"👋 Participant left [{room}]: {display_name} (ID: {participant_id})")
            
            # Phase 3: Notify callbacks of participant leave
            asyncio.create_task(self._notify_participant_change(room, "left", participant_id))

    def get_conference_participants(self, room: str) -> Dict[str, Dict[str, Any]]:
        """
        Get all participants currently in a conference room.
        
        Args:
            room: Conference room name (e.g., "test-conference")
            
        Returns:
            Dictionary mapping participant IDs to their metadata
        """
        conference_muc = f"{room}@muc.{self.settings.domain}"
        return self.conference_participants.get(conference_muc, {})

    async def allocate_forwarder_for_participant(self, room: str, participant_jid: str) -> bool:
        """
        Allocate Colibri forwarder for a specific participant in a room (Phase 1.3).
        Updates participant dict with forwarder info.
        
        Returns True if successful, False otherwise.
        """
        if room not in self.conference_participants:
            self.logger(f"⚠️ Cannot allocate forwarder: room {room} not in tracked conferences")
            return False
            
        if participant_jid not in self.conference_participants[room]:
            self.logger(f"⚠️ Cannot allocate forwarder: participant {participant_jid} not in room {room}")
            return False
            
        participant = self.conference_participants[room][participant_jid]
        
        # Extract endpoint ID (resource part of JID)
        endpoint_id = participant_jid.split('/')[-1] if '/' in participant_jid else participant_jid
        
        try:
            import time
            
            # Wait for Bridge Session ID to be discovered
            # This handles the race condition where Jingle offer processing (which extracts the ID)
            # happens concurrently with this allocation call.
            for i in range(25): # Wait up to 5 seconds
                if room in self.conference_ids:
                    break
                self.logger(f"⏳ Waiting for Bridge Session ID for {room} (Attempt {i+1}/25)...")
                await asyncio.sleep(0.2)
            
            # Use the correct Colibri conference ID if available, otherwise fallback to room name
            conference_id = self.conference_ids.get(room, room)
            if conference_id != room:
                self.logger(f"Using Bridge Session ID {conference_id} for allocation (instead of {room})")
            else:
                self.logger(f"⚠️ Bridge Session ID not found for {room}, falling back to MUC name")
            
            allocation = await self.allocate_forwarder(conference_id, endpoint_id)
            forwarder_info = allocation.get('forwarder', {})
            
            # Store forwarder details in participant
            participant['forwarder'] = {
                'ip': forwarder_info.get('ip'),
                'port': forwarder_info.get('port'),
                'allocated_at': time.time(),
                'endpoint_id': endpoint_id
            }
            
            self.logger(f"✅ Allocated forwarder for {participant.get('nick', participant_jid)}: "
                       f"{forwarder_info.get('ip')}:{forwarder_info.get('port')}")
            return True
            
        except Exception as e:
            self.logger(f"❌ Failed to allocate forwarder for {participant_jid}: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")
            return False

    def get_participants_with_forwarders(self, room: str) -> List[Dict[str, Any]]:
        """
        Get all participants in room who have forwarders allocated (Phase 1.3).
        Returns list suitable for FFmpeg command building.
        """
        if room not in self.conference_participants:
            return []
            
        result = []
        for jid, participant in self.conference_participants[room].items():
            if 'forwarder' in participant and 'ssrcs' in participant:
                # Has both SSRC and forwarder - ready for recording
                fwd = participant['forwarder']
                ssrc_audio = participant['ssrcs'].get('audio', {})
                
                result.append({
                    'id': fwd.get('endpoint_id', jid.split('/')[-1]),
                    'name': participant.get('nick', ''),
                    'jid': jid,
                    'rtp_url': f"rtp://{fwd['ip']}:{fwd['port']}",
                    'ssrc': ssrc_audio.get('ssrc'),
                    'forwarder': fwd
                })
        
        return result

    def is_in_conference(self, room: str) -> bool:
        """
        Check if bot has joined a conference MUC (Phase 2).
        
        Args:
            room: Conference room name (e.g., "my-meeting")
            
        Returns:
            True if bot is in the conference, False otherwise
        """
        conference_muc = f"{room}@muc.{self.settings.domain}"
        return conference_muc in self.conference_participants

    def register_participant_change_callback(self, callback: Callable):
        """
        Register callback for participant join/leave events (Phase 3).
        
        Args:
            callback: Async function with signature: (room: str, action: str, participant_jid: str)
                     action will be "joined" or "left"
        """
        self.participant_change_callbacks.append(callback)
        self.logger(f"Registered participant change callback: {callback.__name__}")

    async def _notify_participant_change(self, room: str, action: str, participant_jid: str):
        """Notify all registered callbacks of participant change (Phase 3)."""
        for callback in self.participant_change_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(room, action, participant_jid)
                else:
                    callback(room, action, participant_jid)
            except Exception as e:
                self.logger(f"❌ Error in participant change callback: {e}")
                import traceback
                self.logger(f"Traceback: {traceback.format_exc()}")

    def _on_conference_participant_online(self, room: str, presence):
        """
        Event handler for MUC participant coming online in a conference room.
        
        Args:
            room: Full MUC JID
            presence: Presence stanza
        """
        # Extract participant nick from presence 'from' field
        # Format: "room@muc.domain/participantNick"
        participant_jid = str(presence['from'])
        if '/' in participant_jid:
            participant_nick = participant_jid.split('/')[-1]
        else:
            participant_nick = participant_jid
        
        # Skip the recorder bot itself
        if participant_nick == "recorder-bot":
            return
        
        # Parse participant metadata
        participant_data = self._parse_participant_from_presence(presence)
        
        # Track participant
        self._track_participant_join(room, participant_nick, participant_data)

    def _on_conference_participant_offline(self, room: str, presence):
        """
        Event handler for MUC participant going offline in a conference room.
        
        Args:
            room: Full MUC JID
            presence: Presence stanza
        """
        # Extract participant nick
        participant_jid = str(presence['from'])
        if '/' in participant_jid:
            participant_nick = participant_jid.split('/')[-1]
        else:
            participant_nick = participant_jid
        
        # Skip the recorder bot itself
        if participant_nick == "recorder-bot":
            return
        
        # Track participant leaving
        self._track_participant_leave(room, participant_nick)


    async def allocate_colibri_v1(self, conference_id: str, endpoint_id: str) -> Dict[str, Any]:
        """
        Allocates an audio channel using the legacy Colibri v1 protocol.
        Namespace: http://jitsi.org/protocol/colibri
        """
        from slixmpp.exceptions import IqError, IqTimeout

        if not self.bridge_jid:
            raise RuntimeError("Bridge JID not discovered")

        self.logger(f"📡 Allocating Colibri v1 Channel on {self.bridge_jid}...")

        # 1. Construct the IQ
        iq = self.make_iq_set(ito=self.bridge_jid)

        # <conference xmlns='http://jitsi.org/protocol/colibri' id='...'>
        # Note: If conference_id is None/Empty, JVB creates a new one.
        conference = ET.Element('{http://jitsi.org/protocol/colibri}conference')
        if conference_id:
            conference.set('id', conference_id)

        # <content name='audio'>
        content = ET.Element('{http://jitsi.org/protocol/colibri}content')
        content.set('name', 'audio')

        # <channel initiator='true' expire='60'>
        # 'initiator=true' asks JVB to start the ICE connectivity checks
        channel = ET.Element('{http://jitsi.org/protocol/colibri}channel')
        channel.set('initiator', 'true')
        channel.set('expire', '180')  # 3 minutes expiry (refresh with simple IQs)

        # <payload-type .../> (Standard Opus)
        payload = ET.Element('{http://jitsi.org/protocol/colibri}payload-type')
        payload.set('id', '111')
        payload.set('name', 'opus')
        payload.set('clockrate', '48000')
        payload.set('channels', '2')

        # <transport xmlns='urn:xmpp:jingle:transports:ice-udp:1'/>
        # We send an empty transport to tell JVB "Allocate ICE candidates for me"
        transport = ET.Element('{urn:xmpp:jingle:transports:ice-udp:1}transport')

        # Assemble structure
        channel.append(payload)
        channel.append(transport)
        content.append(channel)
        conference.append(content)
        iq.append(conference)

        try:
            # 2. Send and Await Reply
            result = await iq.send(timeout=10)
            self.logger("✅ Colibri v1 Allocation Success!")

            # 3. Parse Response (Extract JVB's ICE Candidates)
            # The response mirrors the request but fills in 'id', 'ufrag', 'pwd', and 'candidates'
            resp_conf = result.find('{http://jitsi.org/protocol/colibri}conference')
            resp_content = resp_conf.find('{http://jitsi.org/protocol/colibri}content')
            resp_channel = resp_content.find('{http://jitsi.org/protocol/colibri}channel')
            resp_transport = resp_channel.find('{urn:xmpp:jingle:transports:ice-udp:1}transport')

            allocation_data = {
                "conference_id": resp_conf.get('id'),
                "channel_id": resp_channel.get('id'),
                "ufrag": resp_transport.get('ufrag') if resp_transport is not None else None,
                "pwd": resp_transport.get('pwd') if resp_transport is not None else None,
                "candidates": []
            }

            if resp_transport is not None:
                for cand in resp_transport.findall('{urn:xmpp:jingle:transports:ice-udp:1}candidate'):
                    allocation_data["candidates"].append({
                        "ip": cand.get('ip'),
                        "port": cand.get('port'),
                        "proto": cand.get('protocol'),
                        "type": cand.get('type'),
                        "foundation": cand.get('foundation'),
                        "component": cand.get('component'),
                        "priority": cand.get('priority')
                    })

            self.logger(f"📦 JVB Candidates: {len(allocation_data['candidates'])} found")
            self.logger(f"📦 Conference ID: {allocation_data['conference_id']}")
            self.logger(f"📦 Channel ID: {allocation_data['channel_id']}")

            return allocation_data

        except IqError as e:
            error_condition = e.iq['error']['condition']
            self.logger(f"❌ JVB rejected allocation: {error_condition}")
            self.logger(f"Full error IQ: {e.iq}")
            raise
        except IqTimeout:
            self.logger("❌ JVB allocation timed out")
            raise
        except Exception as e:
            self.logger(f"❌ Unexpected error during Colibri v1 allocation: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")
            raise

    async def run(self):
        """
        Main async method to connect and run until disconnected.
        Use this in asyncio.create_task() within FastAPI lifespan.
        """
        # Fix: Create disconnected Future in async context where event loop is running
        self.disconnected = asyncio.Future()

        # Connect to XMPP server
        self.logger(f"XMPP connecting to {self.settings.host}:{self.settings.port}")

        # Disable cert verification for development (Prosody uses self-signed certs)
        import ssl
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

        # connect() signature changed between slixmpp versions
        # 1.8.x: connect(address=None) where address is a tuple (host, port)
        # 1.9+: connect(host=None, port=None) as separate keyword args
        # Try the 1.9+ style first, fall back to 1.8.x style
        try:
            # Try slixmpp 1.9+ style (keyword arguments)
            await self.connect(host=self.settings.host, port=self.settings.port)
        except TypeError:
            # Fall back to slixmpp 1.8.x style (tuple argument)
            await self.connect(address=(self.settings.host, self.settings.port))
        self.logger("XMPP connection initiated")

        # Wait for readiness (session_start + MUC join + bridge discovery)
        await self.ready.wait()
        self.logger("XMPP bot ready")

        # Run until disconnected
        await self.disconnected

    async def allocate_forwarder(self, conference_id: str, endpoint_id: str) -> Dict[str, Any]:
        """
        Allocate a forwarder using Colibri v1 (legacy protocol).
        Colibri2 is not supported by this JVB version.
        """
        self.logger(f"Allocating forwarder for conference={conference_id}, endpoint={endpoint_id}")

        try:
            # Use Colibri v1 allocation
            allocation_data = await self.allocate_colibri_v1(conference_id, endpoint_id)

            # Return response in compatible format
            return {
                "id": allocation_data["channel_id"],
                "conference_id": allocation_data["conference_id"],
                "bridge_jid": self.bridge_jid,
                "ufrag": allocation_data["ufrag"],
                "pwd": allocation_data["pwd"],
                "candidates": allocation_data["candidates"],
                "forwarder": {
                    # For now, we'll extract the first candidate if available
                    "ip": allocation_data["candidates"][0]["ip"] if allocation_data["candidates"] else None,
                    "port": allocation_data["candidates"][0]["port"] if allocation_data["candidates"] else None,
                }
            }
        except Exception as e:
            self.logger(f"Failed to allocate forwarder: {e}")
            raise

    async def release_forwarder(self, conference_id: str, endpoint_id: str) -> None:
        """Release an endpoint from JVB."""
        if not self.bridge_jid:
            self.logger("No bridge JID available for release")
            return
        try:
            iq = Colibri2IQ.build_release(conference_id, endpoint_id)
            iq.attrib["to"] = self.bridge_jid
            await self._send_iq_async(iq)
            self.logger(f"Released endpoint {endpoint_id} from conference {conference_id}")
        except Exception as e:
            self.logger(f"Failed to release endpoint: {e}")

    async def _send_iq_async(self, iq_elem: ET.Element) -> ET.Element:
        future = self.Iq()
        future.append(iq_elem[0])
        future["to"] = iq_elem.attrib.get("to")
        future["type"] = "set"
        resp = await future.send()
        return resp.xml

    def _resolve_conference_id_via_debug(self, room_name: str) -> Optional[str]:
        """
        Resolve JVB conference ID using the JVB debug endpoint.
        This is a fallback when Jingle/Colibri2 mapping fails.
        """
        try:
            debug_url = f"{self.jvb_rest_url}/debug"
            self.logger(f"🔍 Resolving conference ID via {debug_url}")
            resp = requests.get(debug_url, timeout=5)
            if resp.status_code != 200:
                self.logger(f"❌ JVB debug endpoint returned {resp.status_code}")
                return None
            
            data = resp.json()
            conferences = data.get("conferences", {})
            
            # Normalize room name
            target_room = room_name
            if "@" in target_room:
                target_room_short = target_room.split("@")[0]
            else:
                target_room_short = target_room
                
            for conf_id, conf_data in conferences.items():
                # Check 'name' field (usually full MUC JID)
                conf_name = conf_data.get("name", "")
                
                # Match against full name or short name
                if conf_name == target_room or \
                   (conf_name and conf_name.split("@")[0] == target_room_short):
                    
                    # Found it!
                    # Prefer 'meeting_id' if available (Colibri2 UUID), else 'id'
                    meeting_id = conf_data.get("meeting_id")
                    internal_id = conf_data.get("id")
                    
                    final_id = meeting_id or internal_id
                    self.logger(f"✅ Resolved {room_name} -> {final_id} (via debug)")
                    
                    # Cache it
                    self.conference_ids[target_room_short] = final_id
                    if "@" in conf_name:
                        self.conference_ids[conf_name] = final_id
                        
                    return final_id
            
            self.logger(f"❌ Room {room_name} not found in JVB debug output")
            return None
            
        except Exception as e:
            self.logger(f"❌ Error resolving via debug: {e}")
            return None

    async def start_multitrack_recording(self, room_name: str) -> bool:
        """
        Start multitrack recording via JVB REST API.
        """
        # Normalize room name (remove domain if present)
        if "@" in room_name:
            room_short = room_name.split("@")[0]
        else:
            room_short = room_name
            
        self.logger(f"🎙️  Request to start recording for room: {room_short}")
        
        # Try to find conference ID
        conference_id = None
        
        # 1. Check existing mapping (from Jingle)
        if room_short in self.conference_ids:
            conference_id = self.conference_ids[room_short]
            
        # 2. If not found, wait a bit (retry loop)
        if not conference_id:
            for i in range(5):
                if room_short in self.conference_ids:
                    conference_id = self.conference_ids[room_short]
                    break
                self.logger(f"⏳ Waiting for conference ID mapping for {room_short} (attempt {i+1}/5)...")
                await asyncio.sleep(0.5)
        
        # 3. If still not found, try debug endpoint
        if not conference_id:
            self.logger(f"⚠️ Conference ID not found via Jingle, trying debug endpoint...")
            conference_id = self._resolve_conference_id_via_debug(room_short)
            
        if not conference_id:
            self.logger(f"❌ Could not find conference ID for room {room_short}")
            return False
            
        self.logger(f"✅ Using conference ID: {conference_id}")
        
        # Construct recorder WebSocket URL with room parameter
        recorder_url = f"{self.recorder_ws_url}?room={room_short}"
        
        payload = {
            "connects": [
                {
                    "url": recorder_url,
                    "protocol": "mediajson",
                    "audio": True,
                    "video": False
                }
            ]
        }
        
        url = f"{self.jvb_rest_url}/colibri/v2/conferences/{conference_id}"
        
        try:
            self.logger(f"🎙️  Starting multitrack recording for {conference_id} via {url}")
            self.logger(f"📡 Recorder WebSocket URL: {recorder_url}")
            
            response = requests.patch(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                self.logger(f"✅ Successfully started multitrack recording")
                return True
            elif response.status_code == 404:
                self.logger(f"❌ JVB returned 404. ID might be wrong. Retrying via debug resolution...")
                # Force debug resolution
                new_id = self._resolve_conference_id_via_debug(room_short)
                if new_id and new_id != conference_id:
                    self.logger(f"🔄 Retrying with new ID: {new_id}")
                    url = f"{self.jvb_rest_url}/colibri/v2/conferences/{new_id}"
                    response = requests.patch(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=10
                    )
                    if response.status_code == 200:
                        self.logger(f"✅ Successfully started multitrack recording (on retry)")
                        return True
            
            self.logger(f"❌ Failed to start recording: HTTP {response.status_code}")
            self.logger(f"Response: {response.text}")
            return False
                
        except Exception as e:
            self.logger(f"❌ Error calling JVB REST API: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")
            return False

    async def stop_multitrack_recording(self, room_name: str) -> bool:
        """
        Stop multitrack recording by sending empty connects array.
        """
        # Normalize room name
        if "@" in room_name:
            room_short = room_name.split("@")[0]
        else:
            room_short = room_name
            
        # Look up conference ID
        conference_id = self.conference_ids.get(room_short)
        
        # Fallback to debug resolution if not found
        if not conference_id:
             conference_id = self._resolve_conference_id_via_debug(room_short)
        
        if not conference_id:
            self.logger(f"❌ Could not find conference ID for room {room_short} to stop recording")
            return False
            
        self.logger(f"🛑 Request to stop recording for room: {room_short} (ID: {conference_id})")
        
        # Empty connects array stops the exporter
        payload = {
            "connects": []
        }
        
        url = f"{self.jvb_rest_url}/colibri/v2/conferences/{conference_id}"
        
        try:
            self.logger(f"🛑 Stopping multitrack recording for {conference_id}")
            response = requests.patch(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                self.logger("✅ Successfully stopped multitrack recording")
                return True
            elif response.status_code == 404:
                # Retry with debug resolution
                new_id = self._resolve_conference_id_via_debug(room_short)
                if new_id and new_id != conference_id:
                    url = f"{self.jvb_rest_url}/colibri/v2/conferences/{new_id}"
                    response = requests.patch(url, json=payload, timeout=10)
                    if response.status_code == 200:
                        self.logger("✅ Successfully stopped multitrack recording (on retry)")
                        return True
                        
            self.logger(f"❌ Failed to stop recording: HTTP {response.status_code}")
            return False
        except Exception as e:
            self.logger(f"❌ Error stopping recording: {e}")
            return False


def create_xmpp_bot_from_env(logger: Optional[Callable[[str], None]] = None) -> XMPPBot:
    settings = load_xmpp_settings()
    if settings.mode == "component":
        bot = ComponentBot(settings=settings, logger=logger)
        return bot
    # Plugins are now registered in __init__
    bot = XMPPBot(settings=settings, logger=logger)
    return bot


class ComponentBot(ComponentXMPP):
    def __init__(self, settings: XMPPSettings, logger: Optional[Callable[[str], None]] = None):
        # ComponentXMPP args: (jid, secret, host, port)
        super().__init__(settings.jid, settings.password, settings.host, settings.port)
        self.settings = settings
        self.logger = logger or (lambda msg: None)
        self.bridge_jid: Optional[str] = None
        self.session_started = False
        self.add_event_handler("session_start", self.start)
        self.add_event_handler("muc::%s::got_online" % settings.bridge_muc, self.muc_online)

    async def start(self, event):
        self.logger("XMPP component session started")
        self.session_started = True
        self.logger(f"Component JID: {self.boundjid}")
        try:
            # slixmpp v1.9.0+ requires pfrom for components joining MUC
            # Create a user JID under the component's domain
            component_user_jid = f"recorder-bot@{self.boundjid.domain}"
            self.logger(f"Using pfrom: {component_user_jid}")

            # Join MUC with explicit pfrom (required in v1.9.0+)
            self.plugin["xep_0045"].join_muc(
                self.settings.bridge_muc,
                "recorder-comp",
                pfrom=component_user_jid
            )
            self.logger(f"Joined MUC: {self.settings.bridge_muc}")

            # Check existing occupants after delay
            await asyncio.sleep(2.0)  # Wait for MUC roster
            roster = self.plugin["xep_0045"].get_roster(self.settings.bridge_muc)
            self.logger(f"MUC roster has {len(roster) if roster else 0} occupants")
            if roster:
                for nick in roster:
                    jid_obj = roster[nick].get("jid")
                    jid = str(jid_obj) if jid_obj else None
                    self.logger(f"Occupant {nick}: JID={jid}")
                    if jid and "@internal" in jid:
                        self.bridge_jid = jid
                        self.logger(f"Found existing bridge JID: {self.bridge_jid}")
                        break
            else:
                self.logger("MUC roster is empty or None")
        except Exception as e:
            self.logger(f"Failed to join bridge MUC: {e}")

    def muc_online(self, presence):
        occupant = presence["muc"]["jid"]
        self.logger(f"ComponentBot: MUC occupant online: {occupant}")
        if occupant and occupant.bare and "@internal" in occupant.bare:
            self.bridge_jid = occupant.bare
            self.logger(f"Discovered bridge JID: {self.bridge_jid}")

    async def allocate_forwarder(self, conference_id: str, endpoint_id: str) -> Dict[str, Any]:
        """
        Allocate a forwarder using Colibri v1 (legacy protocol).
        Colibri2 is not supported by this JVB version.
        """
        self.logger(f"Allocating forwarder for conference={conference_id}, endpoint={endpoint_id}")

        try:
            # Use Colibri v1 allocation
            allocation_data = await self.allocate_colibri_v1(conference_id, endpoint_id)

            # Return response in compatible format
            return {
                "id": allocation_data["channel_id"],
                "conference_id": allocation_data["conference_id"],
                "bridge_jid": self.bridge_jid,
                "ufrag": allocation_data["ufrag"],
                "pwd": allocation_data["pwd"],
                "candidates": allocation_data["candidates"],
                "forwarder": {
                    # For now, we'll extract the first candidate if available
                    "ip": allocation_data["candidates"][0]["ip"] if allocation_data["candidates"] else None,
                    "port": allocation_data["candidates"][0]["port"] if allocation_data["candidates"] else None,
                }
            }
        except Exception as e:
            self.logger(f"Failed to allocate forwarder: {e}")
            raise

    async def release_forwarder(self, conference_id: str, endpoint_id: str) -> None:
        """Release an endpoint from JVB."""
        if not self.bridge_jid:
            self.logger("No bridge JID available for release")
            return
        try:
            iq = Colibri2IQ.build_release(conference_id, endpoint_id)
            iq.attrib["to"] = self.bridge_jid
            await self._send_iq_async(iq)
            self.logger(f"Released endpoint {endpoint_id} from conference {conference_id}")
        except Exception as e:
            self.logger(f"Failed to release endpoint: {e}")

    async def _send_iq_async(self, iq_elem: ET.Element) -> ET.Element:
        future = self.Iq()
        future.append(iq_elem[0])
        future["to"] = iq_elem.attrib.get("to")
        future["type"] = "set"
        resp = await future.send()
        return resp.xml
