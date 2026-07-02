"""第三方工具示例：通过 registry 注册自定义工具。

按以下模板创建自己的工具文件，放在 tools_extra/ 目录下即可被自动加载。

注意:
  - 文件名不能以 _ 开头（如 my_tool.py ✓，_helper.py ✗）
  - 必须导出 register(registry) 函数
  - handler 接收 (args: dict, ctx: ToolContext) -> str
  - 所有异常应该在 handler 内部处理，返回友好错误文本
"""
from agent.registry import ToolContext


def _exec_current_time(args: dict, ctx: ToolContext) -> str:
    """返回当前服务器时间。"""
    from datetime import datetime
    return f"当前服务器时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


def register(registry):
    """注册自定义工具（Agent 启动时自动调用）。"""
    registry.register(
        name="get_current_time",
        description="获取当前服务器日期和时间。当用户询问「现在几点」「今天几号」时调用。",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_exec_current_time,
        source=__name__,
    )
