# Choco → Shared Core Extraction (Phase 1 Handoff)

**For**: Claude Code (Sonnet 4.6 recommended)
**Author**: Claude (web), with @codesmax
**Status**: Ready to execute
**Scope**: Refactor only — **no functional changes**, no new features, no chocoweb work yet

---

## Context

ChocoPi is a voice-powered language tutor for kids, currently running as a Pi/Linux-native kiosk app using `pygame-ce` for display, OpenWakeWord (tflite) for wake-word detection, and a Pipecat pipeline for the conversation loop (OpenAI Realtime / Gemini Live / Ultravox providers).

A separate web-based sibling app (`chocoweb`) is planned next, targeting cross-platform remote/browser deployment via WebRTC. To support both apps cleanly without duplicating logic, we're extracting the platform-agnostic core into a shared package *first*, with the existing kiosk app refactored to consume it. **This refactor must happen before any chocoweb work begins.**

To reflect the new two-product reality, the repo itself is being renamed from `chocopi` to `choco` (the umbrella name) — `chocopi` continues to exist as the Pi kiosk app package within it.

## Why now, why this ordering

We considered the unified "one product, two transports" approach but rejected it after empirical testing: browser-based wake-word detection (onnxruntime-web) uses materially more CPU on a Pi than the current bare tflite implementation. The two products genuinely target different deployment models:

- **chocopi**: dedicated Pi device, always-on kiosk, low resource ceiling, hardware-integrated
- **chocoweb** (future): deploy-anywhere server, accessed via any browser (mobile/desktop), uses Chrome's built-in WebRTC AEC

Two implementations is defensible *because* the deployment targets are different. But the conversational logic, providers, memory, prompts, and pipeline assembly are identical — those must not be duplicated. Hence the shared core.

We extract the core with chocopi as the *only* consumer first. This forces the abstractions to be right for the existing working app before chocoweb starts depending on them. If we built chocoweb first or in parallel, the core would inevitably get shaped around chocoweb's needs and the kiosk app would have to retrofit.

## Prerequisite (manual, before Claude Code starts)

The GitHub repo should be renamed from `codesmax/chocopi` to `codesmax/choco` before this work begins. This is a one-click action in GitHub settings and doesn't affect local checkouts (GitHub redirects the old URL). Doing it first means the rest of the refactor lands in the correctly-named repo.

## Goal

Refactor the existing repo from:

```
chocopi/
├── src/chocopi/
│   ├── (orchestrator, providers, memory, wakeword, display, audio, language, etc.)
│   └── ...
└── ...
```

into:

```
choco/                          # repo root, renamed from chocopi
├── pyproject.toml              # uv workspace root
├── README.md                   # explains both products + when to pick which
├── assets/
│   ├── models/                 # wake-word .tflite + .onnx files
│   ├── sprites/                # character animation frames
│   ├── sounds/                 # SFX, jingles, idle audio
│   └── images/                 # backgrounds, UI elements
├── core/
│   ├── pyproject.toml          # declares chococore package
│   └── chococore/              # platform-agnostic modules (see list below)
├── pi/
│   ├── pyproject.toml          # declares chocopi package
│   ├── chocopi/                # pi-specific modules (see list below)
│   └── install/                # systemd unit, install.sh, Pi-specific setup
└── (web/ comes later — do not create in Phase 1)
```

**Functional behavior of the kiosk app must be identical before and after this refactor.** If you observe any behavior change, that's a bug — stop and report.

## Hard constraints

1. **No functional changes.** Every test that passed before must still pass. Every user-facing behavior must be identical. If you need to change behavior to make the abstraction work, *stop and ask* — that's a signal the abstraction is wrong.
2. **No chocoweb scaffolding yet.** Do not create `web/`, do not add WebRTC transports, do not add FastAPI. That's Phase 2, separate handoff.
3. **No new dependencies in `core/`** beyond what `chocopi` already uses (pipecat, the provider SDKs, etc.). Specifically: no pygame, no OWW, no tflite-runtime in core — those are kiosk-specific and stay in `pi/`.
4. **Python 3.11 only**, same as today (tflite-runtime constraint).
5. **uv as the env manager**, same as today. Use uv workspaces for the monorepo structure.
6. **Preserve all existing config files, prompts, models, and assets** at the new paths shown above. Models migrate from their current location to `assets/models/`.
7. **Preserve all existing install scripts and the systemd service** for the kiosk app. Update paths where needed but don't change the install UX.
8. **Use the flat package layout** (no `src/` subdir within `core/` or `pi/`). The package directory sits directly under the workspace member root.
9. **Preserve existing file organization within each package.** If the current code has `providers.py` as a single file, it stays as `providers.py` in its new location — do not split it into a `providers/` directory. Same for any other module. The refactor is about *where files live across packages*, not about *reshaping files within packages*. Reorganizing single files into directories is a separate concern for a future refactor.

## What goes in `core/chococore/` vs `pi/chocopi/`

This section describes *what responsibilities live in each package*, not how the files are organized within them. Whatever shape the current code has (single files, multiple files, etc.), preserve it — just relocate to the right package.

**chococore (platform-agnostic)**:
- Provider integrations (OpenAI Realtime, Gemini Live, Ultravox) and any switching logic
- Memory: session state, profiles, persistence layer, per-child learning levels
- Language: detection logic, per-language metadata, wake/sleep word mapping (but NOT the OWW models or runtime — just the names/labels)
- Prompts: all tutor prompts from `config.yml`
- Pipecat pipeline assembly: the graph of services *minus* the transport (transport is injected by the consuming app)
- Config schema and loading

**pi/chocopi/ (Pi/Linux-specific)**:
- `LocalAudioTransport` setup with PipeWire/PortAudio
- pygame display (animated character, transcript, idle state)
- OpenWakeWord integration: tflite runtime, model loading from `assets/models/`, mic capture for wake detection, sleep-word detection
- Mic ownership handoff between wake-word loop and conversation pipeline (current behavior, preserved)
- Pi-specific entry point and bash launcher

**pi/install/ (kiosk-specific operational concerns)**:
- systemd service unit
- install.sh and related provisioning scripts
- Bluetooth HSP/HFP audio config docs
- Anything OS/hardware-specific that isn't Python code

**assets/ (shared content)**:
- Wake-word models (`.tflite` and `.onnx`) — both formats kept; chocopi uses tflite today, chocoweb may use onnx later
- Sprite sheets, character images, sound effects
- Any other static content that could conceivably be used by both apps

**What's at the boundary** (think carefully): the pipeline assembly in core needs to produce a pipeline that the kiosk app can attach `LocalAudioTransport` to. Design the core's pipeline function to *accept a transport as a parameter*, not construct one. Same with display events — core emits events (e.g., "user spoke", "assistant speaking", "transcript update"); kiosk's display layer subscribes and renders. Don't put display abstraction *types* in core if pygame is the only consumer; a callback or event-emitter pattern is fine. Re-evaluate when chocoweb arrives.

## Recommended execution order

1. **Read the existing codebase end-to-end first.** Understand the current `src/chocopi/` structure, how the orchestrator wires things together, where state lives, what gets imported where. Don't start moving files until you have the mental model.
2. **Set up the uv workspace skeleton**: root `pyproject.toml`, `core/pyproject.toml`, `pi/pyproject.toml`, the package directories with empty `__init__.py` files, and the `assets/` structure. Verify `uv sync` works on the empty skeleton before moving any code.
3. **Move assets first**: relocate models, sprites, sounds into `assets/`. Update any path references in code to point at the new locations.
4. **Move code into `chococore/` in dependency order, leaves first** (the modules with fewest internal imports go first, modules that depend on others come later). Update imports after each move, run the kiosk app, verify it still works. Commit per step.
5. **Move kiosk-specific code into `pi/chocopi/` last**: transport setup, display, wake-word. Mostly relocation with import path changes.
6. **Move install scripts into `pi/install/`** and update any paths they reference.
7. **Update README** to explain the new structure and the two-product framing (chocopi exists today, chocoweb is planned).
8. **Verify end-to-end on a real Pi** before declaring done. The kiosk app must start, detect wake word, run a full conversation in each of the four languages, and shut down cleanly.

Don't try to do this as one giant commit. Each step should be a separately-reviewable commit that leaves the repo in a working state.

## Open questions to flag (don't decide unilaterally)

- **Config file location**: currently `config.yml` lives at repo root. Should it stay there (shared), or move under `pi/` since it's currently the only consumer? Lean toward keeping it at root *for now* since it's mostly platform-agnostic content (prompts, language settings) — but ask.
- **Sprite sheet sharing**: if existing pygame sprite sheets are pygame-specific in layout (single image with a grid the code blits from), they may not be directly shareable with a future web client that wants individual frames or a CSS sprite. For Phase 1, just move what exists into `assets/sprites/` — don't redesign. Phase 2 will figure out the shared-source-of-truth question.
- **Tests**: if there are existing tests, mirror the new structure. If there are none, don't add a testing framework as part of this refactor — that's separate scope.
- **Anything else that requires a behavior change to work** → stop and ask.

## Definition of done

- [ ] Repo restructured as described above
- [ ] `uv sync` works at the workspace root
- [ ] Kiosk app launches via the same command(s) as before (or with a clearly-documented replacement)
- [ ] Wake word detection works in all four languages
- [ ] Full conversation works end-to-end with at least one provider (OpenAI Realtime as the default)
- [ ] pygame display renders correctly with all sprites/animations
- [ ] `install.sh` (and any related provisioning scripts) runs cleanly end-to-end on a fresh Pi and produces a working installation
- [ ] systemd service starts and runs after install
- [ ] README updated to explain the new structure, two-product framing, and where chocoweb will eventually live
- [ ] All changes pushed to a feature branch (`refactor/extract-core` or similar), not merged to main yet — @codesmax wants to review

## Out of scope (do not do these)

- Any chocoweb / web app work
- Creating `web/` directory or any web scaffolding
- WebRTC transports
- FastAPI / server scaffolding
- onnxruntime-web wake-word integration
- Replacing pygame with anything
- Adding tests (unless tests already exist and need to be moved)
- Bumping Python version
- Switching env managers
- Changing provider APIs or prompts
- Performance optimization
- Adding new languages, models, or features
- Redesigning sprite sheets or other assets

## After this is done

Phase 2 handoff (separate doc) will cover building `web/chocoweb/` on top of the now-stable `chococore`. That handoff will be drafted once Phase 1 is reviewed and merged.

### Forward-looking context (informational only, do not implement)

This is *background to inform Phase 1 design decisions*, not a spec to build against. Don't add scaffolding, files, or dependencies for any of it. If a Phase 1 decision feels like it might constrain Phase 2 unnecessarily, raise it as an open question rather than guessing.

Phase 2 will add `web/chocoweb/` as a sibling app consuming `chococore`. Expected shape: FastAPI for the HTTP/WebSocket control plane, Pipecat's WebRTC transport (`SmallWebRTCTransport`) for real-time audio, a browser-based client with HTML/CSS/JS for the character display and transcript, and a tap-to-start UI for session activation (browser-side wake-word via onnxruntime-web is a possible future addition but not initial scope). Memory, providers, language detection, prompts, and pipeline assembly come from `chococore` unchanged. Wake-word detection on the Pi kiosk stays in chocopi using OWW/tflite — chocoweb does not use OWW initially.

Two implications this should subtly inform during Phase 1:

1. **Pipeline assembly in `chococore` should accept a transport as a parameter, not construct one.** Kiosk passes `LocalAudioTransport`; chocoweb will eventually pass `SmallWebRTCTransport`. Don't bake the transport choice into core.
2. **Display/state updates from core should flow through a generic mechanism** (callback, event emitter, async iterator — pick what feels most natural for the existing code), not a pygame-specific API. Pygame consumes the events in kiosk; HTML/JS will consume them later in web. If the existing code already has a clean abstraction here, preserve it. If it doesn't, a minimal one is fine — don't over-engineer.

Neither of these requires Phase 1 to know anything else about chocoweb. If during the refactor you find another spot where a Phase 1 choice could lock out Phase 2, flag it — don't guess.

---

**Final note to Claude Code**: the spirit of this task is "make the existing thing live in a better-organized house, no renovations." If you find yourself wanting to improve something that isn't strictly about extracting the core, write it down as a follow-up and keep going. @codesmax values minimal, focused changes and honest critical feedback — if something in this handoff doc seems wrong, flag it rather than working around it silently.
