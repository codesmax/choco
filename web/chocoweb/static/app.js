// chocoweb client — Pipecat RTVI over SmallWebRTC
// Pinned versions verified against pipecat-ai 1.1.0 (RTVI protocol 1.2.0)
import { PipecatClient } from 'https://esm.sh/@pipecat-ai/client-js@1.9.1';
import { SmallWebRTCTransport } from 'https://esm.sh/@pipecat-ai/small-webrtc-transport@1.10.2';

// ── DOM refs ─────────────────────────────────────────────────────────────
const character = document.getElementById('character');
const charRing = document.getElementById('char-ring');
const sessionBar = document.getElementById('session-bar');
const chocoTitle = document.getElementById('choco-title');
const setupPanel = document.getElementById('setup-panel');
const sessionPanel = document.getElementById('session-panel');
const profilePicker = document.getElementById('profile-picker');
const languagePicker = document.getElementById('language-picker');
const startBtn = document.getElementById('start-btn');
const endBtn = document.getElementById('end-btn');
const statusLabel = document.getElementById('status-label');
const transcript = document.getElementById('transcript');
const errorMsg = document.getElementById('error-msg');

// ── Language → flag emoji ─────────────────────────────────────────────────
const LANG_FLAGS = {
  en: '🇺🇸', ko: '🇰🇷', es: '🇲🇽', zh: '🇨🇳',
  ja: '🇯🇵', fr: '🇫🇷', de: '🇩🇪', pt: '🇧🇷',
  it: '🇮🇹', ru: '🇷🇺', ar: '🇸🇦', hi: '🇮🇳',
};

// ── State ─────────────────────────────────────────────────────────────────
let client = null;
let profiles = [];
let selectedProfile = null;
let selectedLanguage = null;
let botEntry = null;
let userEntry = null;

// ── Character state ───────────────────────────────────────────────────────
function setCharacterState(state) {
  character.className = `state-${state}`;
  charRing.className = state === 'speaking' ? 'ring-speaking'
    : state === 'idle' ? 'ring-idle'
      : '';
}

// ── Status ────────────────────────────────────────────────────────────────
function setStatus(text) {
  statusLabel.textContent = text;
}

// ── Transcript helpers ────────────────────────────────────────────────────
function createEntry(cssClass) {
  const el = document.createElement('div');
  el.className = `transcript-entry ${cssClass}`;
  transcript.appendChild(el);
  return el;
}

function appendChunk(el, chunk) {
  if (/[?!]$/.test(el.textContent) && !/^\s/.test(chunk)) chunk = ' ' + chunk;
  const span = document.createElement('span');
  span.className = 'word-chunk';
  span.textContent = chunk;
  el.appendChild(span);
  transcript.scrollTop = transcript.scrollHeight;
}

function addSystemMsg(text) {
  const el = document.createElement('div');
  el.className = 'transcript-entry system';
  el.textContent = text;
  transcript.appendChild(el);
  transcript.scrollTop = transcript.scrollHeight;
}

// Inserts a media preview card below the most recent bot bubble.
// imgSrc is optional; omit for placeholder. Wired to server 'preview' messages.
function addPreviewCard(title, caption, imgSrc) {
  const card = document.createElement('div');
  card.className = 'preview-card';
  const imgEl = imgSrc
    ? `<img class="preview-img" src="${imgSrc}" alt="${title}">`
    : `<div class="preview-img">IMAGE</div>`;
  card.innerHTML = `
    ${imgEl}
    <div class="preview-body">
      <div class="preview-title">${title}</div>
      <div class="preview-caption">${caption}</div>
    </div>
  `;
  transcript.appendChild(card);
  transcript.scrollTop = transcript.scrollHeight;
}

// ── Error display ─────────────────────────────────────────────────────────
function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove('hidden');
}

function clearError() {
  errorMsg.classList.add('hidden');
}

// ── Profile picker ────────────────────────────────────────────────────────
async function loadProfiles() {
  try {
    const res = await fetch('/api/profiles');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    profiles = await res.json();
    buildProfilePicker();
  } catch (err) {
    showError(`Failed to load profiles: ${err.message}`);
  }
}

function buildProfilePicker() {
  profilePicker.innerHTML = '';
  for (const p of profiles) {
    const btn = document.createElement('button');
    btn.className = 'picker-btn profile-btn';
    btn.dataset.value = p.key;
    const initial = p.name.charAt(0).toUpperCase();
    btn.innerHTML = `
      <span class="profile-initial">${initial}</span>
      <span class="profile-name">${p.name}</span>
    `;
    btn.addEventListener('click', () => selectProfile(p.key));
    profilePicker.appendChild(btn);
  }
  if (profiles.length > 0) selectProfile(profiles[0].key);
  startBtn.disabled = profiles.length === 0;
}

function selectProfile(key) {
  selectedProfile = key;
  profilePicker.querySelectorAll('.picker-btn').forEach(b =>
    b.classList.toggle('selected', b.dataset.value === key)
  );
  buildLanguagePicker(profiles.find(p => p.key === key));
}

// ── Language picker ───────────────────────────────────────────────────────
function buildLanguagePicker(profile) {
  languagePicker.innerHTML = '';
  if (!profile) return;
  const entries = Object.entries(profile.learning_languages || {});
  for (const [code, name] of entries) {
    const btn = document.createElement('button');
    btn.className = 'lang-seg-btn';
    btn.dataset.value = code;
    const flag = LANG_FLAGS[code] ?? '🌐';
    btn.innerHTML = `<span class="lang-flag">${flag}</span><span>${name}</span>`;
    btn.addEventListener('click', () => selectLanguage(code));
    languagePicker.appendChild(btn);
  }
  if (entries.length > 0) selectLanguage(entries[0][0]);
}

function selectLanguage(code) {
  selectedLanguage = code;
  languagePicker.querySelectorAll('.lang-seg-btn').forEach(b =>
    b.classList.toggle('selected', b.dataset.value === code)
  );
}

// ── Session lifecycle ─────────────────────────────────────────────────────
async function startSession() {
  clearError();
  startBtn.disabled = true;

  client = new PipecatClient({
    transport: new SmallWebRTCTransport({
      webrtcRequestParams: {
        endpoint: '/api/offer',
        requestData: { profile: selectedProfile, language: selectedLanguage },
      },
    }),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onConnected: () => {
        setupPanel.classList.add('hidden');
        chocoTitle.classList.add('hidden');
        sessionPanel.classList.remove('hidden');
        sessionBar.classList.remove('hidden');
        transcript.innerHTML = '';
        botEntry = null;
        userEntry = null;
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
        if (!botEntry) botEntry = createEntry('choco');
        setCharacterState('speaking');
        setStatus('Choco is speaking...');
      },
      onBotStoppedSpeaking: () => {
        botEntry = null;
        setCharacterState('idle');
        setStatus('Listening...');
      },
      onUserTranscript: (data) => {
        if (data.final) {
          if (!userEntry && data.text?.trim()) {
            userEntry = createEntry('user');
            appendChunk(userEntry, data.text);
          }
          userEntry = null;
        } else if (data.text?.trim()) {
          if (!userEntry) userEntry = createEntry('user');
          appendChunk(userEntry, data.text);
        }
      },
      onBotOutput: (data) => {
        if (!data.spoken || !data.text?.trim()) return;
        if (!botEntry) botEntry = createEntry('choco');
        appendChunk(botEntry, data.text);
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
        if (msg?.t === 'preview') {
          addPreviewCard(msg.d?.title ?? '', msg.d?.caption ?? '', msg.d?.img);
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
  botEntry = null;
  userEntry = null;
  if (!wasActive) return;

  setCharacterState('sleeping');
  setTimeout(() => {
    sessionPanel.classList.add('hidden');
    sessionBar.classList.add('hidden');
    setupPanel.classList.remove('hidden');
    chocoTitle.classList.remove('hidden');
    startBtn.disabled = false;
    endBtn.disabled = false;
    // character stays sleeping on the setup screen
  }, 2000);
}

// ── Event listeners ───────────────────────────────────────────────────────
startBtn.addEventListener('click', startSession);
endBtn.addEventListener('click', endSession);

// ── Boot ──────────────────────────────────────────────────────────────────
loadProfiles();
