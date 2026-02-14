"""Shared pytest fixtures for E2E tests."""

import asyncio, os, shutil, subprocess
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from helpers import wait_for_healthy


# ---------------------------------------------------------------------------
# Environment-based config
# ---------------------------------------------------------------------------

JITSI_URL = os.environ.get("JITSI_URL", "https://localhost:8443")
CONTROLLER_URL = os.environ.get("CONTROLLER_URL", "http://localhost:8288")
VIDEO_RECORDER_URL = os.environ.get("VIDEO_RECORDER_URL", "http://localhost:3000")
RECORDER_API_SECRET = os.environ.get("RECORDER_API_SECRET", "recorder-secret")
RECORDINGS_DIR = os.environ.get("RECORDINGS_DIR", "../recordings")
RECORD_VIDEO = os.environ.get("RECORD_VIDEO", "false").lower() in ("1", "true", "yes")


@pytest.fixture(scope="session")
def jitsi_url() -> str: return JITSI_URL

@pytest.fixture(scope="session")
def controller_url() -> str: return CONTROLLER_URL

@pytest.fixture(scope="session")
def video_recorder_url() -> str: return VIDEO_RECORDER_URL

@pytest.fixture(scope="session")
def api_secret() -> str: return RECORDER_API_SECRET

@pytest.fixture(scope="session")
def recordings_dir() -> Path: return Path(RECORDINGS_DIR)

@pytest.fixture(scope="session")
def record_video_enabled() -> bool: return RECORD_VIDEO


# ---------------------------------------------------------------------------
# Stack health check (session-scoped, runs once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
async def wait_stack_healthy():
    """Wait for Jitsi web and controller to be reachable before running tests."""
    await wait_for_healthy(f"{CONTROLLER_URL}/health", timeout=90)


# ---------------------------------------------------------------------------
# Playwright browser (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
async def pw():
    """Session-scoped Playwright instance."""
    async with async_playwright() as p:
        yield p


@pytest.fixture(scope="session")
async def browser(pw):
    """Session-scoped Chromium browser with permissive args for headless WebRTC."""
    b = await pw.chromium.launch(
        headless=True,
        args=[
            "--use-fake-ui-for-media-stream",
            "--disable-web-security",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--allow-running-insecure-content",
        ],
    )
    yield b
    await b.close()


# ---------------------------------------------------------------------------
# Recording cleanup (per-test)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_recordings(recordings_dir: Path):
    """Remove all recording directories before each test.

    Recording dirs are root-owned (created by Docker), so we try
    shutil.rmtree first and fall back to sudo rm -rf.
    """
    if recordings_dir.exists():
        for child in recordings_dir.iterdir():
            if child.is_dir():
                try:
                    shutil.rmtree(child)
                except PermissionError:
                    subprocess.run(["sudo", "rm", "-rf", str(child)], check=False)
    yield
