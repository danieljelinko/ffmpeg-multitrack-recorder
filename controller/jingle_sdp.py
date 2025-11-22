"""
Jingle XML to SDP converter for Jitsi Meet WebRTC signaling.

Converts between XMPP Jingle stanzas (XEP-0166) and SDP format used by aiortc.
"""

from xml.etree import ElementTree as ET
from typing import Dict, List, Tuple
import re


def jingle_to_sdp(jingle_element: ET.Element) -> str:
    """
    Convert a Jingle XML element to SDP format for aiortc.

    Args:
        jingle_element: The <jingle> XML element from session-initiate

    Returns:
        SDP offer string compatible with RTCSessionDescription
    """
    sdp_lines = [
        "v=0",
        "o=- 0 0 IN IP4 0.0.0.0",
        "s=-",
        "t=0 0",
    ]

    # Extract all content elements (audio/video)
    contents = jingle_element.findall('{urn:xmpp:jingle:1}content')

    # BUNDLE group for multiplexing
    bundle_mids = [content.get('name') for content in contents]
    if bundle_mids:
        sdp_lines.append(f"a=group:BUNDLE {' '.join(bundle_mids)}")

    # Process each content (media stream)
    for content in contents:
        mid = content.get('name')  # e.g., "0" for audio, "1" for video
        senders = content.get('senders', 'both')  # Jingle direction attribute

        # Get description to determine media type
        description = content.find('{urn:xmpp:jingle:apps:rtp:1}description')
        if description is None:
            continue

        media_type = description.get('media')  # "audio" or "video"

        # Get transport info (ICE/DTLS)
        transport = content.find('{urn:xmpp:jingle:transports:ice-udp:1}transport')
        if transport is None:
            continue

        ufrag = transport.get('ufrag')
        pwd = transport.get('pwd')

        # Get DTLS fingerprint
        fingerprint_elem = transport.find('{urn:xmpp:jingle:apps:dtls:0}fingerprint')
        fingerprint = fingerprint_elem.text if fingerprint_elem is not None else None
        fp_hash = fingerprint_elem.get('hash') if fingerprint_elem is not None else 'sha-256'
        fp_setup = fingerprint_elem.get('setup') if fingerprint_elem is not None else 'actpass'

        # Get payload types (codecs)
        payload_types = description.findall('{urn:xmpp:jingle:apps:rtp:1}payload-type')

        # Build format list (payload type IDs)
        fmt_list = [pt.get('id') for pt in payload_types if pt.get('name') not in ['rtx', 'red', 'ulpfec']]

        # m= line
        sdp_lines.append(f"m={media_type} 9 UDP/TLS/RTP/SAVPF {' '.join(fmt_list)}")
        sdp_lines.append("c=IN IP4 0.0.0.0")

        # ICE credentials
        if ufrag and pwd:
            sdp_lines.append(f"a=ice-ufrag:{ufrag}")
            sdp_lines.append(f"a=ice-pwd:{pwd}")

        # DTLS fingerprint
        if fingerprint:
            # Format: "AD:FD:4E:0E..." → "AD:FD:4E:0E..."
            sdp_lines.append(f"a=fingerprint:{fp_hash} {fingerprint}")
            sdp_lines.append(f"a=setup:{fp_setup}")

        # Media ID
        sdp_lines.append(f"a=mid:{mid}")

        # Direction: Convert Jingle senders attribute to SDP direction
        # Jingle "senders" from perspective of initiator:
        #   "both" → a=sendrecv (both parties send/receive)
        #   "initiator" → a=recvonly (we only receive from initiator)
        #   "responder" → a=sendonly (we only send to initiator)
        if senders == "both":
            sdp_lines.append("a=sendrecv")
        elif senders == "initiator":
            sdp_lines.append("a=recvonly")
        elif senders == "responder":
            sdp_lines.append("a=sendonly")
        else:
            # Default to recvonly for recorder use case
            sdp_lines.append("a=recvonly")

        # RTCP multiplexing
        sdp_lines.append("a=rtcp-mux")

        # Add codec information (rtpmap)
        for pt in payload_types:
            pt_id = pt.get('id')
            pt_name = pt.get('name')
            clockrate = pt.get('clockrate')
            channels = pt.get('channels')

            if pt_name in ['rtx', 'red', 'ulpfec']:
                continue  # Skip retransmission/FEC for now

            if channels and channels != '1':
                sdp_lines.append(f"a=rtpmap:{pt_id} {pt_name}/{clockrate}/{channels}")
            else:
                sdp_lines.append(f"a=rtpmap:{pt_id} {pt_name}/{clockrate}")

            # Add fmtp parameters if present
            params = []
            for param in pt.findall('{urn:xmpp:jingle:apps:rtp:1}parameter'):
                param_name = param.get('name')
                param_value = param.get('value')
                if param_name and param_value:
                    params.append(f"{param_name}={param_value}")

            if params:
                sdp_lines.append(f"a=fmtp:{pt_id} {';'.join(params)}")

        # Add RTCP feedback
        for pt in payload_types:
            pt_id = pt.get('id')
            for fb in pt.findall('{urn:xmpp:jingle:apps:rtp:rtcp-fb:0}rtcp-fb'):
                fb_type = fb.get('type')
                fb_subtype = fb.get('subtype')
                if fb_subtype:
                    sdp_lines.append(f"a=rtcp-fb:{pt_id} {fb_type} {fb_subtype}")
                else:
                    sdp_lines.append(f"a=rtcp-fb:{pt_id} {fb_type}")

    return "\r\n".join(sdp_lines) + "\r\n"


def extract_ssrcs_from_jingle(jingle_element: ET.Element) -> Dict[str, Dict[str, any]]:
    """
    Extract SSRC values from Jingle session-initiate for participant tracking.
    
    Args:
        jingle_element: The <jingle> XML element from session-initiate
        
    Returns:
        Dict mapping media type to SSRC info:
        {
            "audio": {"ssrc": 12345678, "cname": "user-xyz", "msid": "..."},
            "video": {"ssrc": 87654321, "cname": "user-xyz", "msid": "..."}
        }
    """
    ssrcs = {}
    
    # Extract all content elements (audio/video)
    contents = jingle_element.findall('{urn:xmpp:jingle:1}content')
    
    for content in contents:
        # Get description to determine media type
        description = content.find('{urn:xmpp:jingle:apps:rtp:1}description')
        if description is None:
            continue
            
        media_type = description.get('media')  # "audio" or "video"
        
        # Find source elements (XEP-0339: Source-Specific Media Attributes in Jingle)
        # Namespace: urn:xmpp:jingle:apps:rtp:ssma:0
        sources = description.findall('{urn:xmpp:jingle:apps:rtp:ssma:0}source')
        
        for source in sources:
            ssrc_value = source.get('ssrc')
            if not ssrc_value:
                continue
                
            # Extract SSRC parameters (cname, msid, mslabel, etc.)
            params = {}
            for param in source.findall('{urn:xmpp:jingle:apps:rtp:ssma:0}parameter'):
                param_name = param.get('name')
                param_value = param.get('value')
                if param_name and param_value:
                    params[param_name] = param_value
            
            # Store first SSRC found for this media type
            # (Multiple SSRCs per media type possible for simulcast, but we'll use primary)
            if media_type not in ssrcs:
                try:
                    ssrcs[media_type] = {
                        'ssrc': int(ssrc_value),
                        'cname': params.get('cname', ''),
                        'msid': params.get('msid', ''),
                        'mslabel': params.get('mslabel', ''),
                        'label': params.get('label', '')
                    }
                except ValueError:
                    # Invalid SSRC format, skip
                    pass
    
    return ssrcs


def sdp_to_jingle_accept(sdp_answer: str, session_id: str, initiator: str, responder: str) -> ET.Element:
    """
    Converts aiortc's Local SDP Answer into a robust Jingle session-accept packet.
    Includes Codecs, Parameters, and RTCP Feedback to satisfy Jitsi's strict requirements.

    Args:
        sdp_answer: SDP answer string from aiortc
        session_id: Jingle session ID from original offer
        initiator: JID of the initiator
        responder: JID of the responder (our bot)

    Returns:
        Jingle XML element for session-accept with complete codec information
    """
    # Parse the SDP into a structured format per media section
    media_sections = _parse_sdp_media_sections(sdp_answer)

    # Build the Jingle element
    jingle = ET.Element("{urn:xmpp:jingle:1}jingle")
    jingle.set("action", "session-accept")
    jingle.set("sid", session_id)
    jingle.set("initiator", initiator)
    jingle.set("responder", responder)

    # Bundle group (Standard for WebRTC)
    group = ET.Element("{urn:xmpp:jingle:apps:grouping:0}group")
    group.set("semantics", "BUNDLE")

    for media_type, section in media_sections.items():
        # Add content to bundle group
        content_name = "0" if media_type == "audio" else "1"
        content_ref = ET.Element("{urn:xmpp:jingle:apps:grouping:0}content")
        content_ref.set("name", content_name)
        group.append(content_ref)

        # <content>
        content = ET.Element("{urn:xmpp:jingle:1}content")
        content.set("creator", "initiator")
        content.set("name", content_name)
        content.set("senders", "both")  # Usually 'both' for a recorder

        # <description> (The part required to fix the bug)
        desc = ET.Element("{urn:xmpp:jingle:apps:rtp:1}description")
        desc.set("media", media_type)

        # Add Payloads (Codecs)
        for pt_id in section['payloads_order']:
            pt_data = section['payloads'][pt_id]

            payload = ET.Element("{urn:xmpp:jingle:apps:rtp:1}payload-type")
            payload.set("id", pt_id)
            payload.set("name", pt_data.get('name', ''))
            payload.set("clockrate", pt_data.get('clockrate', ''))
            if 'channels' in pt_data:
                payload.set("channels", pt_data['channels'])

            # Add Parameters (fmtp)
            for key, value in pt_data.get('params', {}).items():
                param = ET.Element("{urn:xmpp:jingle:apps:rtp:1}parameter")
                param.set("name", key)
                param.set("value", value)
                payload.append(param)

            # Add RTCP Feedback
            for fb in pt_data.get('rtcp-fb', []):
                rtcp = ET.Element("{urn:xmpp:jingle:apps:rtp:rtcp-fb:0}rtcp-fb")
                rtcp.set("type", fb['type'])
                if 'subtype' in fb:
                    rtcp.set("subtype", fb['subtype'])
                payload.append(rtcp)

            desc.append(payload)

        # Add Header Extensions (Optional but good for Jitsi)
        for ext_id, ext_uri in section.get('extmaps', {}).items():
            ext = ET.Element("{urn:xmpp:jingle:apps:rtp:1}rtp-hdrext")
            ext.set("id", ext_id)
            ext.set("uri", ext_uri)
            desc.append(ext)

        content.append(desc)

        # <transport>
        transport = ET.Element("{urn:xmpp:jingle:transports:ice-udp:1}transport")
        transport.set("ufrag", section['ufrag'])
        transport.set("pwd", section['pwd'])

        if 'fingerprint' in section:
            fp = ET.Element("{urn:xmpp:jingle:apps:dtls:0}fingerprint")
            fp.set("hash", section['fingerprint']['hash_alg'])
            fp.set("setup", section['fingerprint']['setup'])
            fp.text = section['fingerprint']['value']
            transport.append(fp)

        content.append(transport)
        jingle.append(content)

    jingle.insert(0, group)
    return jingle


def _parse_sdp_media_sections(sdp_str: str) -> Dict:
    """
    Parses raw SDP string into a dictionary of media sections with detailed codec info.

    Args:
        sdp_str: Raw SDP string from aiortc

    Returns:
        Dictionary mapping media type (audio/video) to section info containing:
        - payloads_order: list of payload type IDs in order
        - payloads: dict of payload type details (name, clockrate, params, rtcp-fb)
        - extmaps: dict of RTP header extensions
        - ufrag, pwd: ICE credentials
        - fingerprint: DTLS fingerprint info
    """
    lines = sdp_str.splitlines()
    sections = {}
    current_media = None

    # Regex patterns
    re_media = re.compile(r"^m=(audio|video) \d+ [A-Z/]+ (.*)")
    re_rtpmap = re.compile(r"^a=rtpmap:(\d+) ([\w\-]+)/(\d+)(?:/(\d+))?")
    re_fmtp = re.compile(r"^a=fmtp:(\d+) (.+)")
    re_rtcp = re.compile(r"^a=rtcp-fb:(\d+) ([\w\-]+)(?: ([\w\-]+))?")
    re_extmap = re.compile(r"^a=extmap:(\d+) (.+)")
    re_ufrag = re.compile(r"^a=ice-ufrag:(.+)")
    re_pwd = re.compile(r"^a=ice-pwd:(.+)")
    re_fp = re.compile(r"^a=fingerprint:([\w\-]+) (.+)")
    re_setup = re.compile(r"^a=setup:(.+)")

    for line in lines:
        # Detect Media Section Change
        m_match = re_media.match(line)
        if m_match:
            current_media = m_match.group(1)
            pts = m_match.group(2).split()
            sections[current_media] = {
                'payloads_order': pts,
                'payloads': {pt: {} for pt in pts},  # Init dicts
                'extmaps': {},
                'rtcp-fb': [],
                'ufrag': '', 'pwd': '',
                'fingerprint': {'hash_alg': 'sha-256', 'setup': 'active', 'value': ''}
            }
            continue

        if not current_media:
            continue

        s = sections[current_media]

        # Parse ICE/DTLS
        if match := re_ufrag.match(line):
            s['ufrag'] = match.group(1)
        elif match := re_pwd.match(line):
            s['pwd'] = match.group(1)
        elif match := re_fp.match(line):
            s['fingerprint']['hash_alg'] = match.group(1)
            s['fingerprint']['value'] = match.group(2)
        elif match := re_setup.match(line):
            # In answer, usually 'active' if offer was 'actpass'
            s['fingerprint']['setup'] = match.group(1)

        # Parse Codecs (rtpmap)
        elif match := re_rtpmap.match(line):
            pt, name, clock, chans = match.groups()
            if pt in s['payloads']:
                s['payloads'][pt].update({'name': name, 'clockrate': clock})
                if chans:
                    s['payloads'][pt]['channels'] = chans

        # Parse Parameters (fmtp)
        elif match := re_fmtp.match(line):
            pt, params_str = match.groups()
            if pt in s['payloads']:
                # Convert "minptime=10;useinbandfec=1" to dict
                param_dict = {}
                for p in params_str.split(';'):
                    if '=' in p:
                        k, v = p.split('=', 1)
                        param_dict[k.strip()] = v.strip()
                s['payloads'][pt]['params'] = param_dict

        # Parse RTCP Feedback
        elif match := re_rtcp.match(line):
            pt, type_, subtype = match.groups()
            fb_obj = {'type': type_}
            if subtype:
                fb_obj['subtype'] = subtype

            if pt == "*":  # Wildcard (rare in this context but possible)
                pass
            elif pt in s['payloads']:
                s['payloads'][pt].setdefault('rtcp-fb', []).append(fb_obj)

        # Parse Header Extensions
        elif match := re_extmap.match(line):
            ext_id, uri = match.groups()
            s['extmaps'][ext_id] = uri

    return sections
