"""Shared test utilities: ffprobe wrappers, metadata parsing, participant simulation."""

import asyncio, json, os, subprocess, time
from pathlib import Path
from urllib.parse import quote

import httpx

INJECT_AUDIO_JS = Path(__file__).parent / "inject_audio.js"


# ---------------------------------------------------------------------------
# Health / polling helpers
# ---------------------------------------------------------------------------

async def wait_for_healthy(url: str, timeout: float = 60, interval: float = 2) -> dict:
    """Poll a /health endpoint until status: ok or timeout."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(verify=False) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(url, timeout=5)
                data = r.json()
                if data.get("status") == "ok":
                    return data
            except Exception:
                pass
            await asyncio.sleep(interval)
    raise TimeoutError(f"{url} not healthy within {timeout}s")


async def wait_for_recording_active(controller_url: str, timeout: float = 60, interval: float = 2) -> dict:
    """Poll controller /health until active_recordings > 0."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(verify=False) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(f"{controller_url}/health", timeout=5)
                data = r.json()
                if data.get("auto_recording", {}).get("active_recordings", 0) > 0:
                    return data
            except Exception:
                pass
            await asyncio.sleep(interval)
    raise TimeoutError(f"No active recordings within {timeout}s")


async def wait_for_recording_stopped(controller_url: str, timeout: float = 60, interval: float = 2) -> dict:
    """Poll controller /health until active_recordings == 0."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(verify=False) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(f"{controller_url}/health", timeout=5)
                data = r.json()
                if data.get("auto_recording", {}).get("active_recordings", 0) == 0:
                    return data
            except Exception:
                pass
            await asyncio.sleep(interval)
    raise TimeoutError(f"Recordings still active after {timeout}s")


# ---------------------------------------------------------------------------
# ffprobe helpers
# ---------------------------------------------------------------------------

def ffprobe_streams(mka_path: str | Path) -> list[dict]:
    """Run ffprobe and return parsed stream info."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(mka_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return json.loads(result.stdout).get("streams", [])


def count_audio_tracks(mka_path: str | Path) -> int:
    """Return number of audio streams in an MKA file."""
    return sum(1 for s in ffprobe_streams(mka_path) if s.get("codec_type") == "audio")


def get_track_titles(mka_path: str | Path) -> list[str]:
    """Return list of stream title tags from an MKA file."""
    titles = []
    for s in ffprobe_streams(mka_path):
        title = s.get("tags", {}).get("title") or s.get("tags", {}).get("TITLE")
        if title:
            titles.append(title)
    return titles


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def read_metadata(recording_dir: str | Path) -> dict:
    """Parse metadata.json from a recording directory."""
    meta_path = Path(recording_dir) / "metadata.json"
    return json.loads(meta_path.read_text())


def find_latest_recording(recordings_dir: str | Path) -> Path | None:
    """Find most recently modified recording directory."""
    rec_path = Path(recordings_dir)
    if not rec_path.exists():
        return None
    dirs = [d for d in rec_path.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def find_mka_file(recording_dir: str | Path) -> Path | None:
    """Find the .mka file in a recording directory."""
    for f in Path(recording_dir).glob("*.mka"):
        return f
    return None


def find_video_file(recording_dir: str | Path) -> Path | None:
    """Find a video file (.webm or .mkv) in a recording directory."""
    for ext in ("*.webm", "*.mkv"):
        for f in Path(recording_dir).glob(ext):
            return f
    return None


def has_audio_content(mka_path: str | Path) -> bool:
    """Check if MKA file has actual audio streams (not just a header).

    In headless browser environments, Chrome's fake device often doesn't produce
    real RTP audio that JVB can forward to the recorder, resulting in MKA files
    with 0 streams. This helper detects that condition.
    """
    return count_audio_tracks(mka_path) > 0


# Shared helper: run a full recording cycle and return the recording dir
async def complete_recording(
    pw_browser,
    jitsi_url: str,
    controller_url: str,
    recordings_dir: str | Path,
    room: str,
    participants: list[tuple[str, int]],
    audio_duration: float = 15,
) -> Path:
    """Join participants, wait for auto-recording, leave, return recording dir.

    Args:
        participants: list of (display_name, freq) tuples
        audio_duration: seconds to wait while recording is active
    """
    pages = []
    for i, (name, freq) in enumerate(participants):
        p = await create_participant(pw_browser, jitsi_url, room, name, freq=freq)
        pages.append(p)
        # Stagger joins so each participant's audio is established before the next
        if i < len(participants) - 1:
            await asyncio.sleep(3)

    # Wait for all participants' audio to be fully established in JVB
    # before auto-recording triggers, so the recorder endpoint subscribes to all sources
    await asyncio.sleep(5)

    try:
        await wait_for_recording_active(controller_url, timeout=60)
        await asyncio.sleep(audio_duration)
    finally:
        for p in pages:
            await close_participant(p)

    await wait_for_recording_stopped(controller_url, timeout=60)
    await asyncio.sleep(5)  # grace for post-processing

    rec_dir = find_latest_recording(recordings_dir)
    assert rec_dir is not None, "No recording directory found"
    return rec_dir


# ---------------------------------------------------------------------------
# Participant simulation
# ---------------------------------------------------------------------------

async def create_participant(
    pw_browser,
    jitsi_url: str,
    room: str,
    display_name: str,
    freq: int = 440,
) -> "Page":
    """Launch a browser context, inject synthetic audio, join a Jitsi room.

    Each participant gets its own browser instance to avoid WebRTC audio
    conflicts when multiple PeerConnections share the same Chromium process.

    Returns the Playwright page handle (with `.browser_instance` attribute if separate).
    """
    # Launch a separate browser per participant to avoid shared-process WebRTC issues
    from playwright.async_api import async_playwright
    pw_inst = await async_playwright().start()
    browser_instance = await pw_inst.chromium.launch(
        headless=True,
        args=[
            "--use-fake-ui-for-media-stream",
            "--disable-web-security",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--allow-running-insecure-content",
        ],
    )
    context = await browser_instance.new_context(ignore_https_errors=True)
    page = await context.new_page()
    # Store references for cleanup
    page._browser_instance = browser_instance
    page._pw_instance = pw_inst

    # Capture browser console for debugging
    page.on("console", lambda msg: print(f"  [{display_name}] console.{msg.type}: {msg.text}"))

    # Set tone frequency before init script runs
    await page.add_init_script(f"window.__TONE_FREQ = {freq};")
    await page.add_init_script(path=str(INJECT_AUDIO_JS))

    # Build URL with config overrides
    # NOTE: prejoinConfig.enabled=false is set server-side in custom-config.js.
    # Setting it via URL hash causes "start without media" (SSRC mismatch issue).
    # NOTE: Do NOT pass config.startAudioMuted here — Jitsi's URL parser converts
    # "false" to boolean false, which coerces to 0, making the mute threshold 0
    # (i.e., mute ALL participants). The server-side custom-config.js sets it to 99999.
    config_params = "&".join([
        "config.startWithAudioMuted=false",
        "config.startSilent=false",
        "config.startWithVideoMuted=true",
        "config.disableDeepLinking=true",
        "config.testing.testMode=true",
        "config.p2p.enabled=false",
        "config.enableNoisyMicDetection=false",
        "config.disableAP=true",
        f"userInfo.displayName={quote(display_name)}",
    ])
    url = f"{jitsi_url}/{room}#{config_params}"

    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    # Wait for the conference to be joined — look for Jitsi's conference UI
    joined = False
    for selector in ['[id="largeVideo"]', '[class*="toolbox"]', '[class*="filmstrip"]', '[id="videospace"]']:
        try:
            await page.wait_for_selector(selector, timeout=20_000)
            joined = True
            break
        except Exception:
            continue
    if not joined:
        await page.wait_for_timeout(10_000)

    # Wait for conference to be fully joined, unmute audio, set display name
    await page.evaluate("""async (displayName) => {
        // Wait for APP.conference to be fully joined
        for (let i = 0; i < 30; i++) {
            if (typeof APP !== 'undefined' && APP.conference && APP.conference._room
                && APP.conference.isJoined && APP.conference.isJoined()) break;
            await new Promise(r => setTimeout(r, 1000));
        }
        if (typeof APP === 'undefined' || !APP.conference) {
            console.warn('[test] APP.conference not available');
            return;
        }
        console.log('[test] Conference joined, isJoined=' + APP.conference.isJoined());

        // Unmute audio with retry — triggers getUserMedia → inject_audio.js override
        for (let attempt = 0; attempt < 3; attempt++) {
            try {
                if (APP.conference.isLocalAudioMuted()) {
                    console.log('[test] Audio muted, unmuting (attempt ' + attempt + ')...');
                    await APP.conference.muteAudio(false);
                    await new Promise(r => setTimeout(r, 1000));
                }
                if (!APP.conference.isLocalAudioMuted()) {
                    console.log('[test] Audio unmuted successfully');
                    break;
                }
            } catch(e) {
                console.warn('[test] muteAudio error (attempt ' + attempt + '):', e);
                await new Promise(r => setTimeout(r, 1000));
            }
        }

        // Set display name via Jitsi API (multiple approaches for compatibility)
        try {
            if (APP.conference._room && APP.conference._room.setDisplayName) {
                APP.conference._room.setDisplayName(displayName);
                console.log('[test] Display name set via _room.setDisplayName: ' + displayName);
            } else if (APP.conference.changeLocalDisplayName) {
                APP.conference.changeLocalDisplayName(displayName);
                console.log('[test] Display name set via changeLocalDisplayName: ' + displayName);
            }
        } catch(e) { console.warn('[test] setDisplayName error:', e); }

        // Log local tracks for debugging
        try {
            const tracks = APP.conference._room ? APP.conference._room.getLocalTracks() : [];
            console.log('[test] Local tracks: ' + tracks.length +
                        ', types: ' + tracks.map(t => t.getType()).join(','));
        } catch(e) {}
    }""", display_name)

    # Give time for getUserMedia + WebRTC renegotiation + SRTP key exchange
    await page.wait_for_timeout(3000)

    return page


async def close_participant(page) -> None:
    """Close a participant's page, browser context, and browser instance."""
    ctx = page.context
    await page.close()
    await ctx.close()
    # Close separate browser instance if it exists
    if hasattr(page, '_browser_instance'):
        await page._browser_instance.close()
    if hasattr(page, '_pw_instance'):
        await page._pw_instance.stop()
