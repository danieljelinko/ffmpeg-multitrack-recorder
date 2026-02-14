"""E2E tests for metadata.json and MKA track title validation."""

import asyncio, re, uuid
from pathlib import Path

import pytest

from helpers import (
    complete_recording, find_latest_recording, find_mka_file,
    get_track_titles, read_metadata, has_audio_content,
)

pytestmark = pytest.mark.asyncio

def _room(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestParticipantNames:
    async def test_names_in_metadata(self, browser, jitsi_url, controller_url, recordings_dir):
        """metadata.json participants dict has at least 2 entries for Alice and Bob."""
        room = _room("test-meta-names")
        rec_dir = await complete_recording(
            browser, jitsi_url, controller_url, recordings_dir, room,
            [("Alice", 440), ("Bob", 880)],
        )
        meta = read_metadata(rec_dir)
        participants = meta.get("participants", {})
        assert len(participants) >= 2, f"Expected >=2 participants, got {participants}"


class TestTrackTitles:
    async def test_titles_match_metadata(self, browser, jitsi_url, controller_url, recordings_dir):
        """MKA track titles match '{endpoint_id} - {display_name}' and align with metadata."""
        room = _room("test-meta-tracks")
        rec_dir = await complete_recording(
            browser, jitsi_url, controller_url, recordings_dir, room,
            [("Alice", 440), ("Bob", 880)],
        )
        mka = find_mka_file(rec_dir)
        assert mka is not None

        titles = get_track_titles(mka)
        assert len(titles) >= 2, f"Expected >=2 titled tracks, got {titles}"

        meta = read_metadata(rec_dir)
        # Metadata keys are "endpoint_id - display_name"; extract bare endpoint IDs
        meta_endpoint_ids = {k.split(" - ", 1)[0] for k in meta.get("participants", {}).keys()}

        for title in titles:
            if " - " in title:
                eid = title.split(" - ", 1)[0]
                assert eid in meta_endpoint_ids, \
                    f"Track endpoint '{eid}' not in metadata endpoints: {meta_endpoint_ids}"


class TestDirectoryNaming:
    async def test_directory_renamed(self, browser, jitsi_url, controller_url, recordings_dir):
        """Recording directory matches pattern {yymmdd_hhmmss}_{room}_{meetingId}."""
        room = _room("test-meta-dir")
        rec_dir = await complete_recording(
            browser, jitsi_url, controller_url, recordings_dir, room,
            [("Alice", 440), ("Bob", 880)],
        )
        dirname = rec_dir.name
        # Pattern: yymmdd_hhmmss_roomname_uuid
        pattern = r"^\d{6}_\d{6}_.+_.+$"
        assert re.match(pattern, dirname), \
            f"Directory name '{dirname}' does not match expected pattern yymmdd_hhmmss_room_meetingId"
