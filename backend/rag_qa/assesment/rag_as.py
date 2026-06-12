'''
基于 RAGAS 实现模型评估，上下文相关性、上下文召回率、忠实度、答案相关性等指标。
- 上下文相关性：检索到的上下文是否都和问题相关。
- 上下文召回率：检索到的上下文中包含正确答案的比例。
- 忠实度：生成的答案是否忠实于检索到的上下文。
- 答案相关性：生成的答案是否与问题相关。
基于 QWEN2.5:7B 模型, mxbai-embed-large 嵌入模型 进行评估，评估数据来自于之前构建的 JSON 文件。
modelscope download --model Qwen/Qwen2.5-7B-Instruct --local_dir ./model/qwen2.5-7b-instruct
modelscope download --model mirror013/mxbai-embed-large-v1 --local_dir ./model/mxbai-embed-large
'''

# 导入 ragas 中的评估函数
from ragas import evaluate
# 导入评估指标
from ragas.metrics import (
    context_precision,     # 上下文相关性
    context_recall,        # 上下文召回率
    faithfulness,          # 忠实度
    answer_relevancy       # 答案相关性
)
# 导入 json 模块
import json
# 导入datasets库的Dataset类，用于构建RAGAS所需的数据格式
from datasets import Dataset
# 导入配置类
from base.config import conf
# 导入模型加载函数
from langchain_ollama import OllamaLLM,OllamaEmbeddings
# 导入 RAGAS 中的 LLM 包装器
from ragas.llms import LangchainLLMWrapper
# 导入 RAGAS 中的 Embeddings 包装器
from ragas.embeddings import LangchainEmbeddingsWrapper
# 导入 os 模块
import os


# 加载评估数据
with open(conf.rag_evaluate_data, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 构建 RAGAS 评估所需的数据格式
# 创建字典eval_data，将JSON数据转换为RAGAS评估所需的格式
'''RAGAS 要求 contexts 必须是列表的列表 [[ctx1], [ctx2]]，即使只有一个上下文'''
eval_data = {
    'question': [item['question'] for item in data],
    'answer': [item['answer'] for item in data],
    'retrieved_contexts': [item['context'] for item in data],
    'ground_truth': [item['ground_truth'] for item in data]
}

# 将字典转换为Dataset对象，供RAGAS评估使用
eval_dataset = Dataset.from_dict(eval_data)  # 将数据格式设置为PyTorch张量格式，方便后续处理

# 初始化LLM模型和词嵌入模型
llm_model = OllamaLLM(model="qwen2.5:7b")
embedding_model = OllamaEmbeddings(model="mxbai-embed-large:latest")

# 包装LLM模型和词嵌入模型，使其符合RAGAS评估的接口要求
llm_model = LangchainLLMWrapper(llm_model)
embedding_model = LangchainEmbeddingsWrapper(embedding_model)

# 导入 RAGAS 中的 RunConfig 类，用于配置评估运行参数
from ragas.run_config import RunConfig

# 执行评估函数
result = evaluate(
    # 传入转换好的数据集
    dataset=eval_dataset,
    # 传入LLM模型
    llm = llm_model,
    # 传入词嵌入模型
    embeddings=embedding_model,
    # 指定评估指标
    metrics=[
        context_precision,     # 上下文相关性
        context_recall,        # 上下文召回率
        faithfulness,          # 忠实度
        answer_relevancy       # 答案相关性
    ],
    run_config = RunConfig(     # 配置评估运行参数
        max_workers=1           # 关键：只开1个worker
    )
)

if result:
    # 转换为 Pandas DataFrame 方便查看和分析
    df = result.to_pandas()
    
    # 打印统计信息
    print("\n--- 📈 评估统计概览 ---")
    # 选择数值列进行统计
    numeric_cols = df.select_dtypes(include=['number']).columns
    print(df[numeric_cols].describe())
    
    # 保存结果到 CSV
    output_file = os.path.join(os.path.dirname(conf.rag_evaluate_data), "ragas_evaluation_results.csv")
    df.to_csv(output_file, index=False)
    print(f"\n✅ 详细结果已保存至: {output_file}")