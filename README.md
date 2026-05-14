# Vue3Speech

基于 **Vue 3 + Vite** 的语音对话前端：支持麦克风输入（浏览器识别或 HTTP 转写）、**OpenAI 兼容**对话接口，以及 **HTTP TTS** 播报（音色列表、合成与播放进度提示）。

## 功能概览

-   **对话**：语音或文字输入，历史消息作为上下文发往模型。
-   **语音识别（二选一）**
    -   未配置 `VITE_WHISPER_URL`：使用 **Web Speech API**（桌面 Chrome / Edge 体验较好）。
    -   已配置：使用 **MediaRecorder** 录音，将音频 **POST** 到转写服务（如 `/transcribe`），响应形如 `{"language":"Chinese","text":"..."}`。
-   **语音合成**：**POST** `/tts`，请求体含 `text`、`voice` 等；响应使用 `output.audio.url`（或兼容顶层 `url`）播放。合成与播报阶段在界面有明确进度提示；助手气泡在拿到音频地址后与播放同步展示。
-   **音色**：启动时 **GET** `/tts/voices` 拉取列表，下拉选择并写入本地存储；默认音色可由 `VITE_TTS_VOICE` 指定。

## 快速开始

```bash
npm install
cp .env.example .env
# 按你的环境编辑 .env（见下节）
npm run dev
```

开发服务器默认监听 `0.0.0.0`，并启用 **HTTPS**（`@vitejs/plugin-basic-ssl`）。浏览器需允许麦克风权限。

## 环境变量

复制 `.env.example` 为 `.env` 后按需修改，常用项如下：

| 变量                           | 说明                                                                        |
| ------------------------------ | --------------------------------------------------------------------------- |
| `VITE_OPENCLAW_URL`            | OpenAI 兼容 API 根地址（如本地 OpenClaw），会请求聊天补全接口。             |
| `VITE_OPENCLAW_API_KEY`        | 可选，接口需要鉴权时填写。                                                  |
| `VITE_OPENCLAW_MODEL`          | 可选，模型名。                                                              |
| `VITE_WHISPER_URL`             | 转写服务根地址；开发环境可填 `/speech-api` 走 Vite 代理。                   |
| `VITE_WHISPER_FORM_FIELD`      | 上传音频的表单字段名，默认与示例一致时需与后端约定（如 `audio` / `file`）。 |
| `VITE_WHISPER_TRANSCRIBE_PATH` | 转写路径，默认 `/transcribe`。                                              |
| `VITE_TTS_URL`                 | TTS 根地址；不填时主流程里默认使用 `/speech-api`。                          |
| `VITE_TTS_VOICE`               | 默认音色（如 `Cherry`）。                                                   |
| `VITE_TTS_VOICES_PATH`         | 音色列表路径，默认 `/tts/voices`。                                          |

更细的注释见仓库内 [.env.example](.env.example)。

## 开发代理（Vite）

[vite.config.ts](vite.config.ts) 中配置了示例代理，**IP 与端口请按你本机服务修改**：

-   `/speech-api` → 语音相关服务（转写、TTS、`/tts/voices` 等）。
-   `/openclaw-api` → OpenAI 兼容对话服务（若前端通过该前缀访问）。

前端在 `.env` 里把 `VITE_*_URL` 指到上述前缀（如 `/speech-api`）即可避免浏览器跨域问题。

## 脚本

| 命令                     | 说明                                                                          |
| ------------------------ | ----------------------------------------------------------------------------- |
| `npm run dev`            | 启动开发服务器。                                                              |
| `npm run build`          | 类型检查并构建生产包。                                                        |
| `npm run preview`        | 预览构建结果。                                                                |
| `npm run whisper-server` | 运行仓库内 [server/index.mjs](server/index.mjs)（若你使用该 Node 转写服务）。 |

## Qwen-Omni 实时对话（独立示例）

目录 [QwenOmni/](QwenOmni/) 内含基于阿里云 **Qwen-Omni-Realtime** 的浏览器演示：本机 **Python 代理**（WebSocket 转发 + 静态页），需在 `QwenOmni/.env` 或项目根 `.env` 配置 `DASHSCOPE_API_KEY`。详见该目录内 `proxy_server.py` 顶部说明。

## 浏览器与权限

-   语音对话依赖 **麦克风**；HTTPS 或 localhost 下权限策略更一致。
-   Web Speech 识别在非 Chromium 内核或网络受限环境下可能不可用，可改用 HTTP 转写模式。

## 许可证

私有项目（`package.json` 中 `"private": true`）；对外分发时请自行补充许可证说明。

## SKILL 是输入

Skill 是告诉 ai 输入规则，以及注意事项

## MCP 是输出

mcp 是告诉 ai 有哪些能力可以做哪些事
