import os
import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import List, Dict, Any, Optional


def default_recordings_dir() -> Path:
    return Path(os.environ.get("RECORDINGS_PATH", "/recordings/ffmpeg"))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


class FFmpegJob:
    def __init__(self, command: List[str], workdir: Path, manifest: Dict[str, Any]):
        self.command = command
        self.workdir = workdir
        self.manifest = manifest
        self.proc: subprocess.Popen | None = None
        self._log_lines: deque[str] = deque(maxlen=50)
        self._log_thread: Optional[threading.Thread] = None
        self.id = manifest.get("id", str(uuid.uuid4()))

    def start(self) -> None:
        ensure_dir(self.workdir)
        self.proc = subprocess.Popen(
            self.command, cwd=self.workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        self._log_thread = threading.Thread(target=self._pump_logs, daemon=True)
        self._log_thread.start()

    def _pump_logs(self) -> None:
        if not self.proc or not self.proc.stdout:
            return
        for line in self.proc.stdout:
            self._log_lines.append(line.rstrip())

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._log_thread and self._log_thread.is_alive():
            self._log_thread.join(timeout=2)

    def status(self) -> str:
        if not self.proc:
            return "not_started"
        code = self.proc.poll()
        return "running" if code is None else f"exited:{code}"

    def tail(self) -> List[str]:
        return list(self._log_lines)


def build_ffmpeg_command(room: str, participants: List[Dict[str, Any]], out_dir: Path, mix: bool = False) -> List[str]:
    """
    participants: list of {id, rtp_url, rtcp_port?}
    """
    args: List[str] = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info"]
    # inputs
    for p in participants:
        rtp_url = p["rtp_url"]
        args += [
            "-protocol_whitelist",
            "file,udp,rtp,crypto",
            "-use_wallclock_as_timestamps",
            "1",
            "-fflags",
            "+igndts+genpts",
            "-i",
            rtp_url,
        ]
    # maps
    output_paths = []
    for idx, p in enumerate(participants):
        out_file = out_dir / f"audio-{p['id']}.opus"
        output_paths.append(out_file)
        args += ["-map", f"{idx}:a", "-c:a", "copy", str(out_file)]

    if mix and participants:
        # basic mixdown
        filter_complex = ";".join([f"[{i}:a]anull[a{i}]" for i in range(len(participants))])
        input_refs = "".join([f"[a{i}]" for i in range(len(participants))])
        filter_complex += f";{input_refs}amix=inputs={len(participants)}:normalize=0[mixed]"
        mix_path = out_dir / "mix.m4a"
        args += ["-filter_complex", filter_complex, "-map", "[mixed]", "-c:a", "aac", "-movflags", "+faststart", str(mix_path)]
        output_paths.append(mix_path)

    return args
