"""工具注册表：装饰器注册 + 自动发现 + JSON Schema 生成 + 超时保护 + 分发执行。"""

import asyncio
import importlib
import inspect
import json
import os
from collections.abc import Callable

from utils.logger import log_error, log_tool, log_warning


class ToolRegistry:
    """管理所有可用工具的注册、schema 导出和执行分发。"""

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def tool(
        self,
        name: str,
        description: str,
        params: dict[str, dict] | None = None,
    ) -> Callable:
        """装饰器：注册一个工具函数。

        用法:
            @registry.tool(
                name="browser_navigate",
                description="打开浏览器访问指定 URL",
                params={"url": {"type": "string", "description": "目标 URL"}}
            )
            async def browser_navigate(url: str) -> str:
                ...
        """

        def decorator(func: Callable) -> Callable:
            self._tools[name] = {
                "name": name,
                "description": description,
                "params": params or {},
                "func": func,
            }
            return func

        return decorator

    def get_tools_schema(self) -> list[dict]:
        """导出 OpenAI function calling 格式的工具列表。"""
        schemas = []
        for name, tool_info in self._tools.items():
            properties = {}
            required = []
            for param_name, param_spec in tool_info["params"].items():
                properties[param_name] = {
                    "type": param_spec.get("type", "string"),
                    "description": param_spec.get("description", ""),
                }
                if param_spec.get("required", True):
                    required.append(param_name)

            schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool_info["description"],
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
            schemas.append(schema)
        return schemas

    async def execute(
        self,
        name: str,
        arguments: str | dict,
        timeout: int = 60,
        max_retries: int = 0,
        silent: bool = False,
    ) -> str:
        """执行指定工具，支持超时保护和重试。silent=True 时不打印 log_tool。

        返回字符串形式的结果或错误信息（供 LLM 消费）。内部错误会构造为
        ToolError/ToolTimeout/ToolNotFound 实例后转字符串，保证错误格式统一。
        """
        from agent.errors import ToolError, ToolNotFound, ToolTimeout

        if name not in self._tools:
            err = ToolNotFound(message="工具未注册", tool_name=name)
            log_error(str(err))
            return str(err)

        tool_info = self._tools[name]
        func = tool_info["func"]

        # 解析参数
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                args = {}
        else:
            args = arguments

        last_error: ToolError | None = None
        for attempt in range(1 + max_retries):
            try:
                if inspect.iscoroutinefunction(func):
                    result = await asyncio.wait_for(func(**args), timeout=timeout)
                else:
                    loop = asyncio.get_event_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: func(**args)),
                        timeout=timeout,
                    )

                result_str = str(result)
                if not silent:
                    log_tool(name, result_str[:200])
                return result_str

            except TimeoutError:
                last_error = ToolTimeout(
                    message="超过最大执行时间",
                    tool_name=name,
                    timeout_seconds=timeout,
                )
                log_warning(str(last_error))
            except (TypeError, ValueError, KeyError) as e:
                # 参数 / 数据结构错误，通常不可恢复，无需重试
                last_error = ToolError(
                    message=f"参数错误: {type(e).__name__}: {e}",
                    tool_name=name,
                    recoverable=False,
                )
                log_error(str(last_error))
                break
            except Exception as e:
                last_error = ToolError(
                    message=f"{type(e).__name__}: {e}",
                    tool_name=name,
                )
                log_error(str(last_error))

            if attempt < max_retries:
                log_warning(f"重试 {name} ({attempt + 1}/{max_retries})...")
                await asyncio.sleep(1)

        return str(last_error) if last_error else f"工具 {name} 执行失败"

    def auto_discover(self, package_dir: str = "tools") -> None:
        """自动扫描指定包目录下的所有 .py 模块并导入，触发 @registry.tool 注册。"""
        skip = {"__init__", "recon_wordlists"}
        base_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), package_dir)

        if not os.path.isdir(base_path):
            log_error(f"工具目录不存在: {base_path}")
            return

        before = set(self._tools.keys())
        for filename in sorted(os.listdir(base_path)):
            if not filename.endswith(".py"):
                continue
            module_name = filename[:-3]
            if module_name in skip:
                continue
            full_module = f"{package_dir}.{module_name}"
            try:
                importlib.import_module(full_module)
            except Exception as e:
                log_error(f"自动发现跳过 {full_module}: {e}")

        new_tools = set(self._tools.keys()) - before
        # 仅写文件日志，不污染启动 banner
        try:
            from utils.logger import file_logger

            file_logger.write("INFO", f"工具自动发现完成: {len(new_tools)} 个新工具从 {package_dir}/ 注册")
        except Exception:
            pass

    def list_tools(self) -> list[str]:
        """返回所有已注册工具名列表。"""
        return list(self._tools.keys())


# 全局注册表实例
registry = ToolRegistry()
