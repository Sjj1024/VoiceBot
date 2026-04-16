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
        <p class="hint">
            对话模式：你在说话时持续识别；停顿约
            {{ silenceMs }}
            毫秒视为说完并自动回复；播报时麦克风会关闭，播完再继续听。
        </p>
        <p>当前识别：{{ userText || '（暂无）' }}</p>
    </div>
</template>

<script setup>
import { ref } from 'vue'

const messages = ref([])
const userText = ref('')
const status = ref('就绪：请用 Chrome / Edge 打开，并允许麦克风权限')
const isConversing = ref(false)
const isProcessing = ref(false)

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
