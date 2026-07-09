# ================================================================
# 文件: eval_rag.py
# 功能: RAG 检索质量 LLM 评估 —— 基于实际数据的精确率测试
# 说明: 本脚本使用大语言模型作为裁判，评估 RAG 系统的检索质量。
#       核心指标是精确率(Precision@K)，即检索到的结果中有多少是真正相关的。
# ================================================================

# ===== 模块文档字符串（Docstring） =====
"""RAG 检索质量 LLM 评估：基于实际数据的精确率测试。  # 这个字符串是文件的文档说明，描述了本模块的用途

精确率:                                            # 精确率指标的说明标题
  1. 准备 20 个用户查询（从 eval_queries.json 加载）   # 第一步：从JSON文件中读取测试用的用户问题
  2. 对每个查询调用 _exec_search_kb 工具执行检索       # 第二步：对每个问题调用知识库搜索工具来检索文档
  3. LLM 对每条检索结果打分 (0-4)                     # 第三步：让大语言模型对每个检索结果进行相关度评分
  4. 计算平均精确率 Precision@K                       # 第四步：汇总所有评分，计算最终的平均精确率
"""

# ===== 导入标准库模块 =====
import json    # 导入 json 模块，用于读取和写入 JSON 格式的数据文件（如 eval_queries.json）
import os      # 导入 os 模块，用于处理文件和路径相关的操作（如获取文件所在目录）

# ===== 导入类型注解相关 =====
from typing import List    # 从 typing 模块导入 List 类型，用于类型注解，标明函数的参数或返回值是列表类型

# ===== 导入数据类相关 =====
from dataclasses import dataclass    # 从 dataclasses 模块导入 dataclass 装饰器，用于快速创建只存数据的类

# ===== 导入项目内部模块 =====
from base.config import conf           # 从 base.config 导入配置对象 conf，里面包含了模型名称、API密钥等全局配置
from base.logger import logger         # 从 base.logger 导入日志记录器 logger，用于在控制台输出带级别的日志信息
from base.llm_client import OpenAIClient    # 从 rag.llm_client 导入 OpenAI 客户端类，用于调用大语言模型 API
from agent.tools.registry import ToolContext     # 从 agent.tools.registry 导入 ToolContext 类
from agent.tools import registry           # 从 agent.tools 导入 registry 对象，它负责管理和调度所有可用的工具（如知识库搜索）

# ─── 加载测试查询 ─────────────────────────────────
# 这个区域负责从 JSON 文件中读取测试用的用户查询列表

# 定义一个私有常量，存放测试查询文件的完整路径
# os.path.dirname(__file__) 获取当前 Python 文件所在的目录路径
# os.path.join(...) 将目录路径和文件名拼接成完整的文件路径
_QUERIES_FILE = os.path.join(os.path.dirname(__file__), "eval_queries.json")


# 定义一个函数，用于从外部 JSON 文件加载测试查询列表
# 参数 path: JSON 文件的路径，默认使用上面的 _QUERIES_FILE 常量
# 返回值: 一个字符串列表，每个字符串是一个用户查询
def load_test_queries(path: str = _QUERIES_FILE) -> List[str]:
    """从外部 JSON 文件加载测试查询列表。"""    # 函数的文档字符串，说明这个函数的作用
    if not os.path.exists(path):               # 判断指定的文件路径是否存在
        logger.warning(f"测试查询文件不存在: {path}，使用内置默认查询")
        return _default_queries()              # 返回内置的默认查询列表作为备选方案
    with open(path, "r", encoding="utf-8") as f:  # 以只读模式打开 JSON 文件，指定编码为 UTF-8 以支持中文
        queries = json.load(f)                 # 使用 json.load 将文件内容解析为 Python 对象（期望是一个列表）
    if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):  # 检查解析结果是否是一个列表，且列表中每个元素都是字符串
        logger.warning(f"测试查询文件格式异常，使用内置默认查询")
        return _default_queries()              # 返回内置的默认查询列表作为备选方案
    logger.info(f"已加载 {len(queries)} 个测试查询: {path}")
    return queries                             # 返回从文件中加载的查询列表


# 定义一个函数，返回测试查询文件的路径
# 返回值: 字符串，表示测试查询文件的绝对路径
def get_queries_file_path() -> str:
    """返回测试查询文件路径。"""    # 函数的文档字符串，说明这个函数的作用
    return _QUERIES_FILE           # 直接返回私有常量中保存的文件路径


# 定义一个函数，将测试查询列表保存到外部的 JSON 文件中
# 参数 queries: 要保存的查询字符串列表
# 参数 path: 保存的目标文件路径，默认使用 _QUERIES_FILE 常量
# 返回值: 无（None）
def save_test_queries(queries: List[str], path: str = _QUERIES_FILE) -> None:
    """保存测试查询列表到外部 JSON 文件。"""    # 函数的文档字符串，说明这个函数的作用
    with open(path, "w", encoding="utf-8") as f:  # 以写入模式打开文件，指定 UTF-8 编码以支持中文字符
        json.dump(queries, f, ensure_ascii=False, indent=2)  # 将查询列表序列化为 JSON 格式写入文件，ensure_ascii=False 保证中文不被转义，indent=2 让输出有缩进便于阅读
    logger.info(f"已保存 {len(queries)} 个测试查询: {path}")


# 定义一个有下划线前缀的"私有"函数，返回一组内置的默认测试查询
# 返回值: 字符串列表，每个字符串是一个金融/量化投资领域的典型查询
def _default_queries() -> List[str]:
    return [                # 返回一个硬编码的查询列表，涵盖择时、选股、基金、风控等量化投资主题
        "沪深300择时策略",              # 查询：关于沪深300指数的择时交易策略
        "TD序列 GFTD 择时模型",         # 查询：关于TD序列/GFTD这种技术分析择时模型
        "基金定投策略 智能定投",         # 查询：关于基金定投和智能定投的投资策略
        "保本基金 CPPI TIPP 策略",      # 查询：关于保本基金采用的CPPI和TIPP策略
        "行业轮动 景气度投资",           # 查询：关于行业轮动和基于景气度的投资方法
        "分析师推荐 港股 投资策略",      # 查询：关于分析师推荐的港股投资策略
        "单向波动差值择时模型",          # 查询：关于单向波动差值这种择时模型
        "布林带择时定投",               # 查询：关于使用布林带指标进行择时定投
        "量化择时 趋势跟踪",            # 查询：关于量化择时和趋势跟踪策略
        "风险平价 资产配置",            # 查询：关于风险平价模型的资产配置方法
        "事件驱动策略 调研",            # 查询：关于事件驱动型投资策略的调研
        "财报分析 营收增速",            # 查询：关于财务报表分析和营收增速的分析
        "机器学习 股价预测",            # 查询：关于用机器学习方法预测股价
        "ETF 行业配置 轮动",            # 查询：关于ETF的行业配置和轮动策略
        "市场微观结构 高频数据",        # 查询：关于市场微观结构和高频数据的分析
        "违约风险 信用评估",            # 查询：关于违约风险和信用评估的方法
        "动量因子 反转效应",            # 查询：关于动量因子和反转效应的量化因子
        "波动率预测 风险管理",          # 查询：关于波动率预测和风险管理的方法
        "止损策略 回撤控制",            # 查询：关于止损策略和最大回撤控制
        "多因子模型 选股",              # 查询：关于多因子模型的选股策略
    ]


# ===== 定义评估结果的数据类 =====

# 使用 @dataclass 装饰器定义一个数据类，自动生成 __init__ 等方法
# 这个类用来存储一次查询的评估结果
@dataclass
class EvalResult:
    query: str               # 用户查询的原始文本，比如"沪深300择时策略"
    retrieved_count: int     # 检索到的文档片段总数，即一共召回了多少个片段
    relevant_count: int      # 其中与查询相关的片段数量（评分 >= 3 的片段数）
    avg_score: float         # 所有检索片段的平均得分，反映整体检索质量
    scores: List[int]        # 每个检索片段的具体评分列表，比如 [4, 3, 0, 2, 4]

    # 定义一个属性（property），计算这次查询的精确率
    # 精确率 = 相关文档数 / 总检索文档数
    @property
    def precision(self) -> float:
        return self.relevant_count / self.retrieved_count if self.retrieved_count > 0 else 0.0  # 如果检索数为0则返回0.0，避免除以零错误


# ─── LLM 评判器 ───────────────────────────────────
# 这个区域定义了一个用大语言模型来做评分裁判的功能

# 定义系统级提示词（System Prompt），用来告诉大语言模型它的角色和评分标准
# 这是一个常量字符串，不会在程序运行中被修改
_EVAL_SYSTEM_PROMPT = (
    "你是一个检索质量评估专家。给定用户查询和检索到的文档片段，"   # 告诉 LLM 它的身份是评估专家
    "判断该片段是否与查询相关。\n\n"                                # 说明它的任务：判断文档片段和查询的相关性
    "评分标准：\n"                                                  # 以下是评分标准的说明
    "0 - 完全不相关\n"                                              # 0分：文档内容和查询毫无关系
    "1 - 主题相关但内容不直接回答查询\n"                            # 1分：主题沾边，但没有直接回答问题
    "2 - 部分相关，包含一些相关信息\n"                              # 2分：部分相关，包含了一些有用的信息
    "3 - 比较相关，包含关键信息\n"                                 # 3分：比较相关，包含了关键信息
    "4 - 高度相关，直接回答查询\n\n"                               # 4分：高度相关，直接回答了用户的问题
    "只输出一个数字（0-4），不要包含其他文字。"                     # 要求 LLM 只输出数字，不要输出其他内容，方便程序解析
)


# 定义一个函数，让大语言模型给一个查询和文档片段的相关性打分
# 参数 client: OpenAIClient 实例，用来调用 LLM API
# 参数 query: 用户查询的字符串
# 参数 text: 检索到的文档片段文本
# 返回值: 整数，0-4 之间的评分
def llm_score(client: OpenAIClient, query: str, text: str) -> int:
    """LLM 判断文本与查询的相关性，返回 0-4。"""    # 函数的文档字符串
    try:                                            # 开始 try 块，用于捕获可能的异常（如网络问题、解析错误等）
        resp = client.chat(                         # 调用 OpenAI 客户端的 chat 方法，向大语言模型发送请求
            messages=[                              # 消息列表，包含 system 和 user 两条消息
                {"role": "system", "content": _EVAL_SYSTEM_PROMPT},  # system 消息：设定 LLM 的角色和评分规则
                {"role": "user", "content": f"用户查询：{query}\n\n文档片段：{text[:500]}"},  # user 消息：传入查询和文档片段（只取前500字符避免超长）
            ],
            model=conf.chat_model,                  # 使用配置文件中指定的聊天模型名称
            stream=False,                           # 关闭流式输出，一次性返回完整结果
            temperature=0.1,                        # 温度设为 0.1，让输出更确定、更稳定，减少随机性
            max_tokens=256,                         # 最大生成 256 个 token，足够输出一个数字
        )
        score = int(resp.strip())                   # 将 LLM 返回的文本去除首尾空格后转为整数
        return max(0, min(4, score))                # 确保评分在 0-4 范围内，防止 LLM 返回超出范围的值
    except (ValueError, TypeError):                 # 捕获转换整数时可能出现的异常（比如 LLM 返回了非数字内容）
        import re                                   # 在异常处理中导入正则表达式模块，用于从文本中提取数字
        m = re.search(r"[0-4]", resp or "")         # 使用正则表达式在 LLM 返回的文本中查找 0-4 之间的数字
        if m:                                       # 如果找到了匹配的数字
            return int(m.group())                   # 返回找到的第一个数字（转换成整数）
        logger.warning(f"LLM 评分失败 query={query!r} resp={resp!r}")
        return 0                                    # 实在无法解析时返回 0 分（完全不相关）作为默认值


# ─── 精确率测试 ───────────────────────────────────
# 这个区域是核心测试逻辑：遍历所有查询，调用知识库搜索，然后用 LLM 评分

# 定义精确率测试的主函数
# 参数 judge_client: 作为裁判的大语言模型客户端
# 参数 queries: 要测试的查询列表，如果不传则自动从文件加载
# 返回值: EvalResult 对象的列表，每个对象包含一个查询的详细评估结果
def test_precision(judge_client: OpenAIClient, queries: List[str] = None) -> List[EvalResult]:
    """精确率：调用 _exec_search_kb，LLM 评判结果质量。"""    # 函数的文档字符串
    from api.deps import system    # 在函数内部导入 system 对象（避免循环导入），它包含了向量库、数据存储等全局组件

    # 如果传入了 queries 参数则使用它，否则从默认的 JSON 文件中加载测试查询
    test_queries = queries if queries is not None else load_test_queries()

    # 创建一个 ToolContext 对象，封装工具执行所需的上下文环境
    ctx = ToolContext(
        vector_store=system.vector_store,   # 传入向量数据库实例，用于存储和检索文档的向量表示
        partition=None,                     # 分区参数设为 None，表示不限制检索范围（检索全部数据）
        data_store=system.data_store,       # 传入数据存储实例，用于存取原始文档数据
    )

    results = []                            # 初始化一个空列表，用来存储每个查询的评估结果
    for query in test_queries:              # 遍历每一个测试查询
        # 通过工具注册表分发（dispatch）调用知识库搜索工具
        # 参数1: 工具名称 "search_knowledge_base"（对应 _exec_search_kb）
        # 参数2: 将查询参数转为 JSON 字符串传入，search_system=True 表示搜索系统知识库
        # 参数3: ctx=ctx 传入上下文环境
        raw = registry.dispatch(
            "search_knowledge_base",
            json.dumps({"queries": [query], "search_system": True}),
            ctx=ctx,
        )

        # 解析返回的片段（格式化文本：每个片段以 【片段 N 开头）
        import re                      # 导入正则表达式模块，用于从返回文本中提取各个文档片段
        chunks = re.findall(r"【片段 \d+.*?。", raw, re.DOTALL)  # 使用正则查找所有以"【片段 N"开头、以句号结尾的文本块
        if not chunks and raw.strip(): # 如果正则没找到任何片段，但返回文本不为空
            chunks = [raw]             # 将整个返回文本当作一个片段处理

        scores = []                    # 初始化评分列表，用来存储这个查询中每个片段的 LLM 评分
        for text in chunks:            # 遍历每一个检索到的文档片段
            score = llm_score(judge_client, query, text[:500])  # 让 LLM 裁判给这个片段打分（只取前500字符）
            scores.append(score)       # 将评分添加到列表中

        # 计算"相关"的文档数量：评分 >= 3 的视为相关
        relevant = sum(1 for s in scores if s >= 3)   # 使用生成器表达式 + sum 统计评分 >= 3 的文档数量
        # 计算所有片段的平均分，如果列表为空则默认 0.0
        avg = sum(scores) / len(scores) if scores else 0.0

        # 创建 EvalResult 对象，封装本次查询的所有评估数据
        results.append(EvalResult(
            query=query,               # 记录当前查询的文本
            retrieved_count=len(scores),  # 总共检索到的文档片段数量
            relevant_count=relevant,      # 其中相关的文档片段数量
            avg_score=avg,                # 所有片段的平均评分
            scores=scores,                # 每个片段的具体评分列表
        ))

        # 记录日志：输出本次查询的精确率结果，方便实时观察
        logger.debug(f"[精确率] {query}: {relevant}/{len(scores)} 相关, 平均分 {avg:.2f}")

    return results    # 返回所有查询的评估结果列表


# ─── 报告输出 ─────────────────────────────────────
# 这个区域负责将评估结果以美观的格式打印到控制台

# 定义一个函数，用于打印精确率评估的报告
# 参数 results: EvalResult 对象的列表，即 test_precision 函数的返回值
def print_precision_report(results: List[EvalResult]):
    print(f"\n{'='*70}")                                    # 打印一行分隔线（70个等号）
    print(f"  精确率评估报告 (基于 _exec_search_kb)")       # 打印报告标题
    print(f"{'='*70}\n")                                    # 再打印一行分隔线，然后换行
    total_p = 0.0                                           # 初始化总精确率累加器，用于计算平均精确率
    for r in results:                                       # 遍历每个查询的评估结果
        # 打印每个查询的详细信息：查询内容（截取前20字符）、评分列表、相关数/总数、精确率、平均分
        print(f"  [{r.query[:20]:20s}] 评分={r.scores}  相关={r.relevant_count}/{r.retrieved_count}  "
              f"Prec@{r.retrieved_count}={r.precision:.1%}  均分={r.avg_score:.2f}")
        total_p += r.precision                              # 累加每个查询的精确率，用于后续计算平均值
    n = len(results)                                        # 获取查询的总数量
    print(f"\n{'='*70}")                                    # 打印一行分隔线
    print(f"  平均精确率 Precision@{results[0].retrieved_count}: {total_p/n:.1%}")  # 打印所有查询的平均精确率
    print(f"{'='*70}")                                      # 打印一行分隔线收尾


# ─── 主入口 ───────────────────────────────────────
# 这个区域是程序的入口点：当直接运行这个 Python 文件时执行

# 判断当前模块是否作为主程序运行（而不是被其他模块导入）
if __name__ == "__main__":
    # 打印程序的标题和说明信息
    print("=" * 70)                                                 # 打印分隔线
    print("  RAG 检索质量 LLM 评估（精确率）")                       # 打印主标题
    print("  基于实际向量库数据，调用 _exec_search_kb")               # 打印副标题，说明评估方式
    print("=" * 70)                                                 # 打印分隔线

    # 创建 OpenAI 客户端实例，用于后续作为 LLM 裁判
    # api_key 从配置中读取 OpenAI 的 API 密钥
    # base_url 从配置中读取 OpenAI 兼容的 API 地址（可以是代理或第三方中转地址）
    judge_client = OpenAIClient(api_key=conf.openai_api_key, base_url=conf.openai_base_url)

    # 调用 test_precision 函数执行精确率测试，传入 LLM 裁判客户端
    # 返回所有查询的评估结果列表
    precision_results = test_precision(judge_client)

    # 调用 print_precision_report 函数，将评估结果以报告形式打印到控制台
    print_precision_report(precision_results)
