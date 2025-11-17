import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse

from ffmpeg_launcher import build_ffmpeg_command, FFmpegJob, default_recordings_dir, ensure_dir
from colibri2 import build_colibri2_from_env, Colibri2Client

app = FastAPI(title="FFmpeg Multitrack Recorder", version="0.1.0")

EXPECTED_SECRET = os.environ.get("RECORDER_API_SECRET")
RECORDINGS_ROOT = default_recordings_dir()


class RecordingState:
    def __init__(self):
        self.jobs: Dict[str, FFmpegJob] = {}

    def add(self, job: FFmpegJob):
        self.jobs[job.id] = job

    def get(self, rec_id: str) -> FFmpegJob | None:
        return self.jobs.get(rec_id)

    def remove(self, rec_id: str):
        if rec_id in self.jobs:
            del self.jobs[rec_id]


state = RecordingState()


def check_secret(header_val: str | None):
    if EXPECTED_SECRET and header_val != EXPECTED_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


def timestamp_str() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def build_manifest(room: str, participants: List[Dict[str, Any]], out_dir: Path, rec_id: str, mix: bool) -> Dict[str, Any]:
    manifest = {
        "id": rec_id,
        "room": room,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "participants": [{"id": p["id"], "rtp_url": p["rtp_url"]} for p in participants],
        "output_dir": str(out_dir),
        "mix": mix,
    }
    return manifest


def write_manifest(out_dir: Path, manifest: Dict[str, Any]):
    ensure_dir(out_dir)
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def resolve_inputs_from_request(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Use provided RTP inputs if given; otherwise try Colibri2 (not implemented)
    if "inputs" in body:
        return body["inputs"]
    if body.get("use_colibri", True):
        client: Colibri2Client = build_colibri2_from_env()
        # Placeholder: would allocate based on participants/room
        raise HTTPException(
            status_code=501,
            detail="Colibri2 allocation not implemented in this stub; provide `inputs` with rtp_url.",
        )
    raise HTTPException(status_code=400, detail="No inputs provided and Colibri2 disabled.")


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
    participants = resolve_inputs_from_request(body)
    rec_id = str(uuid.uuid4())
    out_dir = RECORDINGS_ROOT / room / timestamp_str()
    manifest = build_manifest(room, participants, out_dir, rec_id, mix=body.get("mix", False))
    cmd = build_ffmpeg_command(room=room, participants=participants, out_dir=out_dir, mix=body.get("mix", False))
    job = FFmpegJob(command=cmd, workdir=out_dir, manifest=manifest)
    job.start()
    state.add(job)
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
    job.stop()
    state.remove(rec_id)
    return {"id": rec_id, "status": "stopped"}
