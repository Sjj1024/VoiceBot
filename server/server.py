import json
import os
import shutil
import subprocess
import tempfile
import asyncio
import wave
from pathlib import Path

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from qwen_asr import Qwen3ASRModel
from pydantic import BaseModel

# 与 ttstest.py 一致：先加载 .env，再读环境变量（不依赖当前工作目录）
_ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(_ROOT / ".env")
except Exception:
    pass


def _load_tts_voices_catalog() -> dict:
    path = _ROOT / "tts_voices_catalog.json"
    if not path.is_file():
        return {"version": None, "voices": [], "error": "tts_voices_catalog.json not found"}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"version": None, "voices": [], "error": str(e)}


TTS_VOICES_CATALOG: dict = _load_tts_voices_catalog()

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

def get_device_and_dtype():
    if torch.cuda.is_available():
        return "cuda:0", torch.bfloat16
    return "cpu", torch.float32

ASR_MODEL_PATH = os.getenv("ASR_MODEL_PATH", "Qwen3-ASR-1.7B")

def get_model_source(local_path: str, hf_id: str) -> str:
    return local_path if os.path.isdir(local_path) else hf_id

DEVICE, DTYPE = get_device_and_dtype()
asr_model = Qwen3ASRModel.from_pretrained(
    get_model_source(ASR_MODEL_PATH, "Qwen/Qwen3-ASR-1.7B"),
    dtype=DTYPE,
    device_map=DEVICE,
    max_inference_batch_size=32,
    max_new_tokens=256,
)

_asr_lock = asyncio.Lock()


class DashscopeTTSBody(BaseModel):
    """与 ttstest.py 一致：仅 text 由请求传入，其余参数写死为示例脚本中的值。"""

    text: str
    voice: str = "Cherry"  # 新增语音参数，默认 Cherry


def _write_wav_pcm16le_mono(wav_path: str, pcm16le: bytes, sample_rate: int = 16000) -> None:
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16le)


def _transcribe_wav_sync(wav_path: str) -> dict:
    results = asr_model.transcribe(audio=wav_path, language=None)
    if not results:
        raise RuntimeError("Transcription failed")
    return {"language": results[0].language, "text": results[0].text}


@app.websocket("/ws/asr")
async def ws_asr(websocket: WebSocket):
    """
    Real-time ASR over WebSocket.

    Client sends: binary frames of PCM16LE mono @ 16kHz.
    Server sends: JSON text messages {type, ...}.
    """
    await websocket.accept()

    sample_rate = 16000
    bytes_per_second = sample_rate * 2  # mono int16
    decode_interval_s = float(os.getenv("ASR_WS_DECODE_INTERVAL_S", "1.2"))
    max_window_s = float(os.getenv("ASR_WS_MAX_WINDOW_S", "12"))
    max_window_bytes = int(max_window_s * bytes_per_second)

    buffer = bytearray()
    last_decode_at = 0.0
    last_text = ""

    await websocket.send_json(
        {
            "type": "ready",
            "format": "pcm_s16le",
            "sample_rate": sample_rate,
            "channels": 1,
            "decode_interval_s": decode_interval_s,
            "max_window_s": max_window_s,
        }
    )

    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                break

            chunk = data.get("bytes")
            if chunk:
                buffer.extend(chunk)
                if len(buffer) > max_window_bytes:
                    buffer[:] = buffer[-max_window_bytes:]

            now = asyncio.get_running_loop().time()
            if (now - last_decode_at) < decode_interval_s:
                continue

            if len(buffer) < int(0.6 * bytes_per_second):
                continue

            last_decode_at = now

            fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="qwen_asr_ws_")
            os.close(fd)
            try:
                _write_wav_pcm16le_mono(wav_path, bytes(buffer), sample_rate=sample_rate)
                async with _asr_lock:
                    out = await asyncio.to_thread(_transcribe_wav_sync, wav_path)

                text = (out.get("text") or "").strip()
                lang = out.get("language")

                if text and text != last_text:
                    last_text = text
                    await websocket.send_json({"type": "partial", "language": lang, "text": text})
            except Exception as e:
                await websocket.send_json({"type": "error", "message": str(e)})
            finally:
                if os.path.exists(wav_path):
                    os.remove(wav_path)

    except WebSocketDisconnect:
        return


@app.get("/")
def root():
    return {"message": "Qwen ASR backend is running"}


@app.get("/demo")
def demo_page():
    html_path = Path(__file__).with_name("demo.html")
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="demo.html not found")
    return FileResponse(str(html_path), media_type="text/html; charset=utf-8")


@app.post("/tts")
async def dashscope_tts(body: DashscopeTTSBody):
    """与 ttstest.py 相同方式调用 DashScope，返回结构与 print(response) 一致（JSON）。"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing DASHSCOPE_API_KEY in environment")

    # 与脚本一致：在主线程同步调用（避免部分 SDK 在非主线程行为不一致）
    try:
        import dashscope  # type: ignore

        dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"
        resp = dashscope.MultiModalConversation.call(
            model="qwen3-tts-flash",
            api_key=api_key,
            text=body.text,
            voice=body.voice,  # 使用请求中的语音参数
            language_type="Chinese",
            stream=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # dashscope 的响应类用 __getattr__ 映射字典键，hasattr(resp, "to_dict") 会误查键 "to_dict" 触发 KeyError
    if isinstance(resp, dict):
        payload = resp
    else:
        try:
            payload = resp.to_dict()
        except Exception:
            try:
                payload = dict(resp)
            except Exception:
                payload = {"raw": str(resp)}
    return JSONResponse(jsonable_encoder(payload))


@app.get("/tts/voices")
def list_tts_voices():
    """返回 DashScope Qwen TTS 支持的 voice 参数说明（见阿里云文档），数据来自 tts_voices_catalog.json。"""
    return jsonable_encoder(TTS_VOICES_CATALOG)


# 浏览器 MediaRecorder 常见 webm/opus；Windows 上 libsndfile 不认 webm，audioread 无 FFmpeg 时会 NoBackendError
_TRANSCODE_VIA_FFMPEG_SUFFIXES = {".webm", ".ogg", ".m4a", ".mp3"}

_ffmpeg_exe_cache: str | None | bool = False  # False = 未解析, None = 无, str = 路径


def _resolve_ffmpeg_exe() -> str | None:
    """IDE 启动的 Python 常拿不到用户 PATH；支持 FFMPEG_PATH，Windows 上再尝试 where.exe。"""
    global _ffmpeg_exe_cache
    if _ffmpeg_exe_cache is not False:
        return _ffmpeg_exe_cache  # type: ignore[return-value]

    for key in ("FFMPEG_PATH", "FFMPEG_BINARY"):
        raw = os.getenv(key)
        if not raw:
            continue
        raw = raw.strip().strip('"')
        if os.path.isfile(raw):
            _ffmpeg_exe_cache = raw
            return raw
        if os.path.isfile(raw + ".exe"):
            _ffmpeg_exe_cache = raw + ".exe"
            return _ffmpeg_exe_cache

    w = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if w:
        _ffmpeg_exe_cache = w
        return w

    if os.name == "nt":
        try:
            kw: dict = {"capture_output": True, "text": True, "timeout": 15}
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            r = subprocess.run(["where.exe", "ffmpeg"], **kw)
            if r.returncode == 0 and r.stdout:
                first = r.stdout.strip().splitlines()[0].strip()
                if first and os.path.isfile(first):
                    _ffmpeg_exe_cache = first
                    return first
        except Exception:
            pass

    _ffmpeg_exe_cache = None
    return None


def _ffmpeg_to_wav(src_path: str, wav_path: str) -> None:
    exe = _resolve_ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg not found")
    kw: dict = {"check": True, "capture_output": True, "timeout": 120}
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.run(
        [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", src_path, "-ar", "16000", "-ac", "1", wav_path],
        **kw,
    )


@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name")

    suffix = Path(file.filename).suffix.lower() or ".wav"
    if suffix not in {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}:
        suffix = ".wav"

    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="qwen_asr_")
    os.close(fd)
    wav_path: str | None = None
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        with open(tmp_path, "wb") as f:
            f.write(content)

        audio_path = tmp_path
        ffmpeg_exe = _resolve_ffmpeg_exe()
        if suffix in _TRANSCODE_VIA_FFMPEG_SUFFIXES and ffmpeg_exe:
            fd_w, wav_path = tempfile.mkstemp(suffix=".wav", prefix="qwen_asr_ff_")
            os.close(fd_w)
            try:
                await asyncio.to_thread(_ffmpeg_to_wav, tmp_path, wav_path)
            except subprocess.CalledProcessError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"ffmpeg 转码失败: {(e.stderr or e.stdout or b'').decode('utf-8', errors='replace')[:500]}",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"ffmpeg 转码失败: {e}")
            audio_path = wav_path
        elif suffix in {".webm", ".ogg"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    "无法解码 webm/ogg：当前 Python 进程找不到 ffmpeg（用 Cursor/IDE 启动时，PATH 常与 PowerShell 不一致）。"
                    " 请在项目根 .env 增加一行：FFMPEG_PATH=你的 ffmpeg.exe 绝对路径（例如 C:/ffmpeg/bin/ffmpeg.exe）；"
                    "或把 ffmpeg 加入系统 PATH 后彻底退出 IDE 再打开。下载: https://ffmpeg.org/download.html"
                ),
            )

        results = asr_model.transcribe(audio=audio_path, language=None)
        if not results:
            raise HTTPException(status_code=500, detail="Transcription failed")

        return {
            "language": results[0].language,
            "text": results[0].text,
        }
    finally:
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0：本机所有网卡，局域网内可用 http://<本机IP>:端口 访问；仅本机可设 UVICORN_HOST=127.0.0.1
    host = os.getenv("UVICORN_HOST", os.getenv("HOST", "0.0.0.0"))
    port = int(os.getenv("UVICORN_PORT", os.getenv("PORT", "8000")))
    log_level = os.getenv("UVICORN_LOG_LEVEL", "info")
    reload_ = _env_bool("UVICORN_RELOAD", default=False)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        reload=reload_,
        access_log=_env_bool("UVICORN_ACCESS_LOG", default=True),
        proxy_headers=_env_bool("UVICORN_PROXY_HEADERS", default=True),
    )
