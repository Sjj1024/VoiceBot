import os
from dotenv import load_dotenv
import dashscope

# 从 .env 文件加载环境变量（如果存在）
load_dotenv()

# 以下为北京地域url，若使用新加坡地域的模型，需将url替换为：https://dashscope-intl.aliyuncs.com/api/v1
dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

text = "数据显示，一季度，我国服务出口7045.2亿元，同比增长11.2%；服务进口11183.8亿元，同比下降2.6%。服务贸易逆差4138.6亿元，比上年同期缩小1001.5亿元。知识密集型服务出口保持较快增长。一季度，知识密集型服务进出口7937.1亿元，同比增长1.6%，占总体服务进出口的比重为43.5%。知识密集型服务出口3842.6亿元，同比增长6.1%，其中，个人文化和娱乐服务、金融服务增长最快，增速分别为25.6%和16.1%；知识密集型服务进口4094.5亿元，同比下降2.3%"
# SpeechSynthesizer接口使用方法：dashscope.audio.qwen_tts.SpeechSynthesizer.call(...)
response = dashscope.MultiModalConversation.call(
    # 如需使用指令控制功能，请将model替换为qwen3-tts-instruct-flash
    model="qwen3-tts-flash",
    # 新加坡和北京地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
    # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key = "sk-xxx"
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    text=text,
    voice="Cherry",
    language_type="Chinese", # 建议与文本语种一致，以获得正确的发音和自然的语调。
    # 如需使用指令控制功能，请取消下方注释，并将model替换为qwen3-tts-instruct-flash
    # instructions='语速较快，带有明显的上扬语调，适合介绍时尚产品。',
    # optimize_instructions=True,
    stream=False
)
print(response)