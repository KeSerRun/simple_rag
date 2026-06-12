# 导入 PromptTemplate 类，用于管理所有的 Prompt 模板
from langchain_core.prompts import PromptTemplate

# 定义 RAGPrompts 类，用于管理所有 Prompt 模板
class RAGPrompts:
    # 定义 RAG 提示模板，基于用户问题和上下文信息生成答案
    @staticmethod
    def context_prompt():
        # 创建并返回 PromptTemplate 实例，包含 RAG 提示的模板字符串和输入变量
        return PromptTemplate(
            input_variables=["context", "query"],
            template="""
            你是一个知识渊博的助手，专门回答用户的问题。
            如果知识库中没有相关信息，请直接回答问题。
            如果知识库中有相关信息，请根据其中的信息回答问题。

            知识库中的信息如下：
            {context}

            用户的问题是：
            {query}

            如果无法回答，请说“抱歉，我无法回答这个问题。”，不要编造答案。
        """
        )
    
    # 定义假设答案生成的提示模板
    @staticmethod
    def hyde_prompt():
        # 创建并返回 PromptTemplate 实例，包含假设答案生成提示的模板字符串和输入变量
        return PromptTemplate(
            input_variables=["query"],
            template="""
            假设你是用户，正在向一个博学的助手提问，你需要一个相关的假设答案。
            
            你想要请求的问题是：
            {query}
            
            请生成一个相关问题的假设答案。
        """
        )
    
    # 定义子查询提示模板
    @staticmethod
    def subquery_prompt():
        # 创建并返回 PromptTemplate 实例，包含子查询提示的模板字符串和输入变量
        return PromptTemplate(
            input_variables=["query"],
            template="""
            你是一个灵活的助手，专门将用户的问题分解为相关的子问题。
            请根据用户的问题生成一个简洁、相关的子问题。

            用户的问题是：
            {query}

            请生成一个适合用于检索的子问题，如果问题涉及多个方面，请生成多个子问题，每个子问题独占一行。
        """
        )

    # 定义回溯问题生成的提示模板
    @staticmethod
    def backtracking_prompt():
        # 创建并返回 PromptTemplate 实例，包含回溯问题生成提示的模板字符串和输入变量
        return PromptTemplate(
            input_variables=["query"],
            template="""
            你是一个聪明的助手，可以提取用户问题中的关键信息，并组织为一段更加简洁的回溯问题。
            请根据用户的问题生成一个简洁、相关的回溯问题。

            用户的问题是：
            {query}

            请生成一个适合用于检索的回溯问题。
        """
        )

