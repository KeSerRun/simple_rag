# 导入 Langchain 提示模板
from langchain_core.prompts import PromptTemplate
# 导入配置类
from base.config import conf
# 导入日志记录器
from base.logger import logger
# 导入大语言模型
from .llm import LLMModel

'''
策略选择器模块，负责根据用户输入选择合适的处理策略
使用llm模型进行策略选择，提示模板设计为引导模型根据用户输入分析并选择最合适的处理策略
需要下载模型：
modelscope download --model Qwen/Qwen2.5-0.5B-Instruct --local_dir ./model/qwen-2.5-0.5b-instruct
'''

# 定义策略选择器类
class StrategySelector(LLMModel):
    def __init__(self,model_path: str,device:str=None):
        super().__init__(model_path=model_path,device=device)
        # 运行设备
        self.device = device

    def get_strategy_prompt(self, query):
        # 定义提示模板，指导模型根据用户输入选择最合适的处理策略
        prompt_template = PromptTemplate(
            input_variables=["query"],
            template="""
请分析用户查询，并从以下四种策略中选择最合适的一项，仅返回策略名称（如“直接检索”），无需解释。

**策略定义：**
1. **直接检索**：意图明确、包含具体实体、询问单一事实。（例：学费多少？大纲是什么？）
2. **假设问题检索**：查询抽象宽泛，需生成相关问题引导。（例：AI的应用有哪些？适合人群？）
3. **子查询检索**：涉及多个实体或方面，需拆解分别检索。（例：A与B的对比？内容和适合人群？）
4. **回溯问题检索**：过于具体或含极端约束，需先理解原理。（例：100亿数据能存吗？MySQL不行了Milvus行吗？）

用户查询: {query}
            """
        )
        return prompt_template.format(query=query)
    
    ''' 定义选择策略的方法，接受用户查询作为输入，返回选择的策略 '''
    def select_strategy(self, query):
        # 获取提示词
        prompt = self.get_strategy_prompt(query)
        # 调用策略选择模型获取策略
        strategy = self._call_llm_model(prompt, max_new_tokens=8, temperature=0.1)
        # 验证模型返回的响应是否在预期的策略列表中，如果不在则记录警告日志并默认使用直接检索策略
        if strategy not in ["直接检索", "假设问题检索", "子查询检索", "回溯问题检索"]:
            logger.warning(f"策略选择器模型返回了非预期的响应: {strategy}，默认使用直接检索策略")
            return "直接检索"
        return strategy

if __name__ == "__main__":
    c = StrategySelector(model_path=conf.strategy_selector_model)
    res = c.select_strategy("MySQL数据库能不能支持100亿条记录的存储和查询？")
    print(res)
    res = c.select_strategy("这个Java课程适合哪些人群？")
    print(res)
    res = c.select_strategy("Java课程多少学费？")
    print(res)
