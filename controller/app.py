import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
import asyncio

from ffmpeg_launcher import build_ffmpeg_command, FFmpegJob, default_recordings_dir, ensure_dir
from colibri2 import build_colibri2_from_env, Colibri2Client
from xmpp_client import create_xmpp_bot_from_env, XMPPBot
from colibri2_simulator import Colibri2Simulator

EXPECTED_SECRET = os.environ.get("RECORDER_API_SECRET")
RECORDINGS_ROOT = default_recordings_dir()
XMPP_ENABLED = bool(os.environ.get("XMPP_JID") or os.environ.get("XMPP_COMPONENT_JID"))
BRIDGE_MUC = os.environ.get("JVB_BRIDGE_MUC", "jvbbrewery@internal-muc.meet.jitsi")
SIMULATION_MODE = bool(os.environ.get("COLIBRI2_SIMULATE", "").lower() in ("1", "true", "yes"))

print(f"[MODULE INIT] XMPP_ENABLED={XMPP_ENABLED}, SIMULATION_MODE={SIMULATION_MODE}")

if SIMULATION_MODE:
    print("[INFO] Running in SIMULATION MODE - no real XMPP/JVB connection")
    simulator = Colibri2Simulator()
else:
    simulator = None


class RecordingState:
    def __init__(self):
        self.jobs: Dict[str, FFmpegJob] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def add(self, job: FFmpegJob, session_meta: Optional[Dict[str, Any]] = None):
        self.jobs[job.id] = job
        if session_meta:
            self.sessions[job.id] = session_meta

    def get(self, rec_id: str) -> FFmpegJob | None:
        return self.jobs.get(rec_id)

    def get_session(self, rec_id: str) -> Optional[Dict[str, Any]]:
        return self.sessions.get(rec_id)

    def remove(self, rec_id: str):
        if rec_id in self.sessions:
            del self.sessions[rec_id]
        if rec_id in self.jobs:
            del self.jobs[rec_id]


state = RecordingState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown"""
    print(f"[LIFESPAN] Starting with XMPP_ENABLED={XMPP_ENABLED}, SIMULATION_MODE={SIMULATION_MODE}")
    # Startup: initialize XMPP bot if enabled
    if XMPP_ENABLED and not SIMULATION_MODE:
        print("[STARTUP] Initializing XMPP bot...")
        try:
            bot = create_xmpp_bot_from_env(logger=lambda msg: print(f"[XMPP] {msg}"))
            app.state.xmpp_bot = bot
            app.state.xmpp_task = asyncio.create_task(bot.run())

            # Wait for bot to be ready before serving requests
            print("[STARTUP] Waiting for XMPP bot to be ready...")
            await asyncio.wait_for(bot.ready.wait(), timeout=10.0)
            print("[STARTUP] XMPP bot ready!")
        except asyncio.TimeoutError:
            print("[STARTUP] WARNING: XMPP bot failed to become ready within 10s")
            app.state.xmpp_bot = None
            app.state.xmpp_task = None
        except Exception as e:
            print(f"[STARTUP] WARNING: Failed to initialize XMPP bot: {e}")
            app.state.xmpp_bot = None
            app.state.xmpp_task = None
    else:
        app.state.xmpp_bot = None
        app.state.xmpp_task = None

    yield

    # Shutdown: disconnect XMPP bot gracefully
    if hasattr(app.state, 'xmpp_bot') and app.state.xmpp_bot:
        print("[SHUTDOWN] Disconnecting XMPP bot...")
        try:
            app.state.xmpp_bot.disconnect()
            await asyncio.wait_for(app.state.xmpp_task, timeout=5.0)
        except asyncio.TimeoutError:
            print("[SHUTDOWN] WARNING: XMPP bot did not disconnect within 5s")
        except Exception as e:
            print(f"[SHUTDOWN] Error during XMPP disconnect: {e}")


app = FastAPI(title="FFmpeg Multitrack Recorder", version="0.2.0", lifespan=lifespan)


def check_secret(header_val: str | None):
    if EXPECTED_SECRET and header_val != EXPECTED_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


def timestamp_str() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def build_manifest(room: str, participants: List[Dict[str, Any]], out_dir: Path, rec_id: str, mix: bool, colibri_session: Optional[str]) -> Dict[str, Any]:
    # Generate audio filenames matching what FFmpeg will create
    import re
    def sanitize_filename(name: str) -> str:
        if not name:
            return ""
        sanitized = re.sub(r'[^\w\-]', '_', name)
        sanitized = re.sub(r'_+', '_', sanitized)
        return sanitized.strip('_')

    participant_entries = []
    for p in participants:
        participant_id = p["id"]
        participant_name = p.get("name", "")

        # Build filename to match FFmpeg output
        if participant_name:
            sanitized_name = sanitize_filename(participant_name)
            audio_file = f"audio-{sanitized_name}-{participant_id}.opus"
        else:
            audio_file = f"audio-{participant_id}.opus"

        participant_entries.append({
            "id": participant_id,
            "display_name": participant_name,
            "audio_file": audio_file,
            "rtp_url": p["rtp_url"],
            "ssrc": p.get("ssrc"),
            "forwarder": p.get("forwarder", {})
        })

    manifest = {
        "id": rec_id,
        "room": room,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "participants": participant_entries,
        "output_dir": str(out_dir),
        "mix": mix,
        "colibri_session": colibri_session,
    }
    return manifest


def write_manifest(out_dir: Path, manifest: Dict[str, Any]):
    ensure_dir(out_dir)
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


async def resolve_inputs_from_request(body: Dict[str, Any], app_state) -> tuple[list[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Returns (participants, session_meta). participants: list[{id, rtp_url, ssrc?}]
    session_meta may include colibri session id for later release.
    """
    if "inputs" in body:
        return body["inputs"], None

    # Attempt Colibri2 allocation if participants provided
    endpoints_raw = body.get("participants") or []
    # Build list of endpoint objects with id and optional name
    endpoint_objects: List[Dict[str, str]] = []
    for ep in endpoints_raw:
        if isinstance(ep, dict):
            if "id" in ep:
                endpoint_objects.append({
                    "id": str(ep["id"]),
                    "name": ep.get("name", "")
                })
        else:
            endpoint_objects.append({"id": str(ep), "name": ""})

    use_colibri = body.get("use_colibri", True)
    if use_colibri and endpoint_objects:
        # Use simulator if enabled
        if SIMULATION_MODE:
            participants, session_meta = simulator.allocate_forwarders(body.get("room", "unknown"), endpoint_objects)
            return participants, session_meta
        # Prefer XMPP path if XMPP is configured and bot is ready
        elif XMPP_ENABLED and hasattr(app_state, 'xmpp_bot') and app_state.xmpp_bot:
            bot: XMPPBot = app_state.xmpp_bot

            # Check if bot is ready
            if not bot.ready.is_set():
                raise HTTPException(status_code=503, detail="XMPP bot not ready")

            # Wait up to 10 seconds for bridge discovery
            if not bot.bridge_jid:
                timeout = 10
                for _ in range(int(timeout / 0.1)):
                    await asyncio.sleep(0.1)
                    if bot.bridge_jid:
                        break

            if not bot.bridge_jid:
                raise HTTPException(status_code=502, detail="No bridge JID discovered via XMPP")

            # Allocate forwarders using the singleton bot
            participants_out: List[Dict[str, Any]] = []
            room = body.get("room", "unknown")
            endpoint_ids = []
            for ep_obj in endpoint_objects:
                ep_id = ep_obj["id"]
                ep_name = ep_obj["name"]
                endpoint_ids.append(ep_id)
                alloc = await bot.allocate_forwarder(room, ep_id)
                fwd = alloc.get("forwarder") or {}
                ip = fwd.get("ip") or "127.0.0.1"
                port = fwd.get("port") or 50000
                pt = fwd.get("pt") or 111
                ssrc = fwd.get("ssrc")
                participants_out.append(
                    {
                        "id": ep_id,
                        "name": ep_name,
                        "rtp_url": f"rtp://{ip}:{port}",
                        "ssrc": ssrc,
                        "pt": pt,
                        "bridge_jid": bot.bridge_jid,
                    }
                )
            return participants_out, {
                "bridge_jid": bot.bridge_jid,
                "room": room,
                "endpoint_ids": endpoint_ids,
                "via_xmpp": True
            }
        # Fallback to HTTP Colibri client if configured (may not be available)
        client: Colibri2Client = build_colibri2_from_env()
        endpoints_ids = [ep["id"] for ep in endpoint_objects]
        # Build name lookup map
        name_map = {ep["id"]: ep["name"] for ep in endpoint_objects}
        allocation = client.allocate_audio_forwarders(room=body["room"], endpoints=endpoints_ids)
        session_id = allocation.get("session_id") or allocation.get("sessionId")
        participants: List[Dict[str, Any]] = []
        for ep in allocation.get("endpoints", []):
            audio = ep.get("audio", {})
            ip = audio.get("ip") or audio.get("host") or "127.0.0.1"
            port = audio.get("port")
            if not port:
                continue
            ep_id = ep.get("id") or ep.get("endpoint") or ep.get("name")
            participants.append(
                {
                    "id": ep_id,
                    "name": name_map.get(ep_id, ""),
                    "rtp_url": f"rtp://{ip}:{port}",
                    "ssrc": audio.get("ssrc"),
                    "forwarder": audio,
                }
            )
        if not participants:
            raise HTTPException(status_code=502, detail="Colibri allocation returned no participants/ports")
        return participants, {"session_id": session_id}

    raise HTTPException(status_code=400, detail="Provide `inputs` with rtp_url or enable Colibri2 with participants.")


async def stop_and_release(rec_id: str, app_state=None) -> None:
    job = state.get(rec_id)
    session_meta = state.get_session(rec_id)
    if job:
        job.stop()
        job.manifest["ended_at"] = datetime.utcnow().isoformat() + "Z"
        job.manifest["logs_tail"] = job.tail()
        manifest_path = Path(job.workdir) / "manifest.json"
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(job.manifest, f, indent=2)
        except Exception:
            pass

    # Release endpoints
    if session_meta:
        # Prefer XMPP release if allocated via XMPP using singleton bot
        if session_meta.get("via_xmpp") and XMPP_ENABLED and app_state:
            if hasattr(app_state, 'xmpp_bot') and app_state.xmpp_bot:
                bot = app_state.xmpp_bot
                if bot.ready.is_set() and bot.bridge_jid:
                    try:
                        room = session_meta.get("room", "unknown")
                        endpoint_ids = session_meta.get("endpoint_ids", [])
                        for ep_id in endpoint_ids:
                            await bot.release_forwarder(room, ep_id)
                    except Exception:
                        # non-fatal; continue cleanup
                        pass
        # Fallback to HTTP Colibri2 release if session_id present
        elif session_meta.get("session_id"):
            try:
                client = build_colibri2_from_env()
                client.release(session_meta["session_id"])
            except Exception:
                # non-fatal; continue cleanup
                pass

    state.remove(rec_id)


@app.get("/health")
async def health(request: Request):
    """Health check showing XMPP connection status"""
    xmpp_status = {
        "enabled": XMPP_ENABLED and not SIMULATION_MODE,
        "connected": False,
        "bridge_jid": None
    }

    if hasattr(request.app.state, 'xmpp_bot') and request.app.state.xmpp_bot:
        bot = request.app.state.xmpp_bot
        xmpp_status["connected"] = bot.ready.is_set()
        xmpp_status["bridge_jid"] = bot.bridge_jid

    return {
        "status": "ok",
        "xmpp": xmpp_status,
        "simulation_mode": SIMULATION_MODE,
        "brewery_muc": BRIDGE_MUC
    }


@app.post("/recordings")
async def start_recording(request: Request, x_auth_token: str | None = Header(default=None)):
    check_secret(x_auth_token)
    body = await request.json()
    room = body.get("room")
    if not room:
        raise HTTPException(status_code=400, detail="room is required")

    participants, session_meta = await resolve_inputs_from_request(body, request.app.state)

    rec_id = str(uuid.uuid4())
    out_dir = RECORDINGS_ROOT / room / timestamp_str()
    mix_flag = bool(body.get("mix", False))
    manifest = build_manifest(room, participants, out_dir, rec_id, mix=mix_flag, colibri_session=session_meta.get("session_id") if session_meta else None)

    cmd = build_ffmpeg_command(room=room, participants=participants, out_dir=out_dir, mix=mix_flag)
    job = FFmpegJob(command=cmd, workdir=out_dir, manifest=manifest)
    job.start()
    state.add(job, session_meta=session_meta)
    write_manifest(out_dir, manifest)
    return JSONResponse({"id": rec_id, "status": job.status(), "manifest": manifest})


@app.get("/recordings/{rec_id}")
def get_status(rec_id: str, x_auth_token: str | None = Header(default=None)):
    check_secret(x_auth_token)
    job = state.get(rec_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    return {"id": rec_id, "status": job.status(), "manifest": job.manifest}


@app.delete("/recordings/{rec_id}")
async def stop_recording(rec_id: str, request: Request, x_auth_token: str | None = Header(default=None)):
    check_secret(x_auth_token)
    job = state.get(rec_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    await stop_and_release(rec_id, request.app.state)
    return {"id": rec_id, "status": "stopped"}


@app.post("/recordings/{rec_id}/refresh")
async def refresh_recording(rec_id: str, request: Request, x_auth_token: str | None = Header(default=None)):
    """
    Basic SSRC/participant refresh: stop existing recording, optionally re-allocate Colibri2, and start a new FFmpeg job.
    This is a coarse approach; fine-grained SSRC patching may be added later.
    """
    check_secret(x_auth_token)
    current = state.get(rec_id)
    if not current:
        raise HTTPException(status_code=404, detail="not found")
    body = await request.json()
    # default to existing room if not provided
    room = body.get("room") or current.manifest.get("room")
    body["room"] = room
    participants, session_meta = await resolve_inputs_from_request(body, request.app.state)

    # stop and release current session
    await stop_and_release(rec_id, request.app.state)

    out_dir = RECORDINGS_ROOT / room / timestamp_str()
    mix_flag = bool(body.get("mix", False))
    manifest = build_manifest(room, participants, out_dir, rec_id, mix=mix_flag, colibri_session=session_meta.get("session_id") if session_meta else None)
    cmd = build_ffmpeg_command(room=room, participants=participants, out_dir=out_dir, mix=mix_flag)
    job = FFmpegJob(command=cmd, workdir=out_dir, manifest=manifest)
    job.start()
    state.add(job, session_meta=session_meta)
    write_manifest(out_dir, manifest)
    return JSONResponse({"id": rec_id, "status": job.status(), "manifest": manifest})


@app.post("/test/join-conference")
async def test_join_conference(request: Request, x_auth_token: str | None = Header(default=None)):
    """
    Test endpoint to join a conference MUC and wait for Jingle offer from Jicofo.
    This is for testing Phase 1 of the "Silent Participant" architecture.

    Body: {"room": "test-conference"}
    """
    check_secret(x_auth_token)

    if SIMULATION_MODE:
        return JSONResponse({"error": "Cannot test Jingle in simulation mode"}, status_code=400)

    body = await request.json()
    room = body.get("room")

    if not room:
        raise HTTPException(status_code=400, detail="Missing 'room' parameter")

    bot: XMPPBot = request.app.state.xmpp_bot

    if not bot or not bot.ready.is_set():
        raise HTTPException(status_code=503, detail="XMPP bot not ready")

    # Join the conference MUC
    try:
        await bot.join_conference_muc(room)
        return JSONResponse({
            "status": "joined",
            "room": room,
            "message": "Check logs for Jingle session-initiate from Jicofo"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to join conference: {str(e)}")
