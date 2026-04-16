<template>
    <div class="container">
        <h2>🎤 AI语音助手</h2>

        <div class="chat-box">
            <div v-for="(msg, i) in messages" :key="i" :class="msg.role">
                {{ msg.content }}
            </div>
        </div>

        <div class="controls">
            <button
                type="button"
                :disabled="isConversing"
                @click="startConversation"
            >
                🎤 开始对话
            </button>
            <button
                type="button"
                :disabled="!isConversing"
                @click="stopConversation"
            >
                ⏹ 结束对话
            </button>
        </div>

        <p class="status">{{ status }}</p>
        <p class="hint">{{ listeningHint }}</p>
        <p>当前识别：{{ userText || '（暂无）' }}</p>
    </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const whisperBase = (import.meta.env.VITE_WHISPER_URL || '').trim()
const useWhisperAsr = Boolean(whisperBase)

const messages = ref([])
const userText = ref('')
const status = ref(
    useWhisperAsr
        ? '就绪：将使用自建 Whisper 转写（无需浏览器语音识别 VPN）'
        : '就绪：请用 Chrome / Edge 打开，并允许麦克风权限'
)
const isConversing = ref(false)
const isProcessing = ref(false)

const silenceMs = 1450

const listeningHint = computed(() =>
    useWhisperAsr
        ? `免 VPN 模式：语音经 MediaRecorder 上传到你的 Whisper 服务；停顿约 ${silenceMs} 毫秒且检测到人声后，会提交本段录音转写。`
        : `对话模式：你在说话时持续识别；停顿约 ${silenceMs} 毫秒视为说完并自动回复；播报时麦克风会关闭，播完再继续听。配置环境变量 VITE_WHISPER_URL 可改为自建 Whisper。`,
)

let userRequestedStop = false
let accFinal = ''
let recognition = null
let silenceTimer = null
let pendingSilenceCommit = false

/** Whisper 路径：麦克风与电平检测 */
let whisperStream = null
let whisperAudioCtx = null
let whisperAnalyser = null
let whisperDataArray = null
let whisperRaf = 0
let whisperMediaRecorder = null
let whisperChunks = []
let whisperLastVoiceAt = 0
let whisperHadVoice = false
/** 低于该 RMS 视为静音（可按环境微调） */
const WHISPER_VOICE_RMS = 0.038

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

const speakAndWait = (text) =>
    new Promise((resolve) => {
        const utterance = new SpeechSynthesisUtterance(text)
        utterance.lang = 'zh-CN'
        utterance.onend = () => resolve()
        utterance.onerror = () => resolve()
        window.speechSynthesis.speak(utterance)
    })

const transcribeWithWhisperServer = async (blob) => {
    const base = whisperBase.replace(/\/$/, '')
    const form = new FormData()
    form.append('audio', blob, 'utterance.webm')
    const res = await fetch(`${base}/transcribe`, {
        method: 'POST',
        body: form,
    })
    const raw = await res.text()
    if (!res.ok) {
        throw new Error(raw || `HTTP ${res.status}`)
    }
    try {
        const data = JSON.parse(raw)
        return (data.text || '').trim()
    } catch {
        return ''
    }
}

const finishUserUtterance = async (text) => {
    const trimmed = text.trim()
    if (!trimmed) return

    messages.value.push({ role: 'user', content: trimmed })
    const rawReply = await callAI(trimmed)
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

const stopWhisperPipeline = () => {
    if (whisperRaf) {
        cancelAnimationFrame(whisperRaf)
        whisperRaf = 0
    }
    try {
        if (whisperMediaRecorder && whisperMediaRecorder.state !== 'inactive') {
            whisperMediaRecorder.stop()
        }
    } catch {
        /* ignore */
    }
    whisperMediaRecorder = null
    whisperChunks = []
    if (whisperStream) {
        whisperStream.getTracks().forEach((t) => t.stop())
        whisperStream = null
    }
    if (whisperAudioCtx) {
        whisperAudioCtx.close().catch(() => {})
        whisperAudioCtx = null
    }
    whisperAnalyser = null
    whisperDataArray = null
    whisperHadVoice = false
    whisperLastVoiceAt = 0
}

const pickRecorderMime = () => {
    const c = 'audio/webm;codecs=opus'
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.(c))
        return c
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.('audio/webm'))
        return 'audio/webm'
    return ''
}

const startWhisperMediaSegment = () => {
    if (!whisperStream || !isConversing.value || userRequestedStop) return
    const mime = pickRecorderMime()
    whisperChunks = []
    whisperMediaRecorder = mime
        ? new MediaRecorder(whisperStream, { mimeType: mime })
        : new MediaRecorder(whisperStream)
    whisperMediaRecorder.ondataavailable = (e) => {
        if (e.data?.size) whisperChunks.push(e.data)
    }
    whisperMediaRecorder.start(400)
}

const whisperSilenceLoop = () => {
    if (!useWhisperAsr || !isConversing.value || userRequestedStop) {
        whisperRaf = 0
        return
    }
    if (!whisperAnalyser || !whisperDataArray) {
        whisperRaf = requestAnimationFrame(whisperSilenceLoop)
        return
    }

    if (!isProcessing.value) {
        whisperAnalyser.getByteTimeDomainData(whisperDataArray)
        const n = whisperDataArray.length
        let sum = 0
        for (let i = 0; i < n; i++) {
            const x = (whisperDataArray[i] - 128) / 128
            sum += x * x
        }
        const rms = Math.sqrt(sum / n)
        if (rms > WHISPER_VOICE_RMS) {
            whisperLastVoiceAt = Date.now()
            whisperHadVoice = true
        }
        if (
            whisperHadVoice &&
            Date.now() - whisperLastVoiceAt >= silenceMs &&
            whisperMediaRecorder &&
            whisperMediaRecorder.state === 'recording'
        ) {
            whisperHadVoice = false
            void commitWhisperTurn()
        }
    }

    whisperRaf = requestAnimationFrame(whisperSilenceLoop)
}

const commitWhisperTurn = async () => {
    if (!isConversing.value || userRequestedStop) return
    if (!whisperMediaRecorder || whisperMediaRecorder.state !== 'recording') return

    isProcessing.value = true

    try {
        await new Promise((resolve, reject) => {
            whisperMediaRecorder.onstop = () => resolve()
            whisperMediaRecorder.onerror = () => reject(new Error('MediaRecorder error'))
            whisperMediaRecorder.stop()
        })
    } catch (e) {
        isProcessing.value = false
        console.error(e)
        status.value = '录音结束失败，请重试'
        if (isConversing.value && !userRequestedStop) startWhisperMediaSegment()
        return
    }

    const blob = new Blob(whisperChunks, {
        type: whisperMediaRecorder.mimeType || 'audio/webm',
    })
    whisperChunks = []

    if (blob.size < 1800) {
        isProcessing.value = false
        if (isConversing.value && !userRequestedStop) {
            startWhisperMediaSegment()
            status.value = '片段太短，已丢弃，请继续说话'
        }
        return
    }

    try {
        status.value = '正在转写（Whisper）…'
        const text = (await transcribeWithWhisperServer(blob)).trim()
        userText.value = text
        if (text) await finishUserUtterance(text)
        else status.value = '未识别到有效文字，请再说一次'
    } catch (e) {
        console.error(e)
        status.value = `转写失败：${e.message || e}`
    } finally {
        isProcessing.value = false
        if (isConversing.value && !userRequestedStop) {
            startWhisperMediaSegment()
            status.value = '继续聆听中…'
        }
    }
}

const startWhisperConversation = async () => {
    stopWhisperPipeline()
    try {
        whisperStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
            },
            video: false,
        })
    } catch (e) {
        status.value = `无法打开麦克风：${e.message || e}`
        console.error(e)
        return
    }

    whisperAudioCtx = new AudioContext()
    const source = whisperAudioCtx.createMediaStreamSource(whisperStream)
    whisperAnalyser = whisperAudioCtx.createAnalyser()
    whisperAnalyser.fftSize = 1024
    whisperAnalyser.smoothingTimeConstant = 0.35
    source.connect(whisperAnalyser)
    whisperDataArray = new Uint8Array(whisperAnalyser.fftSize)

    isConversing.value = true
    userRequestedStop = false
    isProcessing.value = false
    userText.value = ''
    whisperHadVoice = false
    whisperLastVoiceAt = 0

    startWhisperMediaSegment()
    whisperRaf = requestAnimationFrame(whisperSilenceLoop)
    status.value = '对话已开始（Whisper）：说完一句请稍停顿'
}

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

const startConversation = async () => {
    if (useWhisperAsr) {
        await startWhisperConversation()
        return
    }

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
    userRequestedStop = true
    isConversing.value = false
    clearSilenceTimer()
    pendingSilenceCommit = false
    isProcessing.value = false
    window.speechSynthesis.cancel()

    if (useWhisperAsr) {
        stopWhisperPipeline()
        status.value = '已结束对话'
        return
    }

    if (!recognition) return
    try {
        recognition.abort()
    } catch (e) {
        console.error(e)
    }
    status.value = '已结束对话'
}

const callAI = async (text) => {
    const res = await fetch(
        'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
        {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: 'Bearer sk-0a564ebc8daa48d69002273afe06c0ca',
            },
            body: JSON.stringify({
                model: 'qwen-plus',
                messages: [
                    {
                        role: 'system',
                        content:
                            '回答请使用纯文本：不要输出任何表情符号、emoji、绘文字或颜文字；不要使用特殊装饰性符号；标点仅用中文常用标点。',
                    },
                    { role: 'user', content: text },
                ],
            }),
        }
    )

    const data = await res.json()
    return data.choices[0].message.content
}
</script>

<style>
.container {
    max-width: 600px;
    margin: 40px auto;
}

.chat-box {
    border: 1px solid #ccc;
    padding: 10px;
    height: 300px;
    overflow-y: auto;
}

.user {
    text-align: right;
    color: blue;
}

.assistant {
    text-align: left;
    color: green;
}

.controls {
    margin-top: 10px;
}

.controls button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.status {
    color: #555;
    font-size: 14px;
    margin-top: 8px;
}

.hint {
    color: #888;
    font-size: 13px;
    margin-top: 6px;
}
</style>
