"""chocoweb FastAPI server — /api/offer, /api/profiles, static files"""
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from chococore.config import CONFIG, IMAGES_PATH, SOUNDS_PATH
from chocoweb.pipeline import run_pipeline

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/images", StaticFiles(directory=IMAGES_PATH), name="images")
app.mount("/sounds", StaticFiles(directory=SOUNDS_PATH), name="sounds")

_handler = SmallWebRTCRequestHandler()


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/profiles")
async def get_profiles():
    result = []
    for key, profile in CONFIG.profiles.items():
        langs = {}
        for lang_code in (profile.learning_languages or {}):
            lang_config = CONFIG.languages.get(lang_code)
            if lang_config:
                langs[lang_code] = lang_config.language_name
        result.append({
            "key": key,
            "name": profile.name or key,
            "learning_languages": langs,
        })
    return result


@app.post("/api/offer")
async def offer(request: Request):
    body = await request.json()
    sdp_request = SmallWebRTCRequest(
        sdp=body["sdp"],
        type=body["type"],
        pc_id=body.get("pc_id"),
        restart_pc=body.get("restart_pc"),
        request_data=body.get("request_data") or body.get("requestData"),
    )
    data = sdp_request.request_data or {}
    profile_name = data.get("profile", CONFIG.profile or "default")
    language = data.get("language")

    async def on_connection(conn: SmallWebRTCConnection):
        transport = SmallWebRTCTransport(
            conn,
            params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
        )
        asyncio.create_task(run_pipeline(transport, profile_name, language))

    return await _handler.handle_web_request(sdp_request, on_connection)


@app.patch("/api/offer")
async def ice_candidate(request: Request):
    body = await request.json()
    patch_request = SmallWebRTCPatchRequest(
        pc_id=body["pc_id"],
        candidates=[
            IceCandidate(
                candidate=c["candidate"],
                sdp_mid=c.get("sdpMid") or c.get("sdp_mid", ""),
                sdp_mline_index=c.get("sdpMLineIndex") or c.get("sdp_mline_index", 0),
            )
            for c in body.get("candidates", [])
        ],
    )
    await _handler.handle_patch_request(patch_request)
    return {"status": "success"}
