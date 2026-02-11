import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
import asyncio

from xmpp_client import create_xmpp_bot_from_env, XMPPBot

EXPECTED_SECRET = os.environ.get("RECORDER_API_SECRET")
XMPP_ENABLED = bool(os.environ.get("XMPP_JID") or os.environ.get("XMPP_COMPONENT_JID"))
BRIDGE_MUC = os.environ.get("JVB_BRIDGE_MUC", "jvbbrewery@internal-muc.meet.jitsi")
AUTO_RECORDING = os.environ.get("ENABLE_AUTO_RECORDING", "0") in ("1", "true", "yes")
RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "/recordings")

print(f"[MODULE INIT] XMPP_ENABLED={XMPP_ENABLED} AUTO_RECORDING={AUTO_RECORDING}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown"""
    print(f"[LIFESPAN] Starting with XMPP_ENABLED={XMPP_ENABLED}")
    if XMPP_ENABLED:
        print("[STARTUP] Initializing XMPP bot...")
        try:
            bot = create_xmpp_bot_from_env(logger=lambda msg: print(f"[XMPP] {msg}"))
            app.state.xmpp_bot = bot
            app.state.xmpp_task = asyncio.create_task(bot.run())

            print("[STARTUP] Waiting for XMPP bot to be ready...")
            await asyncio.wait_for(bot.ready.wait(), timeout=10.0)
            print("[STARTUP] XMPP bot ready!")

            # Start auto-recording monitor if enabled
            if AUTO_RECORDING and bot.auto_recording_enabled:
                print("[STARTUP] Starting auto-recording monitor...")
                await bot.start_auto_recording_monitor()
                print("[STARTUP] Auto-recording monitor started!")

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

    # Shutdown: stop auto-recording and disconnect XMPP bot
    if hasattr(app.state, 'xmpp_bot') and app.state.xmpp_bot:
        bot = app.state.xmpp_bot
        # Stop auto-recording monitor
        try:
            await bot.stop_auto_recording_monitor()
        except Exception as e:
            print(f"[SHUTDOWN] Error stopping auto-recording: {e}")

        print("[SHUTDOWN] Disconnecting XMPP bot...")
        try:
            bot.disconnect()
            await asyncio.wait_for(app.state.xmpp_task, timeout=5.0)
        except asyncio.TimeoutError:
            print("[SHUTDOWN] WARNING: XMPP bot did not disconnect within 5s")
        except Exception as e:
            print(f"[SHUTDOWN] Error during XMPP disconnect: {e}")


app = FastAPI(title="Multitrack Recorder Controller", version="2.0.0", lifespan=lifespan)


def check_secret(header_val: str | None):
    if EXPECTED_SECRET and header_val != EXPECTED_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health(request: Request):
    """Health check showing XMPP connection and auto-recording status"""
    xmpp_status = {"enabled": XMPP_ENABLED, "connected": False, "bridge_jid": None}
    auto_rec_status = {"enabled": AUTO_RECORDING, "active_recordings": 0, "rooms": []}

    if hasattr(request.app.state, 'xmpp_bot') and request.app.state.xmpp_bot:
        bot: XMPPBot = request.app.state.xmpp_bot
        xmpp_status["connected"] = bot.ready.is_set()
        xmpp_status["bridge_jid"] = bot.bridge_jid
        auto_rec_status["active_recordings"] = len(bot.auto_recordings)
        auto_rec_status["rooms"] = [r["room_short"] for r in bot.auto_recordings.values()]

    return {
        "status": "ok",
        "xmpp": xmpp_status,
        "auto_recording": auto_rec_status,
        "brewery_muc": BRIDGE_MUC,
    }


@app.post("/api/record/start")
async def api_start_recording(request: Request, x_auth_token: str | None = Header(default=None)):
    """Start multitrack recording for a room (manual trigger)."""
    check_secret(x_auth_token)

    body = await request.json()
    room_id = body.get("room_id")
    record_video = body.get("record_video")  # optional override

    if not room_id:
        raise HTTPException(status_code=400, detail="Missing 'room_id' parameter")

    bot: XMPPBot = request.app.state.xmpp_bot
    if not bot or not bot.ready.is_set():
        raise HTTPException(status_code=503, detail="XMPP bot not ready")

    if "@" not in room_id:
        full_room_jid = f"{room_id}@muc.{bot.settings.domain}"
    else:
        full_room_jid = room_id

    try:
        if not bot.is_in_conference(full_room_jid):
            print(f"[API] Joining MUC: {full_room_jid}")
            await bot.join_conference_muc(room_id.split("@")[0])
            await asyncio.sleep(3)

        success = await bot.start_multitrack_recording(full_room_jid, record_video=record_video)
        if not success:
            return JSONResponse({"status": "error", "room": room_id, "message": "Failed to start recording"}, status_code=500)

        return JSONResponse({"status": "recording", "room": room_id, "message": "Multitrack recording started"})

    except Exception as e:
        print(f"[API] Error starting recording: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed: {e}")


@app.post("/api/record/stop")
async def api_stop_recording(request: Request, x_auth_token: str | None = Header(default=None)):
    """Stop multitrack recording for a room."""
    check_secret(x_auth_token)

    body = await request.json()
    room_id = body.get("room_id")
    if not room_id:
        raise HTTPException(status_code=400, detail="Missing 'room_id' parameter")

    bot: XMPPBot = request.app.state.xmpp_bot
    if not bot or not bot.ready.is_set():
        raise HTTPException(status_code=503, detail="XMPP bot not ready")

    if "@" not in room_id:
        full_room_jid = f"{room_id}@muc.{bot.settings.domain}"
    else:
        full_room_jid = room_id

    try:
        await bot.stop_multitrack_recording(full_room_jid)
        return JSONResponse({"status": "stopped", "room": room_id})
    except Exception as e:
        print(f"[API] Error stopping recording: {e}")
        raise HTTPException(status_code=500, detail=f"Failed: {e}")


@app.get("/api/recordings")
async def list_recordings(x_auth_token: str | None = Header(default=None)):
    """List all recordings with their metadata."""
    check_secret(x_auth_token)

    recordings = []
    rec_path = Path(RECORDINGS_DIR)
    if not rec_path.exists():
        return {"recordings": []}

    for d in sorted(rec_path.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        entry = {"meeting_id": d.name, "path": str(d)}

        # Check for metadata.json
        meta_file = d / "metadata.json"
        if meta_file.exists():
            try:
                entry["metadata"] = json.loads(meta_file.read_text())
            except Exception:
                entry["metadata"] = None

        # Check for recording files
        mka_files = list(d.glob("*.mka"))
        mkv_files = list(d.glob("*.mkv"))
        entry["has_audio"] = len(mka_files) > 0
        entry["has_video"] = len(mkv_files) > 0
        entry["files"] = [f.name for f in sorted(d.iterdir()) if f.is_file()]

        recordings.append(entry)

    return {"recordings": recordings}
