import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse

from ffmpeg_launcher import build_ffmpeg_command, FFmpegJob, default_recordings_dir, ensure_dir
from colibri2 import build_colibri2_from_env, Colibri2Client

app = FastAPI(title="FFmpeg Multitrack Recorder", version="0.2.0")

EXPECTED_SECRET = os.environ.get("RECORDER_API_SECRET")
RECORDINGS_ROOT = default_recordings_dir()


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


def check_secret(header_val: str | None):
    if EXPECTED_SECRET and header_val != EXPECTED_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


def timestamp_str() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def build_manifest(room: str, participants: List[Dict[str, Any]], out_dir: Path, rec_id: str, mix: bool, colibri_session: Optional[str]) -> Dict[str, Any]:
    manifest = {
        "id": rec_id,
        "room": room,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "participants": [{"id": p["id"], "rtp_url": p["rtp_url"], "ssrc": p.get("ssrc")} for p in participants],
        "output_dir": str(out_dir),
        "mix": mix,
        "colibri_session": colibri_session,
    }
    return manifest


def write_manifest(out_dir: Path, manifest: Dict[str, Any]):
    ensure_dir(out_dir)
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def resolve_inputs_from_request(body: Dict[str, Any]) -> tuple[list[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Returns (participants, session_meta). participants: list[{id, rtp_url, ssrc?}]
    session_meta may include colibri session id for later release.
    """
    if "inputs" in body:
        return body["inputs"], None

    # Attempt Colibri2 allocation if participants provided
    endpoints_raw = body.get("participants") or []
    endpoints: List[str] = []
    for ep in endpoints_raw:
        if isinstance(ep, dict):
            if "id" in ep:
                endpoints.append(str(ep["id"]))
        else:
            endpoints.append(str(ep))
    use_colibri = body.get("use_colibri", True)
    if use_colibri and endpoints:
        client: Colibri2Client = build_colibri2_from_env()
        allocation = client.allocate_audio_forwarders(room=body["room"], endpoints=endpoints)
        session_id = allocation.get("session_id") or allocation.get("sessionId")
        participants: List[Dict[str, Any]] = []
        for ep in allocation.get("endpoints", []):
            audio = ep.get("audio", {})
            ip = audio.get("ip") or audio.get("host") or "127.0.0.1"
            port = audio.get("port")
            if not port:
                continue
            participants.append(
                {
                    "id": ep.get("id") or ep.get("endpoint") or ep.get("name"),
                    "rtp_url": f"rtp://{ip}:{port}",
                    "ssrc": audio.get("ssrc"),
                    "forwarder": audio,
                }
            )
        if not participants:
            raise HTTPException(status_code=502, detail="Colibri2 allocation returned no participants/ports")
        return participants, {"session_id": session_id}

    raise HTTPException(status_code=400, detail="Provide `inputs` with rtp_url or enable Colibri2 with participants.")


def stop_and_release(rec_id: str) -> None:
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
    if session_meta and session_meta.get("session_id"):
        try:
            client = build_colibri2_from_env()
            client.release(session_meta["session_id"])
        except Exception:
            # non-fatal; continue cleanup
            pass
    state.remove(rec_id)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/recordings")
async def start_recording(request: Request, x_auth_token: str | None = Header(default=None)):
    check_secret(x_auth_token)
    body = await request.json()
    room = body.get("room")
    if not room:
        raise HTTPException(status_code=400, detail="room is required")

    participants, session_meta = resolve_inputs_from_request(body)

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
def stop_recording(rec_id: str, x_auth_token: str | None = Header(default=None)):
    check_secret(x_auth_token)
    job = state.get(rec_id)
    if not job:
        raise HTTPException(status_code=404, detail="not found")
    stop_and_release(rec_id)
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
    participants, session_meta = resolve_inputs_from_request(body)

    # stop and release current session
    stop_and_release(rec_id)

    out_dir = RECORDINGS_ROOT / room / timestamp_str()
    mix_flag = bool(body.get("mix", False))
    manifest = build_manifest(room, participants, out_dir, rec_id, mix=mix_flag, colibri_session=session_meta.get("session_id") if session_meta else None)
    cmd = build_ffmpeg_command(room=room, participants=participants, out_dir=out_dir, mix=mix_flag)
    job = FFmpegJob(command=cmd, workdir=out_dir, manifest=manifest)
    job.start()
    state.add(job, session_meta=session_meta)
    write_manifest(out_dir, manifest)
    return JSONResponse({"id": rec_id, "status": job.status(), "manifest": manifest})
