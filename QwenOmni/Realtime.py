# 最小连接示例（与百炼文档一致）。API Key 写在 .env 或环境变量中，勿写入代码。
# pip install websocket-client python-dotenv
import json
import os
from pathlib import Path

import websocket


def _load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parent
    for path in (here / ".env", here.parent / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


_load_dotenv_files()

API_KEY = os.getenv("DASHSCOPE_API_KEY")
if not API_KEY:
    raise SystemExit("请设置环境变量 DASHSCOPE_API_KEY")

API_URL = (
    "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    "?model=qwen3.5-omni-plus-realtime"
)

headers = ["Authorization: Bearer " + API_KEY]


def on_open(ws):
    print(f"Connected to server: {API_URL}")


def on_message(ws, message):
    data = json.loads(message)
    print("Received event:", json.dumps(data, indent=2, ensure_ascii=False))


def on_error(ws, error):
    print("Error:", error)


ws = websocket.WebSocketApp(
    API_URL,
    header=headers,
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
)

ws.run_forever()
