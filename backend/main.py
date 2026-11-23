import io
import json
import threading
from pathlib import Path
from typing import Dict, List

import ollama
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pocket_tts import TTSModel, export_model_state
from pydantic import BaseModel

from tool_registry import (
    create_path_approval,
    execute_tool,
    get_enabled_tools,
    resolve_path_approval,
    wait_for_path_approval,
)
from tools.spotify_desktop import control as spotify_desktop_control, status as spotify_desktop_status


DEFAULT_TTS_VOICE = "jarvis.wav"
OLLAMA_MODEL = "jarvis"
WEB_SEARCH_INSTRUCTION = (
    "Use the tavily_web_search tool when the user asks for a web search or when answering "
    "questions about live, current, or recent information. Base claims on the returned "
    "results and cite the source title and URL. If search is unavailable or returns no "
    "useful results, say so instead of implying that you searched."
    " When the user asks to control Spotify, use spotify_control. Use action=search_play and pass the requested "
    "song or artist in query; use liked for Liked Songs, and play, pause, next, or previous for transport controls."
)

app = FastAPI(title="Pocket Jarvis Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    messages: List[Dict]


class TTSRequest(BaseModel):
    text: str
    voice: str = DEFAULT_TTS_VOICE


class ToolApprovalRequest(BaseModel):
    approval_id: str
    approved: bool


_tts_model = None
_voice_states = {}
_tts_lock = threading.Lock()
_voice_dir = Path(__file__).resolve().parent / "voices"
_supported_voices = {
    "alba",
    "anna",
    "azelma",
    "bill_boerst",
    "caro_davy",
    "charles",
    "cosette",
    "eponine",
    "eve",
    "fantine",
    "george",
    "javert",
    "jean",
    "jane",
    "marius",
    "mary",
    "michael",
    "paul",
    "peter_yearsley",
    "stuart_bell",
    "vera",
}


def get_tts_model():
    global _tts_model
    if _tts_model is None:
        _tts_model = TTSModel.load_model(language="english_18m_2026-10")
    return _tts_model


def synthesize_speech(text: str, voice: str) -> bytes:
    with _tts_lock:
        model = get_tts_model()
        voice_name = voice.strip()
        preset = voice_name.lower()

        if preset in _supported_voices:
            cache_key = f"preset:{preset}"
            voice_source = preset
        else:
            voice_path = Path(voice_name).expanduser()
            if not voice_path.is_absolute():
                voice_path = _voice_dir / voice_path
            voice_path = voice_path.resolve()
            try:
                voice_path.relative_to(_voice_dir.resolve())
            except ValueError as error:
                raise ValueError("Custom voice files must be inside backend/voices") from error

            if not voice_path.is_file():
                raise ValueError(
                    f"Voice file not found: {voice_path}. Put an authorized WAV or MP3 sample "
                    "in backend/voices and set JARVIS_TTS_VOICE to its filename."
                )

            if voice_path.suffix.lower() == ".safetensors":
                cache_key = f"file:{voice_path}"
                voice_source = voice_path
            elif voice_path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
                if not model.has_voice_cloning:
                    raise RuntimeError(
                        "Pocket TTS loaded without voice-cloning weights. Accept the Pocket TTS "
                        "model terms on Hugging Face and sign in with `hf auth login`, then "
                        "restart Jarvis."
                    )
                state_path = voice_path.with_suffix(".safetensors")
                cache_key = f"file:{state_path}"
                if (
                    not state_path.is_file()
                    or state_path.stat().st_mtime < voice_path.stat().st_mtime
                ):
                    state = model.get_state_for_audio_prompt(voice_path, truncate=True)
                    export_model_state(state, state_path)
                    _voice_states[cache_key] = state
                voice_source = state_path
            else:
                raise ValueError("Custom voice must be WAV, MP3, M4A, FLAC, OGG, or SAFETENSORS")

        if cache_key not in _voice_states:
            _voice_states[cache_key] = model.get_state_for_audio_prompt(voice_source)
        audio = model.generate_audio(_voice_states[cache_key], text)

    buffer = io.BytesIO()
    sf.write(buffer, audio.detach().cpu().numpy(), model.sample_rate, format="WAV")
    return buffer.getvalue()


@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        def generate():
            messages = [
                {"role": "system", "content": WEB_SEARCH_INSTRUCTION},
                *request.messages,
            ]
            tools = get_enabled_tools()
            max_tool_rounds = 5

            for round_number in range(max_tool_rounds + 1):
                stream = ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=messages,
                    tools=tools if round_number < max_tool_rounds else [],
                    stream=True,
                    think=False,
                )

                content_parts = []
                tool_calls = []

                for part in stream:
                    message = part.message
                    content = message.content or ""
                    if content:
                        content_parts.append(content)
                    if message.tool_calls:
                        tool_calls.extend(message.tool_calls)

                if not tool_calls:
                    for content in content_parts:
                        yield json.dumps({"content": content}) + "\n"
                    return

                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(content_parts),
                        "tool_calls": tool_calls,
                    }
                )
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    arguments = tool_call.function.arguments or {}
                    path_confirmed = False
                    try:
                        if function_name == "manage_files_and_folders":
                            from tools.folder_and_file_creator import check_path_access

                            path = arguments.get("path", "")
                            mode = arguments.get("mode", "create")
                            access = check_path_access(path)
                            if access == "blocked":
                                raise PermissionError(
                                    "This path is blocked or invalid. No files were changed."
                                )
                            if access == "confirmation_required" or mode == "delete":
                                approval_id = create_path_approval(
                                    path, mode
                                )
                                yield json.dumps(
                                    {
                                        "confirmation_required": {
                                            "approval_id": approval_id,
                                            "path": path,
                                            "mode": mode,
                                            "content": arguments.get("content", ""),
                                        }
                                    }
                                ) + "\n"
                                path_confirmed = wait_for_path_approval(approval_id)
                                if not path_confirmed:
                                    result = "The user did not approve this file change. No files were changed."
                                else:
                                    result = execute_tool(
                                        function_name, arguments, path_confirmed=True
                                    )
                            else:
                                result = execute_tool(function_name, arguments)
                        else:
                            result = execute_tool(function_name, arguments)
                    except Exception as error:
                        result = f"Tool error ({function_name}): {error}"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": function_name,
                            "content": result,
                        }
                    )

            yield json.dumps({"content": "I couldn't finish the tool request within the allowed number of steps."}) + "\n"

        return StreamingResponse(generate(), media_type="application/x-ndjson")
    except Exception as error:
        return {"error": str(error)}


@app.post("/tool-approval")
async def tool_approval(request: ToolApprovalRequest):
    if not resolve_path_approval(request.approval_id, request.approved):
        raise HTTPException(status_code=404, detail="This confirmation request is no longer active.")
    return {"status": "resolved"}


@app.post("/tts")
async def tts(request: TTSRequest):
    try:
        text = request.text.strip()
        if not text:
            return {"error": "No text provided"}
        wav = await run_in_threadpool(synthesize_speech, text, request.voice)
        return Response(content=wav, media_type="audio/wav")
    except Exception as error:
        print(f"TTS error: {error}")
        return {"error": str(error)}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/spotify/status")
async def spotify_status():
    return await run_in_threadpool(spotify_desktop_status)


class SpotifyControlRequest(BaseModel):
    action: str
    query: str = ""


@app.post("/spotify/control")
async def spotify_control(request: SpotifyControlRequest):
    return {"message": await run_in_threadpool(spotify_desktop_control, request.action, request.query)}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8008)
