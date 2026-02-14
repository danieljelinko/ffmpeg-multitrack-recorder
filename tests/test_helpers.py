"""Unit tests for helpers.py — runs without the Docker stack."""

import json, subprocess, tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from helpers import (
    ffprobe_streams, count_audio_tracks, get_track_titles,
    read_metadata, find_latest_recording, find_mka_file, find_video_file,
    has_audio_content,
)


# ---------------------------------------------------------------------------
# ffprobe helpers (mocked subprocess)
# ---------------------------------------------------------------------------

FAKE_STREAMS = {
    "streams": [
        {"codec_type": "audio", "tags": {"title": "ep1 - Alice", "DURATION": "00:01:00"}},
        {"codec_type": "audio", "tags": {"title": "ep2 - Bob", "DURATION": "00:00:45"}},
    ]
}

EMPTY_STREAMS = {"streams": []}


class TestCountAudioTracks:
    def test_two_tracks(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        with patch("helpers.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(FAKE_STREAMS), stderr="",
            )
            assert count_audio_tracks(mka) == 2

    def test_zero_tracks(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        with patch("helpers.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(EMPTY_STREAMS), stderr="",
            )
            assert count_audio_tracks(mka) == 0

    def test_mixed_codecs_counts_only_audio(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        mixed = {"streams": [
            {"codec_type": "audio", "tags": {"title": "ep1"}},
            {"codec_type": "video", "tags": {"title": "video"}},
            {"codec_type": "audio", "tags": {"title": "ep2"}},
        ]}
        with patch("helpers.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(mixed), stderr="",
            )
            assert count_audio_tracks(mka) == 2


class TestGetTrackTitles:
    def test_extracts_titles(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        with patch("helpers.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(FAKE_STREAMS), stderr="",
            )
            titles = get_track_titles(mka)
        assert titles == ["ep1 - Alice", "ep2 - Bob"]

    def test_no_titles(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        no_titles = {"streams": [{"codec_type": "audio", "tags": {}}]}
        with patch("helpers.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(no_titles), stderr="",
            )
            assert get_track_titles(mka) == []


class TestHasAudioContent:
    def test_true_with_tracks(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        with patch("helpers.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(FAKE_STREAMS), stderr="",
            )
            assert has_audio_content(mka) is True

    def test_false_without_tracks(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        with patch("helpers.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(EMPTY_STREAMS), stderr="",
            )
            assert has_audio_content(mka) is False


class TestFfprobeStreams:
    def test_ffprobe_failure_raises(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        with patch("helpers.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="ffprobe error",
            )
            with pytest.raises(RuntimeError, match="ffprobe failed"):
                ffprobe_streams(mka)


# ---------------------------------------------------------------------------
# Metadata / filesystem helpers
# ---------------------------------------------------------------------------

class TestReadMetadata:
    def test_reads_json(self, tmp_path):
        meta = {"room": "test", "participants": {"ep1": "Alice"}}
        (tmp_path / "metadata.json").write_text(json.dumps(meta))
        assert read_metadata(tmp_path) == meta

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_metadata(tmp_path)


class TestFindLatestRecording:
    def test_finds_most_recent(self, tmp_path):
        import time
        d1 = tmp_path / "old_recording"
        d1.mkdir()
        time.sleep(0.05)
        d2 = tmp_path / "new_recording"
        d2.mkdir()
        assert find_latest_recording(tmp_path) == d2

    def test_empty_dir_returns_none(self, tmp_path):
        assert find_latest_recording(tmp_path) is None

    def test_nonexistent_dir_returns_none(self):
        assert find_latest_recording(Path("/nonexistent/path")) is None

    def test_ignores_files(self, tmp_path):
        (tmp_path / "not_a_dir.txt").touch()
        assert find_latest_recording(tmp_path) is None


class TestFindMkaFile:
    def test_finds_mka(self, tmp_path):
        mka = tmp_path / "recording.mka"
        mka.touch()
        assert find_mka_file(tmp_path) == mka

    def test_no_mka_returns_none(self, tmp_path):
        (tmp_path / "other.txt").touch()
        assert find_mka_file(tmp_path) is None


class TestFindVideoFile:
    def test_finds_webm(self, tmp_path):
        v = tmp_path / "video.webm"
        v.touch()
        assert find_video_file(tmp_path) == v

    def test_finds_mkv(self, tmp_path):
        v = tmp_path / "video.mkv"
        v.touch()
        assert find_video_file(tmp_path) == v

    def test_no_video_returns_none(self, tmp_path):
        (tmp_path / "recording.mka").touch()
        assert find_video_file(tmp_path) is None
