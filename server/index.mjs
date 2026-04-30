/**
 * 自建 Whisper 转写服务（Node）
 *
 * 依赖本机已安装 OpenAI Whisper CLI：
 *   pip install -U openai-whisper
 *   确保终端能执行：whisper --help
 *
 * 环境变量（可选）：
 *   PORT              默认 8787
 *   WHISPER_BIN       默认可执行文件 whisper
 *   WHISPER_MODEL     默认 small（tiny/base/small/medium/large）
 *   WHISPER_LANGUAGE  默认 zh
 *   WHISPER_FP16      设为 0 时传 --fp16 False（CPU 上常需要）
 */

import cors from 'cors'
import express from 'express'
import multer from 'multer'
import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

const upload = multer({
    storage: multer.diskStorage({
        destination: os.tmpdir(),
        filename: (_req, file, cb) => {
            const ext =
                path.extname(file.originalname || '') ||
                (file.mimetype?.includes('webm') ? '.webm' : '.bin')
            cb(
                null,
                `whisper-in-${Date.now()}-${Math.random()
                    .toString(16)
                    .slice(2)}${ext}`
            )
        },
    }),
    limits: { fileSize: 25 * 1024 * 1024 },
})

const app = express()
app.use(cors({ origin: true }))
app.use(express.json())

app.get('/health', (_req, res) => {
    res.json({
        ok: true,
        service: 'speech-server',
        features: ['transcribe', 'tts'],
    })
})

app.post('/tts', async (req, res) => {
    const apiKey = (process.env.DASHSCOPE_API_KEY || '').trim()
    if (!apiKey) {
        return res.status(400).json({
            error: '缺少环境变量 DASHSCOPE_API_KEY（用于 DashScope TTS）',
        })
    } else {
        console.log('loss dashscope apiKey')
    }

    const text = String(req.body?.text || '').trim()
    const voice = String(req.body?.voice || 'Cherry').trim() || 'Cherry'
    const language_type =
        String(req.body?.language_type || 'Chinese').trim() || 'Chinese'

    if (!text) {
        return res.status(400).json({ error: '缺少参数 text' })
    }

    let upstreamRes
    try {
        upstreamRes = await fetch(
            'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation',
            {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${apiKey}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    model: 'qwen3-tts-flash',
                    input: { text, voice, language_type },
                }),
            }
        )
    } catch (e) {
        console.error(e)
        return res.status(502).json({ error: `TTS 上游请求失败：${e.message}` })
    }

    if (!upstreamRes.ok) {
        const errText = await upstreamRes.text().catch(() => '')
        return res.status(502).json({
            error: `TTS 上游返回异常：HTTP ${upstreamRes.status} ${upstreamRes.statusText}`,
            detail: errText.slice(0, 2000),
        })
    }

    const data = await upstreamRes.json().catch(() => null)
    const url = data?.output?.audio?.url
    if (typeof url !== 'string' || !url) {
        return res.status(502).json({
            error: 'TTS 上游返回缺少 audio.url',
            data,
        })
    }

    return res.json({
        url,
        id: data?.output?.audio?.id,
        expires_at: data?.output?.audio?.expires_at,
        request_id: data?.request_id,
        usage: data?.usage,
    })
})

app.post('/transcribe', upload.single('audio'), async (req, res) => {
    if (!req.file?.path) {
        return res.status(400).json({ error: '缺少表单字段 audio（文件）' })
    }

    const inputPath = req.file.path
    const outDir = await fs.mkdtemp(path.join(os.tmpdir(), 'whisper-out-'))

    const whisperBin = process.env.WHISPER_BIN || 'whisper'
    const model = process.env.WHISPER_MODEL || 'small'
    const language = process.env.WHISPER_LANGUAGE || 'zh'

    let stderr = ''
    try {
        const makeArgs = () => {
            const args = [
                inputPath,
                '--model',
                model,
                '--language',
                language,
                '--output_dir',
                outDir,
                '--output_format',
                'txt',
            ]
            if (process.env.WHISPER_FP16 === '0') {
                args.push('--fp16', 'False')
            }
            return args
        }

        const run = (bin, args) =>
            new Promise((resolve, reject) => {
                const child = spawn(bin, args, {
                    stdio: ['ignore', 'ignore', 'pipe'],
                })
                child.stderr?.on('data', (c) => {
                    stderr += String(c)
                })
                child.on('error', reject)
                child.on('close', (code) => {
                    if (code === 0) resolve()
                    else
                        reject(
                            new Error(
                                `whisper 退出码 ${code}。\n${stderr.slice(
                                    -1200
                                )}`
                            )
                        )
                })
            })

        try {
            await run(whisperBin, makeArgs())
        } catch (e) {
            // 常见：系统里没有 whisper 可执行文件（ENOENT）。自动回退到 python -m whisper。
            if (
                e?.code === 'ENOENT' ||
                /spawn\s+whisper\s+ENOENT/.test(String(e))
            ) {
                const py = process.env.WHISPER_PYTHON || 'python3'
                stderr += `\n[warn] ${whisperBin} not found, fallback: ${py} -m whisper\n`
                await run(py, ['-m', 'whisper', ...makeArgs()])
            } else {
                throw e
            }
        }
    } catch (e) {
        await fs.unlink(inputPath).catch(() => {})
        await fs.rm(outDir, { recursive: true, force: true }).catch(() => {})
        console.error(e)
        return res.status(500).json({
            error: String(e.message || e),
            hint: '本服务通过子进程调用本机 whisper（或 python -m whisper）；未安装、PATH 未包含、或模型下载失败都会报错。',
        })
    }

    const stem = path.parse(inputPath).name
    const txtPath = path.join(outDir, `${stem}.txt`)

    let text = ''
    try {
        text = (await fs.readFile(txtPath, 'utf8')).trim()
    } catch {
        text = ''
    }

    await fs.unlink(inputPath).catch(() => {})
    await fs.rm(outDir, { recursive: true, force: true }).catch(() => {})

    return res.json({ text })
})

const port = Number(process.env.PORT || 8787)
app.listen(port, () => {
    console.log(`语音服务已启动：http://127.0.0.1:${port}`)
    console.log(`  POST /transcribe  表单字段名：audio`)
    console.log(`  POST /tts        JSON: { text, voice?, language_type? }`)
    console.log(
        `  模型：${process.env.WHISPER_MODEL || 'small'}  语言：${
            process.env.WHISPER_LANGUAGE || 'zh'
        }`
    )
})
