# app/tool_registry.py
import asyncio
from typing import Callable, Dict

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Callable] = {}

    def register(self, name: str, func: Callable):
        self.tools[name] = func

    async def execute(self, name: str, params: Dict) -> str:
        if name not in self.tools:
            return f"Error: Tool '{name}' not found"
        try:
            func = self.tools[name]
            result = await func(**params) if asyncio.iscoroutinefunction(func) else func(**params)
            return str(result)
        except Exception as e:
            return f"Tool error: {str(e)}"

# ─── Default tools ───────────────────────────────────────────────────

async def _tool_write_file(path: str, content: str) -> str:
    # In real deploy, use S3 or volume
    return f"Wrote {len(content)} chars to {path}"

async def _tool_read_file(path: str) -> str:
    return f"Contents of {path}: [placeholder]"

async def _tool_execute_python(code: str) -> str:
    # Use restricted exec or Docker
    return f"Executed Python code: {code[:50]}..."

async def _tool_web_search(query: str) -> str:
    # Integrate with search API
    return f"Search results for: {query}"

def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("write_file", _tool_write_file)
    registry.register("read_file", _tool_read_file)
    registry.register("execute_python", _tool_execute_python)
    registry.register("web_search", _tool_web_search)
    return registry
