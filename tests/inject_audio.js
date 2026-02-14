// Called with: page.add_init_script(path="inject_audio.js")
// Set window.__TONE_FREQ before navigating (default 440)
// Replaces getUserMedia with a synthetic OscillatorNode tone at the specified frequency.
// Each participant gets a unique frequency so they're distinguishable in recordings.
//
// CRITICAL: Also prevents Jitsi from muting/stopping/removing the audio track at the
// WebRTC level. This ensures RTP audio packets always flow from client → JVB → recorder,
// regardless of Jitsi's startAudioMuted or other mute logic.
(function() {
  const freq = window.__TONE_FREQ || 440;
  const origGUM = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);

  // Create a fresh AudioContext + oscillator stream.  Not a singleton — if the previous
  // track was somehow killed, we need a new one.
  function createSynthStream() {
    const ctx = new AudioContext();
    if (ctx.state === 'suspended') ctx.resume();
    const osc = ctx.createOscillator();
    osc.frequency.value = freq;
    const gain = ctx.createGain();
    gain.gain.value = 0.8;
    const dest = ctx.createMediaStreamDestination();
    osc.connect(gain);
    gain.connect(dest);
    osc.start();
    console.log(`[inject_audio] Synthetic tone created: ${freq}Hz`);
    return dest.stream;
  }

  // Keep one "primary" stream, but recreate if the track was killed
  let _primaryStream = null;
  function getSynthStream() {
    if (_primaryStream) {
      const tracks = _primaryStream.getAudioTracks();
      if (tracks.length > 0 && tracks[0].readyState === 'live') return _primaryStream;
      console.log('[inject_audio] Previous track dead, creating new stream');
    }
    _primaryStream = createSynthStream();
    return _primaryStream;
  }

  // --------------------------------------------------------------------------
  // 1. Prevent audio track from being disabled (track.enabled = false)
  //    Jitsi's muteAudio() typically uses this.
  // --------------------------------------------------------------------------
  const origEnabledDesc = Object.getOwnPropertyDescriptor(MediaStreamTrack.prototype, 'enabled');
  if (origEnabledDesc) {
    Object.defineProperty(MediaStreamTrack.prototype, 'enabled', {
      get() { return origEnabledDesc.get.call(this); },
      set(val) {
        if (!val && this.kind === 'audio') {
          console.log('[inject_audio] BLOCKED track.enabled=false for audio');
          return;  // silently prevent muting
        }
        origEnabledDesc.set.call(this, val);
      },
      configurable: true,
    });
  }

  // --------------------------------------------------------------------------
  // 2. Prevent audio track from being stopped (track.stop())
  // --------------------------------------------------------------------------
  const origStop = MediaStreamTrack.prototype.stop;
  MediaStreamTrack.prototype.stop = function() {
    if (this.kind === 'audio') {
      console.log('[inject_audio] BLOCKED track.stop() for audio');
      return;  // silently prevent stopping
    }
    return origStop.call(this);
  };

  // --------------------------------------------------------------------------
  // 3. Prevent RTCRtpSender.replaceTrack(null) for audio senders
  //    Some Jitsi versions remove the audio track via replaceTrack(null) when muting.
  // --------------------------------------------------------------------------
  const origReplaceTrack = RTCRtpSender.prototype.replaceTrack;
  RTCRtpSender.prototype.replaceTrack = function(track) {
    if (track === null && this.track && this.track.kind === 'audio') {
      console.log('[inject_audio] BLOCKED replaceTrack(null) for audio sender');
      return Promise.resolve();  // pretend it worked
    }
    return origReplaceTrack.call(this, track);
  };

  // --------------------------------------------------------------------------
  // 4. Prevent RTCPeerConnection.removeTrack() for audio senders
  // --------------------------------------------------------------------------
  const origRemoveTrack = RTCPeerConnection.prototype.removeTrack;
  RTCPeerConnection.prototype.removeTrack = function(sender) {
    if (sender && sender.track && sender.track.kind === 'audio') {
      console.log('[inject_audio] BLOCKED removeTrack() for audio sender');
      return;
    }
    return origRemoveTrack.call(this, sender);
  };

  // --------------------------------------------------------------------------
  // 5. getUserMedia override — return synthetic tone stream
  // --------------------------------------------------------------------------
  navigator.mediaDevices.getUserMedia = async (constraints) => {
    console.log('[inject_audio] getUserMedia intercepted', JSON.stringify(constraints));
    const synthAudio = getSynthStream();
    const combinedStream = new MediaStream();
    for (const at of synthAudio.getAudioTracks()) combinedStream.addTrack(at);
    if (constraints.video) {
      try {
        const real = await origGUM({ video: constraints.video });
        for (const vt of real.getVideoTracks()) combinedStream.addTrack(vt);
      } catch (e) {
        const canvas = document.createElement('canvas');
        canvas.width = 640; canvas.height = 480;
        canvas.getContext('2d').fillRect(0, 0, 640, 480);
        const canvasStream = canvas.captureStream(5);
        for (const vt of canvasStream.getVideoTracks()) combinedStream.addTrack(vt);
      }
    }
    return combinedStream;
  };
})();
