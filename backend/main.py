# ===== 导入系统模块 =====
# 导入配置类：从 base 包下的 config 模块中导入 conf 对象，用于读取全局配置（如存储后端类型、历史窗口大小等）
from base.config import conf
# 导入日志模块：logger 用于打印运行日志，log_qa 用于记录问答日志到文件
from base.logger import logger, log_qa
# 根据配置选择持久化存储的实现：配置文件中的 storage_backend 字段决定用 SQLite 还是 JSON 文件
if conf.storage_backend == 'sqlite':
    # 如果配置要求使用 SQLite，则从 storage 包导入 SQLiteStore，并将其命名为 DataStore（统一接口名）
    from storage import SQLiteStore as DataStore
    # 打印日志，告知用户当前存储后端是 SQLite
    logger.info("存储后端: SQLite")
else:
    # 否则（默认情况）使用 JSON 文件存储，从 storage 包导入 JSONFileStore 并命名为 DataStore
    from storage import JSONFileStore as DataStore
    # 打印日志，告知用户当前存储后端是 JSON 文件
    logger.info("存储后端: JSON 文件")
# 导入 RAG 问答系统类：从 agent 包中导入 RAGSystem，它是整个问答流程的核心引擎，负责向量检索 + LLM 调用
from agent import RAGSystem
# 导入 Optional 类型注解：用于标注函数参数或返回值可能是 None 的情况（类型提示用）
from typing import Optional
# 导入 uuid 模块：用于生成唯一的会话 ID（UUID 通用唯一识别码）
import uuid
# 导入 argparse 模块：用于解析命令行参数，构建 CLI 工具的命令和选项
import argparse
# 导入 os 模块：提供与操作系统交互的功能，比如检查文件路径是否存在、获取路径信息等
import os
# 导入 sys 模块：提供 Python 解释器相关的功能，比如退出程序 sys.exit()
import sys
# 导入 re 模块：提供正则表达式工具，用于文本关键词提取和模式匹配
import re


# ===== IntegratedSystem 类：集成系统核心类 =====
# 定义一个名为 IntegratedSystem 的类，它将数据存储和 RAG 问答能力封装在一起，对外提供统一的问答接口
class IntegratedSystem:
    # 构造方法：当创建 IntegratedSystem 实例时自动调用，初始化内部组件
    def __init__(self):
        # 创建数据存储实例：根据前面选择的 DataStore（SQLite 或 JSON 文件）来初始化数据存储对象
        self.data_store = DataStore()
        # 创建 RAG 问答系统实例：传入 data_store 参数，使问答系统可以读写会话历史等数据
        self.rag_qa = RAGSystem(data_store=self.data_store)
        # 获取向量存储对象：从 RAG 系统中取出 vector_store，用于直接操作文档的向量化存储（增删文档等）
        self.vector_store = self.rag_qa.vector_store
        # 初始化会话风格追踪字典：记录每个会话当前使用的回答风格（style），用于检测风格是否发生了切换
        self.session_last_style: dict[str, str] = {}
        # 初始化会话任务字典：记录每个会话的短期任务和长期任务列表（用于上下文感知和任务跟踪）
        self.session_tasks: dict[str, dict] = {}  # 结构示例：{session_id: {"short": [...], "long": [...]}}
        # 初始化会话轮次计数器：记录每个会话已经进行的问答轮数，用于任务时效判断和超期检测
        self.session_turn: dict[str, int] = {}

    # 定义 get_history 方法：读取指定会话的历史记录，并将其转换为 LLM（大语言模型）可用的消息格式
    def get_history(self, session_id):
        """读取会话历史并展开为 LLM 输入格式。

        history.json 中两种条目:
          - {type: 'qa', user, assistant}       → user / assistant 两条消息
          - {type: 'event', event_type, files}  → 单条 <operation：...> user 消息
        规则:
          - max_history_length: 硬截断窗口，超过时丢弃最早的 QA
          - max_history_chars: 字符数超限时压缩早期对话（保留最近 2 轮）
        """
        # 从数据存储中获取该会话的原始历史记录列表，如果没有则返回空列表
        raw = self.data_store.get_session_history(session_id) or []
        # 如果历史记录为空（没有内容），直接返回一个空的消息列表
        if not raw:
            return []
        # 初始化一个空列表，用于存放格式化后的消息（供后续 LLM 使用）
        messages = []

        # 1) 硬截断: 按轮次截取最近 N 条 QA
        # 从原始历史中筛选出类型不为 'event' 的 QA 条目（只保留真正的问题和回答）
        qa_entries = [h for h in raw if h.get('type') != 'event']
        # 如果 QA 条目数量超过了配置中设定的最大历史长度限制
        if len(qa_entries) > conf.max_history_length:
            # 计算需要丢弃的轮数：当前 QA 数量减去允许的最大长度
            discard = len(qa_entries) - conf.max_history_length
            # 获取需要丢弃的条目的 id（Python 对象的内存地址），用于在原始列表中识别并移除
            discard_ids = {id(h) for h in qa_entries[:discard]}
            # 重新构建原始历史列表：过滤掉那些 id 在 discard_ids 中的条目
            raw = [h for h in raw if id(h) not in discard_ids]
            # 打印日志，告知截断了多少轮对话
            logger.info(f"历史截断: 丢弃前 {discard} 轮, 保留最近 {conf.max_history_length} 轮")

        # 2) 字符数压缩: 超过上限时压缩早期对话
        # 再次从（可能截断后的）原始历史中筛选出非事件类型的 QA 条目
        qa_entries2 = [h for h in raw if h.get('type') != 'event']
        # 计算所有 QA 条目的总字符数：把每条的用户问题和 AI 回答的字符数加起来
        total_chars = sum(
            len(h.get('user', '') or '') + len(h.get('assistant', '') or '')
            for h in qa_entries2
        )
        # 如果总字符数超过了配置限制，并且 QA 条目数大于 2（至少有压缩空间）
        if total_chars > conf.max_history_chars and len(qa_entries2) > 2:
            # 设定保留最近几轮不压缩（这里设为保留最近 2 轮）
            keep = 2
            # 取前面需要压缩的条目（除了最近 keep 条之外的都是要压缩的）
            compressed_qa = qa_entries2[:-keep]
            # 获取被压缩条目的 id 集合，用于从原始列表中标识
            compressed_ids = {id(h) for h in compressed_qa}
            # 构建剩余不压缩的原始历史列表（只含没有被压缩的条目）
            remaining_raw = [h for h in raw if id(h) not in compressed_ids]

            # 归档：把被压缩的轮次存入归档存储中，供 LLM 通过 read_archive 工具回溯查看
            archive_id = self.data_store.insert_archive(
                session_id=session_id,  # 指定属于哪个会话
                summary="用户的问题：" + "；".join(  # 生成摘要：提取每条问题的前 60 个字符拼接起来
                    h.get('user', '')[:60] for h in compressed_qa if h.get('user')
                ),
                turns=[  # 将压缩的轮次按 {user, assistant, timestamp} 格式组织成列表
                    {
                        "user": h.get("user", ""),
                        "assistant": h.get("assistant", ""),
                        "timestamp": h.get("timestamp", ""),
                    }
                    for h in compressed_qa
                ],
            )
            # 生成一条摘要文本，告知 LLM 有历史被归档了，并给出归档编号和问题摘要
            summary_text = f"（历史摘要 #{archive_id}：用户之前的问题：" + "；".join(
                h.get('user', '')[:60] for h in compressed_qa if h.get('user')
            ) + "。如需查阅完整历史，请调用 read_archive 工具。）"

            # 如果摘要文本不为空，则将其作为一条 user 消息添加到消息列表中
            if summary_text:
                messages.append({'role': 'user', 'content': summary_text})

            # 遍历剩余的未被压缩的历史条目，将它们逐一追加到消息列表中
            for h in remaining_raw:
                self._append_history_item(messages, h)

            # 计算压缩后的消息总字符数（用于日志对比和数据验证）
            after_chars = sum(len(m.get('content', '') or '') for m in messages)
            # 打印压缩情况的详细日志：压缩了多少轮、多少字符、节省了多少字符、归档编号
            logger.info(
                f"历史压缩触发: "
                f"压缩前 {len(compressed_qa)} 轮/{total_chars} 字符, "
                f"压缩后 {after_chars} 字符, "
                f"节省 {total_chars - after_chars} 字符, "
                f"归档={archive_id}"
            )
        else:
            # 如果不需要压缩，则遍历所有原始历史条目，直接追加到消息列表中
            for h in raw:
                self._append_history_item(messages, h)

        # 返回最终格式化好的消息列表，供 LLM 使用
        return messages

    # 定义一个静态方法（不依赖实例，可直接通过类名调用）：用于将一条历史记录条目追加到消息列表中
    @staticmethod
    def _append_history_item(messages: list, h: dict):
        """将一条 history 条目追加到 messages。"""
        # 如果这条历史记录的类型是 'event'（事件类型，如上传、删除文件等操作事件）
        if h.get('type') == 'event':
            # 调用 _event_to_tag 方法将事件转换为特殊的标签文本（如 <operation：upload files: xxx>）
            tag = IntegratedSystem._event_to_tag(
                h.get('event_type', ''), h.get('files', [])
            )
            # 如果生成的标签不为空，则将其作为一条 user 消息添加到消息列表中
            if tag:
                messages.append({'role': 'user', 'content': tag})
        else:
            # 如果是普通的 QA 记录，则将用户的问题作为一条 user 消息添加到列表中
            messages.append({'role': 'user', 'content': h.get('user', '')})
            # 将 AI 的回答作为一条 assistant 消息添加到列表中（与 user 消息一一对应）
            messages.append({'role': 'assistant', 'content': h.get('assistant', '')})

    # 定义一个静态方法：将事件类型和文件列表转换为统一的标签文本格式，供 LLM 感知用户近期操作
    @staticmethod
    def _event_to_tag(event_type: str, files: list) -> str:
        """事件 → <operation：...> 文本, 供 LLM 感知用户最近操作"""
        # 如果事件类型是 'delete_all'（清空所有文件），返回对应的操作标签文本
        if event_type == 'delete_all':
            return "<operation：clear all uploaded files>"
        # 如果文件列表为空（没有文件信息），则返回空字符串
        if not files:
            return ""
        # 取文件列表的前 3 个文件名，用于生成标签
        head = files[:3]
        # 如果文件总数超过 3 个，则在标签末尾加一个 "等" 字表示还有更多
        suffix = "等" if len(files) > 3 else ""
        # 如果是上传事件，返回上传操作标签，列出被上传的文件名
        if event_type == 'upload':
            return f"<operation：upload files: {', '.join(head)}{suffix}>"
        # 如果是删除事件，返回删除操作标签，列出被删除的文件名
        if event_type == 'delete':
            return f"<operation：delete files: {', '.join(head)}{suffix}>"
        # 如果是风格切换事件，取出第一个元素作为新的风格名称（没有则用 "default"）
        if event_type == 'style_change':
            new_style = files[0] if files else 'default'
            return f"<operation：switch answer style to {new_style}>"
        # 如果事件类型不匹配以上任何一种，返回空字符串
        return ""

    # 定义一个私有方法：检测会话的回答风格是否发生了切换，并在历史中记录事件
    def _check_style_change(self, session_id: str, style: Optional[str]) -> None:
        """检测 style 切换，记录事件到历史。"""
        # 获取之前记录的该会话的最终风格
        prev = self.session_last_style.get(session_id)
        # 如果之前有记录，并且与当前传进来的风格不同（发生了切换）
        if prev is not None and prev != style:
            # 在数据存储中插入一条 style_change 事件（记录到历史中）
            self.data_store.insert_session_event(session_id, 'style_change', [str(style or 'default')])
            # 打印日志，记录风格从旧值切换到新值
            logger.info(f"style 切换: {prev} → {style or 'default'}")
        # 更新该会话的最近风格记录为当前风格（如果没有传 style 则默认为 'default'）
        self.session_last_style[session_id] = style or 'default'

    # ─── 会话任务追踪 ───────────────────────────────

    # 类常量：任务的最大过期轮数——如果某个任务超过 N 轮未被引用，则标记为 superseded（已过期）
    TASK_MAX_STALE_TURNS = 5
    # 类常量：短期任务的最大活跃数量（同时最多允许 N 个短期任务处于 active 状态）
    TASK_MAX_SHORT = 3
    # 类常量：短期任务总历史上限（包括已关闭的，最多保留 N 个）
    TASK_MAX_SHORT_HIST = 20
    # 类常量：长期任务上限（最多保留 N 个长期任务）
    TASK_MAX_LONG = 10
    # 类常量：话题关联判定的关键词重叠比例阈值——超过此比例认为两个任务属于同一话题
    TASK_OVERLAP_RATIO = 0.2

    # 定义一个静态方法：从给定文本中提取关键词，用于话题关联判定
    @staticmethod
    def _task_keywords(text: str) -> set:
        """提取文本中的关键词用于话题关联判定。"""
        # 使用正则表达式查找所有中英文单词/字符（包括中文汉字、英文字母和数字），返回去重后的集合
        return set(re.findall(r'[\w一-鿿]+', text.lower()))

    # 定义一个静态方法：判断一个新问题与某个任务描述是否属于同一话题
    @staticmethod
    def _is_related_to(q_words: set, task_desc: str) -> bool:
        """新问题与任务描述是否属于同一话题。"""
        # 提取任务描述中的关键词（同样使用 _task_keywords 静态方法）
        t_words = IntegratedSystem._task_keywords(task_desc)
        # 如果问题关键词集合或任务关键词集合为空，则认为是相关的（无法判断就归为相关）
        if not q_words or not t_words:
            return True
        # 计算问题关键词和任务关键词的交集（两个集合相同的部分）
        overlap = q_words & t_words
        # 如果交集大小除以任务关键词数量 >= 阈值，则判定为同一话题返回 True，否则返回 False
        return len(overlap) / max(len(t_words), 1) >= IntegratedSystem.TASK_OVERLAP_RATIO

    # 定义一个私有方法：从内存中读取某个会话的状态为 active 的短期任务和长期任务描述
    def _load_session_tasks(self, session_id: str) -> tuple[list[str], list[str]]:
        """读取会话中状态为 active 的短期/长期任务描述。"""
        tasks = self.session_tasks.get(session_id)
        if tasks is None:
            # 内存未命中，尝试从持久化存储恢复
            tasks = self.data_store.get_session_tasks(session_id)
            self.session_tasks[session_id] = tasks
        short = [t["desc"] for t in tasks.get("short", []) if t.get("status") == "active"]
        long_ = [t["desc"] for t in tasks.get("long", []) if t.get("status") == "active"]
        return short, long_

    def _save_session_tasks(self, session_id: str, short: list[dict], long_: list[dict]):
        """保存会话任务列表。"""
        tasks = {"short": short, "long": long_}
        self.session_tasks[session_id] = tasks
        self.data_store.save_session_tasks(session_id, tasks)

    # 定义一个私有方法：从用户问题中提取短期任务的描述文字
    def _extract_task_from_query(self, question: str, wf_name: str = None) -> str:
        """从用户问题中提取短期任务描述。"""
        # 如果传入了工作流名称（wf_name），则使用工作流名称对应的中文显示名
        if wf_name:
            # 定义一个工作流 ID 到中文显示名的映射字典
            wf_display = {"USstocks": "美股分析"}
            # 如果映射中有对应的显示名则返回，否则返回原始工作流名称
            return wf_display.get(wf_name, wf_name)
        # 如果没有工作流名称，则对问题进行清洗：去掉首尾空格和常见的句尾标点
        q = question.strip().rstrip("？?。.!！")
        # 截取前 40 个字符作为任务描述，如果超过 40 个字符则加省略号
        return q[:40] + ("…" if len(q) > 40 else "")

    # 定义一个私有方法：获取并递增会话的轮次计数器
    def _get_turn(self, session_id: str) -> int:
        """获取并递增会话轮次。"""
        # 如果该会话还没有轮次记录，则初始化为 0（setdefault 方法：有则返回，无则设默认值）
        self.session_turn.setdefault(session_id, 0)
        # 将轮次计数器加 1（表示这一轮问答开始了）
        self.session_turn[session_id] += 1
        # 返回递增后的轮次数
        return self.session_turn[session_id]

    # 定义一个私有方法：更新会话的任务状态——检测任务是否完成/切换，管理任务的生命周期
    def _update_tasks(self, session_id: str, question: str, wf_name: str = None):
        """更新会话任务：检测完成/切换，管理状态生命周期。"""
        # 获取当前轮次数（调用 _get_turn 自动递增）
        turn = self._get_turn(session_id)
        # 从 session_tasks 中获取该会话的任务数据，如果不存在则用空字典作为默认值
        tasks = self.session_tasks.get(session_id, {"short": [], "long": []})
        # 取出短期任务列表（原始数据格式，每个元素是一个包含 desc、status、turn 等字段的字典）
        raw_short: list[dict] = tasks.get("short", [])
        # 取出长期任务列表（同样每个元素是一个多字段字典）
        raw_long: list[dict] = tasks.get("long", [])
        # 通过 _extract_task_from_query 方法从当前问题中提取短期任务描述文本
        current_desc = self._extract_task_from_query(question, wf_name)
        # 提取当前问题中的关键词集合，用于后续的话题关联判定
        q_words = self._task_keywords(question)

        # 定义一个内部嵌套函数：判断某个任务是否与当前问题属于同一话题（仍然活跃相关）
        def _task_active(t: dict) -> bool:
            """判定任务与新问题是否同属一个话题（关键词重叠 或 同 workflow）。"""
            # 如果任务状态不是 active（比如已经 superseded），则不认为活跃
            if t["status"] != "active":
                return False
            # 如果传入了工作流名称，且任务的工作流字段与之相同，则认为它们相关
            if wf_name and t.get("workflow") == wf_name:
                return True
            # 如果通过关键词重叠判定发现是同一话题，也认为相关
            if self._is_related_to(q_words, t["desc"]):
                return True
            # 如果以上条件都不满足，则判定为不相关
            return False

        # ── 1. 关闭已无关的旧任务 ────────────────────
        # 遍历所有短期任务，检查哪些不再与当前话题相关
        for t in raw_short:
            # 如果任务状态不是 active，则跳过不做处理
            if t["status"] != "active":
                continue
            # 如果该任务与当前问题相关（调用内部函数 _task_active 判断）
            if _task_active(t):
                # 仍然相关：刷新该任务的最后活跃轮次为当前轮次
                t["last_active_turn"] = turn
            else:
                # 不再相关：可能是话题切换了，或者已经超过过期轮数了
                # 如果当前轮次减去最后活跃轮次超过了最大过期轮数，说明是因为超期
                if turn - t.get("last_active_turn", t["turn"]) > self.TASK_MAX_STALE_TURNS:
                    # 打印日志，说明该任务因为超过 N 轮未引用而被标记过期
                    logger.info(f"任务超期: '{t['desc']}' ({self.TASK_MAX_STALE_TURNS}轮未引用)")
                else:
                    # 否则是因为话题被切换了
                    logger.info(f"任务完成: '{t['desc']}' (话题切换)")
                # 将任务状态改为 "superseded"（已过期/已被取代）
                t["status"] = "superseded"

        # ── 2. 更新短期任务 ──────────────────────────
        # 在短期任务中查找与当前任务描述相同且状态为 active 的任务（即已有的未完成任务）
        existing = [t for t in raw_short if t["desc"] == current_desc and t["status"] == "active"]
        # 取出所有描述不同的任务（用于后续排序和保留）
        others = [t for t in raw_short if t["desc"] != current_desc]

        if existing:
            # 如果已经存在相同描述的任务，则更新其最后活跃轮次
            existing[0]["last_active_turn"] = turn
            # 当前活跃任务列表就是这个已存在的任务
            active_tasks = existing
        else:
            # 如果不存在，则创建一个新的任务字典
            new_task = {
                "desc": current_desc,       # 任务描述（从问题中提取）
                "status": "active",          # 初始状态为活跃
                "turn": turn,               # 创建时的轮次
                "last_active_turn": turn,    # 最后活跃轮次
                "workflow": wf_name,         # 关联的工作流名称（如果有）
            }
            # 当前活跃任务列表就是这个新创建的任务
            active_tasks = [new_task]

        # 组装新的短期任务列表：把当前活跃任务和其他活跃任务放在前面（不超过上限），已关闭的放在后面
        active_part = (active_tasks + [t for t in others if t["status"] == "active"])[:self.TASK_MAX_SHORT]
        # 提取出所有非 active 状态的任务（已关闭的历史任务）
        inactive_part = [t for t in raw_short if t["status"] != "active"]
        # 合并活跃任务和非活跃任务，并限制总历史上限（最多保留 TASK_MAX_SHORT_HIST 个）
        new_short = (active_part + inactive_part)[:self.TASK_MAX_SHORT_HIST]

        # ── 3. 长期任务：同一 desc 再次出现时提升 ────
        # 获取当前长期任务中所有已有描述，构建一个集合便于快速判断
        long_descs = {t["desc"] for t in raw_long}
        # 如果当前任务描述不在长期任务中（说明之前还没被提升为长期任务）
        if current_desc not in long_descs:
            # 检查这个描述是否在短期任务历史中出现过（包括当前 raw_short 和 session_tasks 中存储的历史）
            hist_descs = {t["desc"] for t in raw_short} | {
                t["desc"] for t in self.session_tasks.get(session_id, {}).get("short", [])
            }
            # 如果当前任务描述在历史中存在过（说明用户又回到了之前的话题），则提升为长期任务
            if current_desc in hist_descs:
                # 在长期任务列表末尾追加一条新的长期任务记录
                raw_long.append({
                    "desc": current_desc,    # 任务描述
                    "status": "active",      # 初始状态为活跃
                    "turn": turn,           # 创建轮次
                    "last_active_turn": turn, # 最后活跃轮次
                    "workflow": wf_name,     # 关联的工作流
                })
                # 打印日志，记录某个任务被提升为长期任务
                logger.info(f"提升为长期任务: '{current_desc}'")

        # 长期任务也做超期检测（避免长期任务无限堆积）
        for t in raw_long:
            # 如果任务状态不是 active，则跳过
            if t["status"] != "active":
                continue
            # 如果当前轮次减去最后活跃轮次超过了过期阈值（短期阈值的 2 倍，因为长期任务寿命更长）
            if turn - t.get("last_active_turn", t["turn"]) > self.TASK_MAX_STALE_TURNS * 2:
                # 将该任务标记为 superseded（过期）
                t["status"] = "superseded"
                # 打印日志，记录长期任务过期
                logger.info(f"长期任务过期: '{t['desc']}'")

        # 保存更新后的任务列表：短期任务用 new_short，长期任务截取前 TASK_MAX_LONG 个
        self._save_session_tasks(session_id, new_short, raw_long[:self.TASK_MAX_LONG])

    # 定义 get_answer 方法（非流式）：处理用户的查询请求，返回完整的答案字符串
    def get_answer(self, session_id, question, partition: str = None, style: Optional[str] = None):
        """处理用户查询,返回答案"""
        # 检测回答风格是否发生切换，如果是则记录事件到历史中
        self._check_style_change(session_id, style)
        # 获取该会话的历史记录，格式化为 LLM 可用的消息列表
        history = self.get_history(session_id)

        # Workflow 路由检测：调用 rag_qa 的 workflow_router 来判断是否匹配某个特定工作流
        wf_name = self.rag_qa.workflow_router.match(question)
        # 加载当前会话的活跃短期任务和长期任务描述列表
        short_tasks, long_tasks = self._load_session_tasks(session_id)
        logger.debug(f"会话任务 session={session_id} 短期={short_tasks} 长期={long_tasks}")

        try:
            # 调用 rag_qa 的 generate_answer 方法获取回答（非流式模式，stream=False）
            answer = self.rag_qa.generate_answer(
                question,                 # 用户提出的问题
                stream=False,             # 禁止流式输出，等完整回答生成后再返回
                history=history,          # 传入格式化后的历史消息
                partition=partition,      # 分区参数（用于隔离不同用户的数据）
                style=style,              # 回答风格（如 default、professional 等）
                short_term_tasks=short_tasks,  # 活跃的短期任务列表
                long_term_tasks=long_tasks,    # 活跃的长期任务列表
            )
            # 打印成功日志，记录回答的字符长度
            logger.debug(f"回答成功 len={len(answer)}")
        except Exception as e:
            # 如果生成回答过程中发生了任何异常，捕获并记录错误日志
            logger.error(f"回答失败: {e}")
            # 生成一个友好的错误提示消息作为回答
            answer = f"抱歉，处理请求时发生了错误: {e}"
            # 即使出错了，也将这次问答记录到数据存储的历史中
            self.data_store.insert_session_history(session_id, question, answer)
            # 使用 log_qa 函数记录问答日志到文件
            log_qa(partition, session_id, question, answer)
            # 返回错误提示消息
            return answer

        # 正常回答生成后，更新会话的任务状态
        self._update_tasks(session_id, question, wf_name)
        # 将这次问答记录插入到数据存储的会话历史中
        self.data_store.insert_session_history(session_id, question, answer)
        # 使用 log_qa 函数记录问答日志到文件
        log_qa(partition, session_id, question, answer)
        # 返回最终的答案字符串
        return answer

    # 定义 answer_generator 方法（流式版）：使用生成器逐步返回答案片段，支持实时打字效果
    def answer_generator(self, session_id, question, partition: str = None, style: Optional[str] = None):
        """流式返回答案的生成器"""
        # 检测回答风格切换，记录事件
        self._check_style_change(session_id, style)
        # 获取会话历史，格式化为消息列表
        history = self.get_history(session_id)

        # 工作流路由检测
        wf_name = self.rag_qa.workflow_router.match(question)
        # 加载短期和长期任务
        short_tasks, long_tasks = self._load_session_tasks(session_id)
        logger.debug(f"会话任务 session={session_id} 短期={short_tasks} 长期={long_tasks}")

        # 调用 rag_qa 的流式生成方法，返回一个迭代器（逐个产生事件）
        answer_iter = self.rag_qa.generate_answer(
            question,                 # 用户问题
            stream=True,              # 开启流式模式（逐步返回 token 事件）
            history=history,          # 历史消息
            partition=partition,      # 分区
            style=style,              # 风格
            short_term_tasks=short_tasks,  # 短期任务
            long_term_tasks=long_tasks,    # 长期任务
        )
        # 初始化一个空列表，用于累加流式返回的所有 token 片段
        ans = []
        # 遍历生成器返回的事件流
        for event in answer_iter:
            # 如果事件的类型是 "token"（表示这是一个文本片段）
            if event.get("type") == "token":
                # 将 token 中的文本追加到 ans 列表中
                ans.append(event.get("text", ""))
            # 将事件原样 yield 出去（供调用者逐条处理，例如推送给前端进行流式展示）
            yield event
        # 将累积的所有 token 片段拼接成完整的回答字符串
        answer = ''.join(ans)

        # 更新会话任务
        self._update_tasks(session_id, question, wf_name)
        # 将会话历史存储到数据存储中
        self.data_store.insert_session_history(session_id, question, answer)
        # 记录问答日志
        log_qa(partition, session_id, question, answer)
        # 打印回答成功的日志
        logger.debug(f"回答成功 len={len(answer)}")

    # -- replaced by run_cli --

    # 定义 run_cli 方法：命令行的入口，根据不同的命令执行相应的操作
    def run_cli(self, args):
        """CLI entry point"""
        # 检查命令行参数中是否提供了 session 参数，如果有则使用该值作为会话 ID
        if hasattr(args, "session") and args.session:
            session_id = args.session
        else:
            # 如果没有提供 session 参数，则自动生成一个以 "cli-" 开头的 8 位 UUID 作为会话 ID
            session_id = "cli-" + str(uuid.uuid4())[:8]
        # 确定分区值：如果命令行指定了 partition 则用它，否则使用 session_id 作为分区标识
        partition = args.partition if hasattr(args, "partition") and args.partition else session_id

        # 判断用户输入的命令是哪个（argparse 已解析到 args.command）
        if args.command == "query":
            # query 命令：向系统提问
            # 重置输出缓冲，确保后续 print 立即输出
            print(end="", flush=True)
            # 检查是否指定了 --stream 参数（流式输出模式）
            if getattr(args, "stream", False):
                # 流式模式：调用 answer_generator 生成器，逐个处理事件
                for event in self.answer_generator(session_id, args.question, partition=partition):
                    # 如果事件类型是 token（文本片段），则直接打印到控制台（不换行，实时刷出）
                    if event.get("type") == "token":
                        print(event.get("text", ""), end="", flush=True)
                # 流式输出结束，打印一个换行
                print()
            else:
                # 非流式模式：直接调用 get_answer 获取完整答案
                answer = self.get_answer(session_id, args.question, partition=partition)
                # 打印完整答案到控制台
                print(answer)

        # 判断命令是否为 upload（上传文档）
        elif args.command == "upload":
            # 检查指定的路径是否存在（文件或目录）
            if not os.path.exists(args.path):
                # 如果路径不存在，打印错误提示并退出程序
                print("path not found:", args.path)
                sys.exit(1)
            # 判断路径是否指向一个文件
            if os.path.isfile(args.path):
                # 如果是文件，获取文件名（不包含目录路径）
                name = os.path.basename(args.path)
                # 在会话历史中插入一条上传事件记录
                self.data_store.insert_session_event(session_id, 'upload', [name])
                # 调用向量存储的 store_documents_from_dir 方法处理文件并存入向量库
                self.vector_store.store_documents_from_dir(args.path, partition=partition)
                # 打印上传成功的提示
                print("uploaded:", name)
            # 如果路径是一个目录
            elif os.path.isdir(args.path):
                # 调用向量存储的 store_documents_from_dir 方法处理目录下所有文件
                self.vector_store.store_documents_from_dir(args.path, partition=partition)
                # 打印上传成功的提示
                print("uploaded from dir:", args.path)

        # 判断命令是否为 chat（交互式聊天模式）
        elif args.command == "chat":
            # 打印提示信息，告诉用户进入交互模式，输入 /exit 退出
            print("Interactive mode. Type /exit to quit.")
            # 开始无限循环，处理多条用户输入
            while True:
                try:
                    # 获取用户输入，去除首尾空格
                    q = input("> ").strip()
                # 捕获 EOFError（用户按了 Ctrl+D 或 Ctrl+Z）和 KeyboardInterrupt（用户按了 Ctrl+C）
                except (EOFError, KeyboardInterrupt):
                    # 打印换行使界面更整洁
                    print()
                    # 退出循环
                    break
                # 如果输入为空（用户直接按了回车），则跳过本轮，继续等待输入
                if not q:
                    continue
                # 如果用户输入了 /exit，则退出交互模式
                if q == "/exit":
                    break
                try:
                    # 调用 get_answer 方法获取答案
                    answer = self.get_answer(session_id, q, partition=partition)
                    # 打印答案到控制台
                    print(answer)
                except Exception as e:
                    # 如果出错，打印错误信息
                    print("error:", e)

        # 判断命令是否为 info（显示会话信息）
        elif args.command == "info":
            # 打印会话 ID
            print(f"session:     {session_id}")
            # 打印分区 ID
            print(f"partition:   {partition}")
            # 获取该分区下的文档数量
            docs = self.vector_store.get_documents_by_partition(partition=partition)
            # 打印文档数量
            print(f"documents:   {len(docs)}")
            # 获取该会话的历史记录
            history = self.data_store.get_session_history(session_id)
            # 打印历史轮次数量
            print(f"history:     {len(history or [])} rounds")


# ===== build_parser 函数：构建命令行参数解析器 =====
# 定义一个名为 build_parser 的函数，用于创建和配置 argparse 参数解析器，处理各种 CLI 命令
def build_parser():
    # 创建一个 ArgumentParser 实例，description 参数指定了这个 CLI 工具的简短描述
    p = argparse.ArgumentParser(description="RAG CLI")
    # 添加子命令解析器：dest="command" 表示将子命令的名称存储在 args.command 属性中
    sp = p.add_subparsers(dest="command")

    # 创建 query 子命令：用于向系统提问
    q = sp.add_parser("query", help="ask a question")
    # 为 query 添加一个必需的位置参数：question，即问题文本
    q.add_argument("question", help="question text")
    # 为 query 添加一个可选的 --stream 标志参数：如果指定则启用流式输出
    q.add_argument("--stream", action="store_true", help="stream output")

    # 创建 upload 子命令：用于上传文档
    u = sp.add_parser("upload", help="upload document(s)")
    # 为 upload 添加一个必需的位置参数：path，即要上传的文件或目录路径
    u.add_argument("path", help="file or directory path")

    # 创建 chat 子命令：用于启动交互式聊天模式
    c = sp.add_parser("chat", help="interactive chat mode")

    # 创建 info 子命令：用于显示当前会话的信息
    i = sp.add_parser("info", help="show session info")

    # 遍历所有子命令（query、upload、chat、info），为它们添加公共的可选参数
    for sub in [q, u, c, i]:
        # 添加 --session 参数：用于指定会话 ID（不指定则自动生成）
        sub.add_argument("--session", help="session id")
        # 添加 --partition 参数：用于指定分区/用户 ID
        sub.add_argument("--partition", help="partition/user id")

    # 返回构建完成的参数解析器对象
    return p


# ===== 程序入口：当该文件作为主程序运行时执行 =====
# 判断当前脚本是否作为主程序直接运行（而不是被其他模块导入）
if __name__ == "__main__":
    # 创建一个 IntegratedSystem 实例（集成系统），初始化所有内部组件
    system = IntegratedSystem()
    # 调用 build_parser 函数获取命令行参数解析器
    parser = build_parser()
    # 解析命令行参数，将结果存储在 args 中
    args = parser.parse_args()
    # 如果没有指定任何子命令（args.command 为空）
    if not args.command:
        # 打印帮助信息（展示所有可用命令和参数说明）
        parser.print_help()
        # 退出程序，返回状态码 1（表示非正常退出）
        sys.exit(1)
    # 有命令则调用 IntegratedSystem 实例的 run_cli 方法执行对应的逻辑
    system.run_cli(args)
