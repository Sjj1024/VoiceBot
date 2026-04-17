<template>
    <div class="page">
        <main class="card">
            <header class="card-head">
                <div class="title-block">
                    <span class="title">语音助手</span>
                    <span class="subtitle">
                        停顿约 {{ silenceMs }}ms 视为一句说完
                    </span>
                </div>
                <span
                    class="live-pill"
                    :class="{
                        on: isConversing && !isProcessing,
                        busy: isProcessing,
                    }"
                >
                    {{
                        isThinking
                            ? '思考中'
                            : isProcessing
                            ? '处理中'
                            : isConversing
                            ? '聆听中'
                            : '未开始'
                    }}
                </span>
            </header>

            <div class="chat-scroll" role="log" aria-live="polite">
                <div
                    v-if="messages.length === 0 && !userText"
                    class="chat-empty"
                >
                    开始对话后，你的发言会出现在这里。
                </div>
                <div
                    v-for="(msg, i) in messages"
                    :key="i"
                    class="row"
                    :class="msg.role"
                >
                    <div class="bubble">{{ msg.content }}</div>
                </div>
            </div>

            <transition name="fade">
                <div v-if="isThinking" class="thinking-bar" role="status">
                    <span class="thinking-spinner" aria-hidden="true" />
                    <span class="thinking-text">请等待思考完毕</span>
                </div>
            </transition>

            <div class="live-caption">
                <span class="live-label">当前识别</span>
                <span class="live-value">{{ userText || '—' }}</span>
            </div>

            <div class="actions">
                <button
                    type="button"
                    class="btn primary"
                    :disabled="isConversing"
                    @click="startConversation"
                >
                    开始对话
                </button>
                <button
                    type="button"
                    class="btn ghost"
                    :disabled="!isConversing"
                    @click="stopConversation"
                >
                    结束对话
                </button>
            </div>

            <p class="status-line">{{ status }}</p>
            <p class="hint">
                持续识别语音；说完稍停顿即自动请求回复。播报时麦克风会暂时关闭，播完后继续听。
            </p>
        </main>
    </div>
</template>

<script setup>
import { ref } from 'vue'

const messages = ref([])
const userText = ref('')
const status = ref('就绪：请用 Chrome / Edge 打开，并允许麦克风权限')
const isConversing = ref(false)
const isProcessing = ref(false)
/** 正在等待模型 HTTP 返回（区别于播报阶段的 isProcessing） */
const isThinking = ref(false)

const openclawBase = (import.meta.env.VITE_OPENCLAW_URL || '').trim()
const openclawApiKey = (import.meta.env.VITE_OPENCLAW_API_KEY || '').trim()
const openclawModel = (import.meta.env.VITE_OPENCLAW_MODEL || '').trim()

/** 停顿超过该时间（毫秒）认为一句说完，触发自动回复 */
const silenceMs = 1450

let userRequestedStop = false
let accFinal = ''
let recognition = null
let silenceTimer = null
/** 已调用 recognition.stop()，等待 onend 里收尾并走回复流程 */
let pendingSilenceCommit = false

/** 去掉 AI 回复中的 emoji / 绘文字（便于朗读与展示） */
const stripEmojis = (s) =>
    s
        .replace(/\p{Extended_Pictographic}/gu, '')
        .replace(/\uFE0F/g, '')
        .replace(/[\u{1F3FB}-\u{1F3FF}]/gu, '')
        .replace(/\s{2,}/g, ' ')
        .trim()

const clearSilenceTimer = () => {
    if (silenceTimer != null) {
        clearTimeout(silenceTimer)
        silenceTimer = null
    }
}

const scheduleSilenceCommit = () => {
    clearSilenceTimer()
    if (!isConversing.value || isProcessing.value) return
    silenceTimer = window.setTimeout(() => {
        silenceTimer = null
        if (!isConversing.value || isProcessing.value) return
        if (!userText.value.trim()) return
        isProcessing.value = true
        pendingSilenceCommit = true
        try {
            recognition?.stop()
        } catch (e) {
            pendingSilenceCommit = false
            isProcessing.value = false
            console.error(e)
        }
    }, silenceMs)
}

/** 播报结束（或失败）后再 resolve，便于接上下一轮识别 */
const speakAndWait = (text) =>
    new Promise((resolve) => {
        const utterance = new SpeechSynthesisUtterance(text)
        utterance.lang = 'zh-CN'
        utterance.onend = () => resolve()
        utterance.onerror = () => resolve()
        window.speechSynthesis.speak(utterance)
    })

const finishUserUtterance = async (text) => {
    const trimmed = text.trim()
    if (!trimmed) return

    messages.value.push({ role: 'user', content: trimmed })
    isThinking.value = true
    status.value = '请等待思考完毕…'
    let rawReply
    try {
        rawReply = await callOpenClaw(trimmed)
    } catch (e) {
        console.error(e)
        status.value = `回复失败：${e.message}`
        messages.value.push({
            role: 'assistant',
            content: `（请求失败）${e.message}`,
        })
        return
    } finally {
        isThinking.value = false
    }

    const reply = stripEmojis(rawReply)
    messages.value.push({ role: 'assistant', content: reply })

    status.value = '正在播报回复…'
    await speakAndWait(reply)
}

const tryStartRecognition = () => {
    if (!recognition || !isConversing.value || userRequestedStop) return
    accFinal = ''
    userText.value = ''
    status.value = '正在聆听，请说话…'
    window.setTimeout(() => {
        if (!isConversing.value || userRequestedStop || !recognition) return
        try {
            recognition.start()
        } catch (e) {
            if (e.name === 'InvalidStateError') {
                status.value = '识别已在运行，将保持聆听'
            } else {
                status.value = `无法开始聆听：${e.message}`
                console.error(e)
            }
        }
    }, 120)
}

// 1️⃣ 初始化语音识别
const initSpeech = () => {
    const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition

    if (!SpeechRecognition) {
        status.value =
            '当前浏览器不支持 Web Speech 识别（请用桌面版 Chrome 或 Edge）'
        alert(status.value)
        return false
    }

    recognition = new SpeechRecognition()
    recognition.lang = 'zh-CN'
    recognition.continuous = true
    recognition.interimResults = true

    recognition.onstart = () => {
        if (isConversing.value && !isProcessing.value) {
            status.value = '正在聆听，说完可稍停顿以触发回复'
        }
    }

    recognition.onaudiostart = () => {
        if (isConversing.value && !isProcessing.value) {
            status.value = '麦克风已打开，请说话'
        }
    }

    recognition.onspeechstart = () => {
        if (isConversing.value && !isProcessing.value) {
            status.value = '听到你的声音了…'
        }
    }

    recognition.onnomatch = () => {
        if (!isConversing.value || isProcessing.value) return
        status.value = '未匹配到有效语句，请再说一次'
        console.warn('SpeechRecognition nomatch')
    }

    recognition.onerror = (event) => {
        if (event.error === 'aborted') return
        const map = {
            not_allowed: '麦克风被拒绝：请在地址栏允许麦克风',
            aborted: '识别已中断',
            'no-speech': '未检测到语音，请靠近麦克风再试',
            network: '网络错误：语音识别需能访问 Google 服务',
            'service-not-allowed': '浏览器或系统禁止了语音服务',
        }
        status.value =
            map[event.error] || `识别出错：${event.error}，请打开控制台查看详情`
        console.error('SpeechRecognition error:', event.error, event)

        if (
            isConversing.value &&
            !userRequestedStop &&
            !isProcessing.value &&
            (event.error === 'no-speech' || event.error === 'network')
        ) {
            window.setTimeout(() => tryStartRecognition(), 400)
        }
    }

    recognition.onend = () => {
        if (userRequestedStop) {
            clearSilenceTimer()
            pendingSilenceCommit = false
            isProcessing.value = false
            userRequestedStop = false
            status.value = '对话已结束'
            return
        }

        if (pendingSilenceCommit) {
            pendingSilenceCommit = false
            const turnText = userText.value.trim()
            accFinal = ''
            userText.value = ''

            void (async () => {
                try {
                    if (turnText) await finishUserUtterance(turnText)
                } finally {
                    isProcessing.value = false
                    if (isConversing.value && !userRequestedStop) {
                        status.value = '回复结束，继续聆听中…'
                        tryStartRecognition()
                    }
                }
            })()
            return
        }

        // 识别会话意外结束：在对话中且不在处理回复时自动续听
        if (isConversing.value && !isProcessing.value) {
            tryStartRecognition()
        }
    }

    recognition.onresult = (event) => {
        if (!isConversing.value || isProcessing.value) return

        let finalChunk = ''
        let interim = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const piece = event.results[i][0].transcript
            if (event.results[i].isFinal) finalChunk += piece
            else interim += piece
        }
        accFinal += finalChunk
        userText.value = accFinal + interim
        scheduleSilenceCommit()
    }

    return true
}

const startConversation = () => {
    if (!recognition) {
        if (initSpeech() === false) return
    }
    isConversing.value = true
    userRequestedStop = false
    isProcessing.value = false
    pendingSilenceCommit = false
    accFinal = ''
    userText.value = ''
    clearSilenceTimer()
    window.speechSynthesis.cancel()
    try {
        recognition.start()
        status.value = '对话已开始：停顿约 1.5 秒视为一句说完'
    } catch (e) {
        if (e.name === 'InvalidStateError') {
            status.value = '识别已在运行中'
        } else {
            status.value = `无法启动：${e.message}`
            console.error(e)
        }
    }
}

const stopConversation = () => {
    if (!recognition) return
    userRequestedStop = true
    isConversing.value = false
    clearSilenceTimer()
    pendingSilenceCommit = false
    isProcessing.value = false
    window.speechSynthesis.cancel()
    try {
        recognition.abort()
    } catch (e) {
        console.error(e)
    }
    status.value = '已结束对话'
}

// 调用 AI（你可以换成 DeepSeek）
const callOpenClaw = async (text) => {
    const base = openclawBase || '/openclaw-api'
    const url = `${base.replace(/\/+$/, '')}/v1/chat/completions`

    const headers = { 'Content-Type': 'application/json' }
    if (openclawApiKey) headers.Authorization = `Bearer ${openclawApiKey}`

    const res = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify({
            model: openclawModel || 'openclaw/default',
            messages: [
                {
                    role: 'system',
                    content:
                        '回答请使用纯文本：不要输出任何表情符号、emoji、绘文字或颜文字；不要使用特殊装饰性符号；标点仅用中文常用标点。',
                },
                { role: 'user', content: text },
            ],
        }),
    })

    if (!res.ok) {
        const errText = await res.text().catch(() => '')
        throw new Error(
            `openclaw 接口请求失败：HTTP ${res.status} ${res.statusText}${
                errText ? `\n${errText.slice(0, 1200)}` : ''
            }`
        )
    }

    const data = await res.json()
    const content = data?.choices?.[0]?.message?.content
    if (typeof content !== 'string') {
        throw new Error(
            `openclaw 返回格式不符合预期（缺少 choices[0].message.content）：${JSON.stringify(
                data
            ).slice(0, 1200)}`
        )
    }
    return content
}
</script>

<style scoped>
.page {
    min-height: 100vh;
    box-sizing: border-box;
    padding: clamp(20px, 4vw, 40px) 126px 48px;
    background: radial-gradient(
            1200px 600px at 10% -10%,
            #e8eeff 0%,
            transparent 55%
        ),
        radial-gradient(900px 500px at 100% 0%, #f3e8ff 0%, transparent 50%),
        #f4f5f7;
    font-family: system-ui, -apple-system, 'Segoe UI', Roboto, 'PingFang SC',
        'Microsoft YaHei', sans-serif;
    color: #1a1d26;
}

.card {
    /* max-width: 560px; */
    margin: 0 auto;
    background: #fff;
    border-radius: 20px;
    box-shadow: 0 12px 40px rgba(15, 23, 42, 0.08),
        0 1px 0 rgba(255, 255, 255, 0.8) inset;
    border: 1px solid rgba(15, 23, 42, 0.06);
    padding: 22px 22px 20px;
}

.card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
    padding-bottom: 14px;
    border-bottom: 1px solid #eef0f4;
}

.title-block {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    min-width: 0;
}

.title {
    font-size: 1.25rem;
    font-weight: 650;
    letter-spacing: -0.02em;
}

.subtitle {
    font-size: 0.8125rem;
    color: #6b7280;
}

.live-pill {
    flex-shrink: 0;
    font-size: 0.75rem;
    font-weight: 600;
    padding: 6px 10px;
    border-radius: 999px;
    background: #f3f4f6;
    color: #6b7280;
}

.live-pill.on {
    background: #ecfdf5;
    color: #047857;
}

.live-pill.busy {
    background: #fff7ed;
    color: #c2410c;
}

.chat-scroll {
    height: min(42vh, 320px);
    min-height: 200px;
    overflow-y: auto;
    padding: 4px 2px 8px;
    scrollbar-width: thin;
    scrollbar-color: #cbd5e1 transparent;
}

.chat-scroll::-webkit-scrollbar {
    width: 6px;
}

.chat-scroll::-webkit-scrollbar-thumb {
    background: #cbd5e1;
    border-radius: 999px;
}

.chat-empty {
    font-size: 0.875rem;
    color: #9ca3af;
    text-align: center;
    padding: 48px 16px;
    line-height: 1.5;
}

.row {
    display: flex;
    margin-bottom: 10px;
}

.row.user {
    justify-content: flex-end;
}

.row.assistant {
    justify-content: flex-start;
}

.bubble {
    max-width: 88%;
    padding: 10px 14px;
    border-radius: 16px;
    font-size: 0.9375rem;
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-word;
}

.row.user .bubble {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
    color: #fff;
    border-bottom-right-radius: 6px;
}

.row.assistant .bubble {
    background: #f3f4f6;
    color: #111827;
    border-bottom-left-radius: 6px;
}

.thinking-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 12px 0 4px;
    padding: 10px 14px;
    border-radius: 12px;
    background: linear-gradient(90deg, #fffbeb 0%, #fef3c7 100%);
    border: 1px solid #fde68a;
    color: #92400e;
    font-size: 0.875rem;
    font-weight: 500;
}

.thinking-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid #fcd34d;
    border-top-color: #d97706;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
}

.thinking-text {
    letter-spacing: 0.02em;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}

.fade-enter-active,
.fade-leave-active {
    transition: opacity 0.2s ease, transform 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
    opacity: 0;
    transform: translateY(-4px);
}

.live-caption {
    margin-top: 12px;
    padding: 10px 12px;
    border-radius: 12px;
    background: #f9fafb;
    border: 1px solid #eef0f4;
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.live-label {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #9ca3af;
}

.live-value {
    font-size: 0.875rem;
    color: #374151;
    line-height: 1.45;
    min-height: 1.45em;
}

.actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 16px;
}

.btn {
    appearance: none;
    border: none;
    cursor: pointer;
    font-size: 0.9375rem;
    font-weight: 600;
    padding: 10px 18px;
    border-radius: 12px;
    transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease,
        transform 0.1s ease;
}

.btn:active:not(:disabled) {
    transform: scale(0.98);
}

.btn.primary {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
    color: #fff;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35);
}

.btn.primary:hover:not(:disabled) {
    box-shadow: 0 6px 18px rgba(37, 99, 235, 0.42);
}

.btn.ghost {
    background: #fff;
    color: #374151;
    border: 1px solid #e5e7eb;
}

.btn.ghost:hover:not(:disabled) {
    background: #f9fafb;
    border-color: #d1d5db;
}

.btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
    box-shadow: none;
}

.status-line {
    margin: 14px 0 0;
    font-size: 0.8125rem;
    color: #6b7280;
    line-height: 1.5;
}

.hint {
    margin: 8px 0 0;
    font-size: 0.75rem;
    color: #9ca3af;
    line-height: 1.55;
}
</style>
