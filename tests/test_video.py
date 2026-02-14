"""E2E tests for composite video recording.

Skipped entirely when RECORD_VIDEO is not enabled.
"""

import asyncio, uuid
from pathlib import Path

import pytest

from helpers import (
    complete_recording,
    find_latest_recording, find_mka_file, find_video_file,
    count_audio_tracks, read_metadata,
)

pytestmark = pytest.mark.asyncio


def _room(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _require_video(record_video_enabled):
    if not record_video_enabled:
        pytest.skip("RECORD_VIDEO not enabled")


class TestVideoRecording:
    async def test_video_file_produced(self, browser, jitsi_url, controller_url, recordings_dir):
        """With RECORD_VIDEO=true, a video file (.webm) is produced alongside the MKA."""
        room = _room("test-video")
        rec_dir = await complete_recording(
            browser, jitsi_url, controller_url, recordings_dir, room,
            [("Alice", 440), ("Bob", 880)],
            audio_duration=15,
        )
        video = find_video_file(rec_dir)
        assert video is not None, f"No video file in {rec_dir}"
        assert video.stat().st_size > 0, "Video file is empty"

        mka = find_mka_file(rec_dir)
        assert mka is not None, f"No MKA file in {rec_dir}"


class TestVideoMetadata:
    async def test_metadata_reflects_video(self, browser, jitsi_url, controller_url, recordings_dir):
        """Metadata.json reflects video recording state."""
        room = _room("test-videometa")
        rec_dir = await complete_recording(
            browser, jitsi_url, controller_url, recordings_dir, room,
            [("Alice", 440), ("Bob", 880)],
            audio_duration=15,
        )
        meta = read_metadata(rec_dir)
        assert meta.get("record_video") is True or meta.get("video_recording") is True, \
            f"Metadata does not indicate video recording: {meta}"
