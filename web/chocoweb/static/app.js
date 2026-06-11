// chocoweb client — Pipecat RTVI over SmallWebRTC
// Pinned versions verified against pipecat-ai 1.1.0 (RTVI protocol 1.2.0)
import { PipecatClient } from 'https://esm.sh/@pipecat-ai/client-js@1.9.1';
import { SmallWebRTCTransport } from 'https://esm.sh/@pipecat-ai/small-webrtc-transport@1.10.2';

// ── DOM refs ────────────────────────────────────────────────────────────
const character = document.getElementById('character');
const setupPanel = document.getElementById('setup-panel');
const sessionPanel = document.getElementById('session-panel');
const profileSel = document.getElementById('profile-select');
const languageSel = document.getElementById('language-select');
const startBtn = document.getElementById('start-btn');
const endBtn = document.getElementById('end-btn');
const statusLabel = document.getElementById('status-label');
const transcript = document.getElementById('transcript');
const errorMsg = document.getElementById('error-msg');

// ── State ────────────────────────────────────────────────────────────────
let client = null;
let profiles = [];
let currentBotEntry = null;  // accumulates bot text during a turn
let currentBotText = '';

// ── Character state ──────────────────────────────────────────────────────
function setCharacterState(state) {
  character.className = `state-${state}`;
}

// ── Status ───────────────────────────────────────────────────────────────
function setStatus(text) {
  statusLabel.textContent = text;
}

// ── Transcript helpers ───────────────────────────────────────────────────
function addTranscript(role, text) {
  if (!text?.trim()) return;
  const el = document.createElement('div');
  el.className = `transcript-entry ${role}`;
  el.textContent = text;
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
}

function addSystemMsg(text) {
  const el = document.createElement('div');
  el.className = 'transcript-entry system';
  el.textContent = text;
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
}

// ── Sent sound (client-side, on user-stopped-speaking) ───────────────────
let _sentAudio = null;
async function playSentSound() {
  if (!_sentAudio) {
    _sentAudio = new Audio('/sounds/sent.wav');
    _sentAudio.volume = 0.5;
  }
  try {
    _sentAudio.currentTime = 0;
    await _sentAudio.play();
  } catch (_) { /* ignore — first-interaction autoplay block */ }
}

// ── Error display ────────────────────────────────────────────────────────
function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove('hidden');
}

function clearError() {
  errorMsg.classList.add('hidden');
}

// ── Profile loading ──────────────────────────────────────────────────────
async function loadProfiles() {
  try {
    const res = await fetch('/api/profiles');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    profiles = await res.json();
    populateProfilePicker();
  } catch (err) {
    showError(`Failed to load profiles: ${err.message}`);
  }
}

function populateProfilePicker() {
  profileSel.innerHTML = '';
  for (const p of profiles) {
    const opt = document.createElement('option');
    opt.value = p.key;
    opt.textContent = p.name;
    profileSel.appendChild(opt);
  }
  populateLanguagePicker();
  startBtn.disabled = profiles.length === 0;
}

function populateLanguagePicker() {
  languageSel.innerHTML = '';
  const profile = profiles.find(p => p.key === profileSel.value);
  if (!profile) return;
  for (const [code, name] of Object.entries(profile.learning_languages)) {
    const opt = document.createElement('option');
    opt.value = code;
    opt.textContent = name;
    languageSel.appendChild(opt);
  }
}

profileSel.addEventListener('change', populateLanguagePicker);

// ── Session lifecycle ────────────────────────────────────────────────────
async function startSession() {
  clearError();
  startBtn.disabled = true;

  const profileKey = profileSel.value;
  const langCode = languageSel.value;

  client = new PipecatClient({
    transport: new SmallWebRTCTransport({
      webrtcRequestParams: { endpoint: '/api/offer', requestData: { profile: profileKey, language: langCode } },
    }),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onConnected: () => {
        setupPanel.classList.add('hidden');
        sessionPanel.classList.remove('hidden');
        transcript.innerHTML = '';
        setStatus('Connecting...');
      },
      onBotReady: () => {
        setCharacterState('idle');
        setStatus('Listening...');
      },
      onDisconnected: () => {
        onSessionEnded();
      },
      onUserStartedSpeaking: () => {
        setStatus('Speaking...');
      },
      onUserStoppedSpeaking: () => {
        playSentSound();
        setStatus('Listening...');
      },
      onTrackStarted: (track) => {
        if (track.kind !== 'audio') return;
        let audio = document.getElementById('bot-audio');
        if (!audio) {
          audio = document.createElement('audio');
          audio.id = 'bot-audio';
          audio.autoplay = true;
          document.body.appendChild(audio);
        }
        audio.srcObject = new MediaStream([track]);
      },
      onBotStartedSpeaking: () => {
        currentBotText = '';
        currentBotEntry = document.createElement('div');
        currentBotEntry.className = 'transcript-entry choco';
        transcript.appendChild(currentBotEntry);
        setCharacterState('speaking');
        setStatus('Choco is speaking...');
      },
      onBotStoppedSpeaking: () => {
        currentBotEntry = null;
        currentBotText = '';
        setCharacterState('idle');
        setStatus('Listening...');
      },
      onUserTranscript: (data) => {
        if (data.final) addTranscript('user', data.text);
      },
      onBotOutput: (data) => {
        if (!data.spoken || !data.text?.trim()) return;
        const chunk = data.text.replaceAll('\n', ' ');
        currentBotText = currentBotText
          ? currentBotText + chunk
          : chunk;
        if (currentBotEntry) {
          currentBotEntry.textContent = currentBotText;
        } else {
          addTranscript('choco', currentBotText);
        }
        transcript.scrollTop = transcript.scrollHeight;
      },
      onServerMessage: (msg) => {
        if (msg?.t === 'session-ending') {
          const reason = msg.d?.reason;
          const labels = {
            'sleep-word': 'Choco is going to sleep. Goodbye!',
            'echo-loop': 'Echo detected — ending session.',
            'idle-timeout': 'Session timed out.',
            'user-ended': 'Session ended.',
          };
          addSystemMsg(labels[reason] ?? 'Session ending...');
          setCharacterState('sleeping');
          setStatus('Goodbye!');
        }
      },
      onError: (err) => {
        showError(String(err?.message ?? err));
      },
    },
  });

  try {
    await client.connect();
  } catch (err) {
    showError(`Connection failed: ${err.message}`);
    client = null;
    startBtn.disabled = false;
  }
}

async function endSession() {
  if (!client) return;
  endBtn.disabled = true;
  addSystemMsg('Ending session...');
  try {
    await client.disconnect();
  } catch (_) { /* teardown regardless */ }
}

function onSessionEnded() {
  const wasActive = !!client;
  client = null;
  currentBotEntry = null;
  currentBotText = '';
  if (!wasActive) return;

  setCharacterState('sleeping');
  setTimeout(() => {
    sessionPanel.classList.add('hidden');
    setupPanel.classList.remove('hidden');
    startBtn.disabled = false;
    endBtn.disabled = false;
    // character stays sleeping on the setup screen
  }, 2000);
}

// ── Event listeners ──────────────────────────────────────────────────────
startBtn.addEventListener('click', startSession);
endBtn.addEventListener('click', endSession);

// ── Boot ─────────────────────────────────────────────────────────────────
loadProfiles();
