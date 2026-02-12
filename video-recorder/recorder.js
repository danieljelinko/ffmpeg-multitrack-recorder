const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

class JitsiRecorder {
  constructor({ jitsiUrl, recordingsDir, logger, displayName, avatarUrl, videoFeedPath }) {
    this.jitsiUrl = jitsiUrl;
    this.recordingsDir = recordingsDir;
    this.log = logger || console.log;
    this.displayName = displayName || 'Recorder';
    this.avatarUrl = avatarUrl || '';
    this.videoFeedPath = videoFeedPath || '';
    // roomName -> { browser, context, page, videoPath, startTime }
    this.sessions = new Map();
  }

  /**
   * Start recording a Jitsi room.
   * Launches headless Chromium, joins the meeting, captures composite video.
   */
  async startRecording(roomName, meetingId) {
    if (this.sessions.has(roomName)) {
      this.log(`[RECORDER] Already recording room: ${roomName}`);
      return { status: 'already_recording', roomName };
    }

    const outDir = meetingId
      ? path.join(this.recordingsDir, meetingId)
      : path.join(this.recordingsDir, roomName);
    fs.mkdirSync(outDir, { recursive: true });

    this.log(`[RECORDER] Starting video recording for room: ${roomName}`);
    this.log(`[RECORDER] Output dir: ${outDir}`);

    const launchArgs = [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--use-fake-device-for-media-stream',
      '--use-fake-ui-for-media-stream',
      '--autoplay-policy=no-user-gesture-required',
      '--ignore-certificate-errors',
    ];
    if (this.videoFeedPath) {
      launchArgs.push(`--use-file-for-fake-video-capture=${this.videoFeedPath}`);
    }

    const browser = await chromium.launch({ args: launchArgs });

    const context = await browser.newContext({
      recordVideo: {
        dir: outDir,
        size: { width: 1280, height: 720 },
      },
      ignoreHTTPSErrors: true,
      permissions: ['camera', 'microphone'],
      viewport: { width: 1280, height: 720 },
    });

    const page = await context.newPage();
    // Playwright recordVideo starts capturing here (when page is created)
    const videoStartTime = new Date().toISOString();

    // Build Jitsi URL with config overrides to join silently
    const configEntries = [
      'config.prejoinPageEnabled=false',
      'config.startWithAudioMuted=true',
      this.videoFeedPath ? 'config.startWithVideoMuted=false' : 'config.startWithVideoMuted=true',
      'config.disableDeepLinking=true',
      'config.notifications=[]',
      'config.toolbarButtons=[]',
      'config.hideConferenceSubject=true',
      'config.hideConferenceTimer=true',
      'config.disableProfile=true',
      'config.enableClosePage=false',
      'config.disableInviteFunctions=true',
      'config.remoteVideoMenu.disableKick=true',
      'config.remoteVideoMenu.disableGrantModerator=true',
      'config.filmstrip.disableResizable=true',
      `userInfo.displayName=${encodeURIComponent(this.displayName)}`,
    ];
    if (this.avatarUrl) configEntries.push(`userInfo.avatarURL=${encodeURIComponent(this.avatarUrl)}`);
    const configParams = configEntries.join('&');

    const meetUrl = `${this.jitsiUrl}/${roomName}#${configParams}`;
    this.log(`[RECORDER] Navigating to: ${meetUrl}`);

    try {
      await page.goto(meetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      this.log(`[RECORDER] Page loaded for room: ${roomName}`);

      // Wait for the conference to initialize (video tiles to appear)
      await this._waitForConference(page, roomName);

      this.sessions.set(roomName, {
        browser,
        context,
        page,
        outDir,
        meetingId,
        videoStartTime,
        conferenceReadyTime: new Date().toISOString(),
      });

      this.log(`[RECORDER] Video recording started for room: ${roomName}`);
      this.log(`[RECORDER] Video capture began at: ${videoStartTime}`);
      return { status: 'recording', roomName, meetingId, outDir, videoStartTime };

    } catch (err) {
      this.log(`[RECORDER] Error starting recording for ${roomName}: ${err.message}`);
      await browser.close().catch(() => {});
      throw err;
    }
  }

  /**
   * Wait for the Jitsi conference to be ready (video tiles visible).
   */
  async _waitForConference(page, roomName) {
    // Wait for either the filmstrip or a video element to appear
    const selectors = [
      '#videospace',
      '[id^="participant_"]',
      '.videocontainer',
      '#largeVideo',
    ];

    for (let attempt = 0; attempt < 15; attempt++) {
      for (const sel of selectors) {
        try {
          const el = await page.$(sel);
          if (el) {
            this.log(`[RECORDER] Conference UI detected (${sel}) for room: ${roomName}`);
            // Give extra time for video streams to start
            await page.waitForTimeout(3000);
            return;
          }
        } catch { /* ignore */ }
      }
      this.log(`[RECORDER] Waiting for conference UI... (attempt ${attempt + 1}/15)`);
      await page.waitForTimeout(2000);
    }
    this.log(`[RECORDER] Conference UI not detected after 30s, recording anyway`);
  }

  /**
   * Stop recording a room, close browser, return video file path.
   */
  async stopRecording(roomName) {
    const session = this.sessions.get(roomName);
    if (!session) {
      this.log(`[RECORDER] No active recording for room: ${roomName}`);
      return { status: 'not_recording', roomName };
    }

    this.log(`[RECORDER] Stopping video recording for room: ${roomName}`);

    let videoPath = null;
    try {
      // Close the page to finalize the video
      videoPath = await session.page.video()?.path();
      await session.page.close();
      await session.context.close();
      await session.browser.close();
    } catch (err) {
      this.log(`[RECORDER] Error during cleanup for ${roomName}: ${err.message}`);
      try { await session.browser.close(); } catch { /* ignore */ }
    }

    this.sessions.delete(roomName);

    // Rename the video file to a predictable name
    if (videoPath && fs.existsSync(videoPath)) {
      const finalPath = path.join(session.outDir, 'video.webm');
      try {
        fs.renameSync(videoPath, finalPath);
        videoPath = finalPath;
        this.log(`[RECORDER] Video saved: ${finalPath}`);
      } catch (err) {
        this.log(`[RECORDER] Could not rename video: ${err.message}`);
      }
    }

    return {
      status: 'stopped',
      roomName,
      meetingId: session.meetingId,
      videoPath,
      videoStartTime: session.videoStartTime,
      conferenceReadyTime: session.conferenceReadyTime,
      endTime: new Date().toISOString(),
    };
  }

  /** List active recording sessions. */
  listSessions() {
    const result = [];
    for (const [roomName, session] of this.sessions) {
      result.push({
        roomName,
        meetingId: session.meetingId,
        videoStartTime: session.videoStartTime,
        conferenceReadyTime: session.conferenceReadyTime,
      });
    }
    return result;
  }

  /** Stop all active sessions (for graceful shutdown). */
  async stopAll() {
    const rooms = [...this.sessions.keys()];
    for (const room of rooms) {
      await this.stopRecording(room).catch(err =>
        this.log(`[RECORDER] Error stopping ${room}: ${err.message}`)
      );
    }
  }
}

module.exports = { JitsiRecorder };
