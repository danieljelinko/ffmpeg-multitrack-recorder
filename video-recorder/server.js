const express = require('express');
const { JitsiRecorder } = require('./recorder');

const PORT = parseInt(process.env.PORT || '3000', 10);
const JITSI_URL = process.env.JITSI_INTERNAL_URL || 'https://web:8443';
const RECORDINGS_DIR = process.env.RECORDINGS_DIR || '/recordings';
const RECORDER_DISPLAY_NAME = process.env.RECORDER_DISPLAY_NAME || 'Recorder';
const RECORDER_AVATAR_URL = process.env.RECORDER_AVATAR_URL || '';
const RECORDER_VIDEO_FEED = process.env.RECORDER_VIDEO_FEED || '';

const app = express();
app.use(express.json());

const recorder = new JitsiRecorder({
  jitsiUrl: JITSI_URL,
  recordingsDir: RECORDINGS_DIR,
  displayName: RECORDER_DISPLAY_NAME,
  avatarUrl: RECORDER_AVATAR_URL,
  videoFeedPath: RECORDER_VIDEO_FEED,
  logger: (msg) => console.log(`${new Date().toISOString()} ${msg}`),
});

app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    activeSessions: recorder.listSessions(),
    jitsiUrl: JITSI_URL,
  });
});

app.post('/api/record/start', async (req, res) => {
  const { room, meeting_id } = req.body;
  if (!room) return res.status(400).json({ error: 'Missing "room" field' });

  try {
    const result = await recorder.startRecording(room, meeting_id);
    res.json(result);
  } catch (err) {
    console.error(`Error starting recording: ${err.message}`);
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/record/stop', async (req, res) => {
  const { room } = req.body;
  if (!room) return res.status(400).json({ error: 'Missing "room" field' });

  try {
    const result = await recorder.stopRecording(room);
    res.json(result);
  } catch (err) {
    console.error(`Error stopping recording: ${err.message}`);
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/sessions', (_req, res) => {
  res.json({ sessions: recorder.listSessions() });
});

// Graceful shutdown
async function shutdown(signal) {
  console.log(`${signal} received, stopping all recordings...`);
  await recorder.stopAll();
  process.exit(0);
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Video recorder API listening on port ${PORT}`);
  console.log(`Jitsi URL: ${JITSI_URL}`);
  console.log(`Recordings dir: ${RECORDINGS_DIR}`);
});
