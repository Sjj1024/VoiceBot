import os
import dashscope

# 若使用新加坡地域的模型，请释放下列注释
# dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
messages=[
    {
        "role": "system",
        "content": "请抽取用户的姓名与年龄信息，以JSON格式返回"
    },
    {
        "role": "user",
        "content": "大家好，我叫刘五，今年34岁，邮箱是liuwu@example.com，平时喜欢打篮球和旅游", 
    },
]

# 使用dashscope.Generation.call方法调用模型
response = dashscope.Generation.call(
    # 若没有配置环境变量，请用阿里云百炼API Key将下行替换为：api_key="sk-xxx",
    api_key=os.getenv('DASHSCOPE_API_KEY'),
    model="qwen-plus", 
    messages=messages,
    result_format='message',
    response_format={'type': 'json_object'}
    )
json_string = response.output.choices[0].message.content
print(json_string)