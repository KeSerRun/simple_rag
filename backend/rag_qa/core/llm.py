# 导入日志记录模块
from base.logger import logger
# 导入 transformers 库中的模型和分词器类
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
# 导入多线程模块
import threading
# 导入 PyTorch 库
import torch
'''
大语言模型模块，负责处理复杂的语言生成任务，如生成假设问题、生成最终答案等
这里使用 Qwen2.5-1.5B 模型进行语言生成，提示模板设计为引导模型根据用户输入生成相关的文本内容
需要下载模型：
    modelscope download --model Qwen/Qwen2.5-1.5B-Instruct --local_dir ./model/qwen-2.5-1.5b-instruct
'''

# 定义大语言模型
class LLMModel:
    def __init__(self,model_path: str,device:str=None):
        # 定义模型名称
        self.model_path = model_path
        # 指定设备
        self.device = device 
        # 初始化模型
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype="auto",
            device_map="cpu" if device is None else device
        )
        # 如果指定了设备，将模型移动到指定设备上
        if device is not None:
            self.model.to(device)
        # 设置为评估模式
        self.model.eval()
        # 初始化分词器
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        # 初始化Streamer，用于流式生成文本
        self.streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)

    def _call_llm_model(self, prompt, max_new_tokens=512, temperature=0.8, history:list=None, stream=False):
        try:
            # 如果提供了历史记录，将历史记录与当前提示词合并，形成新的输入文本
            message = [{"role": "system", "content": "你是一个有用的助手，帮助用户解答问题。"},
                        *(history or []),  # 如果有历史对话，则将其包含在提示中
                        {"role": "user", "content": prompt}]
            # 使用分词器处理输入文本
            text = self.tokenizer.apply_chat_template(
                message,
                tokenize=False,
                add_generation_prompt=True
            )
            # 将处理后的文本转换为模型输入格式
            model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
            # 如果不启用流式输出
            if not stream:
                # 禁用梯度计算，使用模型生成响应
                with torch.no_grad():
                    # 使用模型生成响应
                    generated_ids = self.model.generate(
                        **model_inputs,     # 输入模型输入
                        max_new_tokens=max_new_tokens,   # 生成响应的最大长度
                        temperature=temperature,     # 生成的随机程度，值越小越确定，值越大越随机
                        streamer=None    # 不启用流式输出
                    )
                # 从生成的 ID 中提取响应文本
                generated_ids = [
                    output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
                ]
                # 解码生成的 ID，得到响应文本
                response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
                # 返回生成的响应文本
                return response
            else:
                # 否则返回一个生成器，逐步生成响应文本
                return self.generater(model_inputs, max_new_tokens, temperature)
        except Exception as e:
            # 记录错误日志
            logger.error(f"LLM 模型调用失败: {e}")
            # 返回错误提示
            return "抱歉，模型处理请求时发生了错误。"

    def generater(self,model_inputs, max_new_tokens, temperature):
        # 定义运行的函数
        def run(model_inputs, max_new_tokens, temperature, streamer):
            with torch.no_grad():
                self.model.generate(
                    **model_inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    streamer=self.streamer
                )
        # 异步使用模型生成响应，启用流式输出
        threading.Thread(
            target=run, 
            args=(model_inputs,      # 输入模型输入
                  max_new_tokens,    # 生成响应的最大长度
                  temperature,       # 生成的随机程度，值越小越确定，值越大越随机
                  self.streamer)     # 启用流式输出
        ).start()
        # 从流式输出中获取生成的响应文本
        for new_text in self.streamer:
            yield new_text