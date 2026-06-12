#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ollama 数据扩写 - 核心接口
功能：text -> [text1, text2, ... text10]
"""

import re
import time
from typing import List
import requests
from base.config import conf

class OllamaAugmenter:
    def __init__(self, model_name: str = "qwen2.5", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.api_url = f"{base_url.rstrip('/')}/api/generate"
    
    def augment(self, text: str, n: int = 10, temperature: float = 0.8) -> List[str]:
        """
        将单条文本扩写为 n 条语义相似但表达不同的变体
        
        Args:
            text: 原始文本
            n: 生成数量，默认10
            temperature: 采样温度，越高多样性越强
        
        Returns:
            包含原始文本的 n 条结果列表（原始文本在首位）
        """
        
        prompt = f"""基于以下文本，生成 {n} 条语义相同但表达方式不同的变体。保持核心信息不变，使用不同的词汇、句式或风格。

原文：{text}

直接输出结果，每条一行，前面加序号：
"""
        try:
            resp = requests.post(
                self.api_url,
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": 2048}
                },
                timeout=120
            )
            resp.raise_for_status()
            generated = resp.json().get("response", "")
            
            # 解析生成的变体
            variations = self._parse(generated, text)
            
            # 确保数量足够，不足时复制最后一个
            while len(variations) < n:
                variations.append(variations[-1] if variations else text)
            
            return variations[:n]
            
        except Exception as e:
            print(f"生成失败: {e}")
            return [text] * n
    
    def _parse(self, raw: str, original: str) -> List[str]:
        """解析模型输出，提取并去重"""
        results = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # 去除序号前缀
            cleaned = re.sub(r"^\d+[\.\)、\s]+", "", line).strip()
            if cleaned and cleaned != original and cleaned not in results:
                results.append(cleaned)
        
        # 原始文本放在首位
        return [original] + results


# ==================== 使用示例 ====================

""" if __name__ == "__main__":
    augmenter = OllamaAugmenter(model_name="qwen2.5:7b")
    
    text = "请介绍一下深度学习的基本概念。"
    result = augmenter.augment(text, n=10)
    
    for i, t in enumerate(result, 1):
        print(f"{i}. {t}") """


def augment_query_classifier_data(model_name="qwen2.5:7b"):
    augmenter = OllamaAugmenter(model_name=model_name)
    
    import json
    agument_list = []
    with open(conf.query_classifier_eval_data_file, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            text = data.get("query", "")
            label = data.get("label", "")
            print(f"原始文本: {text} (标签: {label})")
            variations = augmenter.augment(text, n=5)
            print(f"生成变体:\n {variations}")
            agument_list.extend([{"query": var, "label": label} for var in variations])

    with open(conf.query_classifier_train_data_file, 'w', encoding='utf-8') as f:
        for item in agument_list:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")