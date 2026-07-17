from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types


class ConfigDrivenTool(BaseTool):
    """Base for every tool built from a Postgres `tools` row.

    Subclasses only implement `run_async`; the callable's schema exposed to
    the model comes straight from the tool's stored `input_schema` JSON
    schema, so nothing here ever eval()s user-supplied code.
    """

    def __init__(self, *, name: str, description: str, input_schema: dict) -> None:
        super().__init__(name=name, description=description or name)
        self._input_schema = input_schema

    def _get_declaration(self) -> types.FunctionDeclaration | None:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self._input_schema or {"type": "object", "properties": {}},
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        raise NotImplementedError
