"""
浏览器无法为 WebSocket 握手添加 Authorization，故由本机代理转发到 DashScope Realtime。

运行:
  在 QwenOmni/.env 或项目根 .env 中配置 DASHSCOPE_API_KEY 等变量（见下方），或 export 到 shell。
  pip install -r requirements.txt
  python proxy_server.py

  支持的环境变量（均可写在 .env）:
    DASHSCOPE_API_KEY, DASHSCOPE_REGION, DASHSCOPE_REALTIME_MODEL
    QWEN_OMNI_HTTP_HOST, QWEN_OMNI_HTTP_PORT, QWEN_OMNI_WS_HOST, QWEN_OMNI_WS_PORT

然后浏览器打开: http://127.0.0.1:8080/
页面会通过 ws://127.0.0.1:8765 连接本代理，代理再连百炼。
"""
from __future__ import annotations

import asyncio
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed


def _load_dotenv_files() -> None:
    """依次加载 QwenOmni/.env、项目根 .env；不覆盖已在进程环境中的变量。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parent
    for path in (here / ".env", here.parent / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


_load_dotenv_files()

STATIC_DIR = Path(__file__).resolve().parent / "static"
HTTP_HOST = os.environ.get("QWEN_OMNI_HTTP_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("QWEN_OMNI_HTTP_PORT", "8080"))
WS_HOST = os.environ.get("QWEN_OMNI_WS_HOST", "127.0.0.1")
WS_PORT = int(os.environ.get("QWEN_OMNI_WS_PORT", "8765"))

MODEL = os.environ.get("DASHSCOPE_REALTIME_MODEL", "qwen3.5-omni-plus-realtime")
REGION = os.environ.get("DASHSCOPE_REGION", "cn").lower()


def dashscope_realtime_url() -> str:
    if REGION == "intl":
        host = "dashscope-intl.aliyuncs.com"
    else:
        host = "dashscope.aliyuncs.com"
    return f"wss://{host}/api-ws/v1/realtime?model={MODEL}"


def start_http_server() -> None:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

        def log_message(self, fmt, *args):
            print(f"[http] {self.address_string()} - {fmt % args}")

    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    print(f"静态页面: http://{HTTP_HOST}:{HTTP_PORT}/")
    server.serve_forever()


async def relay_browser_to_dashscope(browser_ws, dashscope_ws) -> None:
    try:
        async for message in browser_ws:
            await dashscope_ws.send(message)
    except ConnectionClosed:
        pass
    finally:
        await dashscope_ws.close()


async def relay_dashscope_to_browser(browser_ws, dashscope_ws) -> None:
    try:
        async for message in dashscope_ws:
            await browser_ws.send(message)
    except ConnectionClosed:
        pass


async def handle_browser(browser_ws) -> None:
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        await browser_ws.close(code=4000, reason="Server: set DASHSCOPE_API_KEY")
        return

    url = dashscope_realtime_url()
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with websockets.connect(
            url,
            additional_headers=headers,
            max_size=None,
        ) as ds_ws:
            await asyncio.gather(
                relay_browser_to_dashscope(browser_ws, ds_ws),
                relay_dashscope_to_browser(browser_ws, ds_ws),
            )
    except Exception as e:
        try:
            await browser_ws.close(code=4001, reason=str(e)[:120])
        except Exception:
            pass
        print(f"[ws] upstream error: {e}")


async def ws_main() -> None:
    async with websockets.serve(
        handle_browser,
        WS_HOST,
        WS_PORT,
        max_size=None,
    ):
        print(f"浏览器 WebSocket 代理: ws://{WS_HOST}:{WS_PORT}")
        await asyncio.Future()


def main() -> None:
    if not STATIC_DIR.is_dir():
        raise SystemExit(f"缺少目录: {STATIC_DIR}")
    threading.Thread(target=start_http_server, daemon=True).start()
    asyncio.run(ws_main())


if __name__ == "__main__":
    main()
