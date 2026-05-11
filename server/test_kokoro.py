import soundfile as sf
from kokoro import KPipeline

def main():
    # 1️⃣ 初始化中文语音管线
    # lang_code='z' 代表中文普通话
    print("正在初始化语音管线...")
    pipeline = KPipeline(lang_code='z')
    
    # 2️⃣ 准备测试文本
    # 这里的中文和英文混合效果很好
    text = """你好！我是 Kokoro 语音合成模型。
    我是一个轻量级的文本转语音系统，只有八千两百万个参数。
    我可以在没有显卡的普通电脑上流畅运行，而且声音很自然。
    现在，我正在为你朗读这段测试文字。"""
    
    # 3️⃣ 选择音色并生成语音
    # 中文音色列表：zf_xiaobei(温柔), zf_xiaoxiao(成熟), zm_yunyang(浑厚)等
    voice = "zf_xiaoxiao"  # 成熟稳重的女声
    print(f"正在使用音色 '{voice}' 生成语音...")
    
    generator = pipeline(
        text, 
        voice=voice,
        speed=1.0  # 语速，范围0.5-1.5
    )
    
    # 4️⃣ 保存音频文件
    output_file = "kokoro_output.wav"
    for i, result in enumerate(generator):
        # 提取音频数据（形状: [样本数]）
        audio_tensor = result.output.audio
        
        # 保存为wav文件，采样率24kHz
        sf.write(output_file, audio_tensor, 24000)
        print(f"✅ 音频已保存为: {output_file}")
        print(f"   - 音频时长: {len(audio_tensor)/24000:.2f} 秒")
        print(f"   - 文本内容: {result.graphemes[:50]}...")
        break  # 只需要第一段音频
    
if __name__ == "__main__":
    main()