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
            cb(null, `whisper-in-${Date.now()}-${Math.random().toString(16).slice(2)}${ext}`)
        },
    }),
    limits: { fileSize: 25 * 1024 * 1024 },
})

const app = express()
app.use(cors({ origin: true }))
app.use(express.json())

app.get('/health', (_req, res) => {
    res.json({ ok: true, service: 'whisper-transcribe' })
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

    let stderr = ''
    try {
        await new Promise((resolve, reject) => {
            const child = spawn(whisperBin, args, {
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
                            `whisper 退出码 ${code}。请确认已 pip install openai-whisper 且 PATH 中有 whisper。\n${stderr.slice(-1200)}`
                        )
                    )
            })
        })
    } catch (e) {
        await fs.unlink(inputPath).catch(() => {})
        await fs.rm(outDir, { recursive: true, force: true }).catch(() => {})
        console.error(e)
        return res.status(500).json({
            error: String(e.message || e),
            hint: '本服务通过子进程调用本机 whisper 命令；未安装或模型下载失败都会报错。',
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
    console.log(`Whisper 转写服务已启动：http://127.0.0.1:${port}`)
    console.log(`  POST /transcribe  表单字段名：audio`)
    console.log(`  模型：${process.env.WHISPER_MODEL || 'small'}  语言：${process.env.WHISPER_LANGUAGE || 'zh'}`)
})
