import asyncio
import logging
from typing import Dict, Any, Optional, Callable

import slixmpp
from slixmpp import ClientXMPP, ComponentXMPP
from slixmpp.xmlstream import ET
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.media import MediaBlackhole

from xmpp_config import XMPPSettings, load_xmpp_settings
from jingle_sdp import jingle_to_sdp, sdp_to_jingle_accept


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
                await self.plugin["xep_0045"].join_muc_wait(
                    self.settings.bridge_muc,
                    nick,
                    timeout=10.0
                )
                self.logger(f"Successfully joined MUC {self.settings.bridge_muc}")

                # Manually check MUC roster for existing occupants (including JVB)
                await asyncio.sleep(0.5)  # Brief wait for roster to populate
                roster = self.plugin["xep_0045"].get_roster(self.settings.bridge_muc)
                if roster:
                    self.logger(f"MUC roster has {len(roster)} occupants")
                    for occupant_nick in roster:
                        occupant_jid = roster[occupant_nick].get("jid")
                        if occupant_jid:
                            self.logger(f"  Occupant '{occupant_nick}': {occupant_jid}")
                            # Check if this is the JVB
                            if str(occupant_jid).startswith("jvb@"):
                                self.bridge_jid = str(occupant_jid)
                                self.logger(f"✅ Bridge discovered in roster: {self.bridge_jid}")
                                # Trigger capability probe
                                asyncio.create_task(self.check_bridge_capabilities())
                                break
                else:
                    self.logger("MUC roster is empty or None")

                # Check if we already discovered the bridge from initial MUC roster
                if self.bridge_jid:
                    self.logger(f"Bridge already discovered: {self.bridge_jid}")
                    self.ready.set()
                    self.logger("Bot ready event set (bridge discovered)")
                else:
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

            sid = jingle.get('sid')
            initiator = jingle.get('initiator')
            self.logger(f"Session ID: {sid}")
            self.logger(f"Initiator: {initiator}")

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
        We simply acknowledge them to prevent Jicofo from timing out and kicking us.
        """
        self.logger(f"Received Colibri2 conference-modify from {iq['from']}")
        # Send an empty result IQ to acknowledge
        # This tells Jicofo "OK, I processed your request" (even if we did nothing)
        iq.reply().send()
        self.logger("✅ Sent Colibri2 acknowledgement (preventing timeout)")

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

        try:
            # Join the MUC first (without custom presence)
            await self.plugin["xep_0045"].join_muc_wait(
                conference_muc,
                nick,
                timeout=10.0
            )
            self.logger(f"✅ Successfully joined conference MUC: {conference_muc}")
        except asyncio.TimeoutError:
            self.logger(f"⚠️ TIMEOUT: MUC join confirmation not received for {conference_muc}")
            self.logger("Proceeding anyway as we might be joined but missed the presence echo.")
            # Continue execution - we may still be in the room
        except Exception as e:
            self.logger(f"❌ Error joining conference MUC: {e}")
            import traceback
            self.logger(f"Traceback: {traceback.format_exc()}")
            raise

        # Always send custom muted presence and register handlers
        # (Even if join_muc_wait timed out, we may still be in the room)
        try:
            # Immediately send custom presence with audiomuted=true and videomuted=true
            # This prevents Jicofo from allocating Colibri2 endpoints for the bot
            presence = self.make_presence(pto=f"{conference_muc}/{nick}")
            presence['type'] = 'available'
            
            # Add Jitsi-specific status elements to indicate muted state
            # This should prevent Jicofo from trying to allocate bridge resources
            audiomuted = ET.SubElement(presence, '{http://jitsi.org/jitmeet/audio}audiomuted')
            audiomuted.text = 'true'
            
            videomuted = ET.SubElement(presence, '{http://jitsi.org/jitmeet/video}videomuted')
            videomuted.text = 'true'
            
            await presence.send()
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
        
        # Extract JID from MUC <x> element
        muc_user = presence.xml.find('{http://jabber.org/protocol/muc#user}x')
        if muc_user is not None:
            item = muc_user.find('{http://jabber.org/protocol/muc#user}item')
            if item is not None and item.get('jid'):
                participant_data["jid"] = item.get('jid')
        
        # Extract display name from <nick> element (Jitsi uses this)
        nick_elem = presence.xml.find('{http://jabber.org/protocol/nick}nick')
        if nick_elem is not None and nick_elem.text:
            participant_data["display_name"] = nick_elem.text
        
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
        self.logger(f"   Audio muted: {participant_data['audio_muted']}, Video muted: {participant_data['video_muted']}")

    def _track_participant_leave(self, room: str, participant_id: str):
        """
        Track a participant leaving a conference room.
        
        Args:
            room: Full MUC JID
            participant_id: Participant identifier
        """
        if room in self.conference_participants and participant_id in self.conference_participants[room]:
            participant_data = self.conference_participants[room].pop(participant_id)
            display_name = participant_data.get("display_name", participant_id)
            self.logger(f"👋 Participant left [{room}]: {display_name} (ID: {participant_id})")

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
