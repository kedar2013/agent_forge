from typing import Any

from app.models.tools import Tool
from app.tool_registry.http_tool import HttpTool
from app.tool_registry.image_gen_tool import ImageGenTool
from app.tool_registry.mcp_tool import build_mcp_toolset
from app.tool_registry.data_query_tool import DataQueryTool
from app.tool_registry.mongo_tool import MongoQueryTool
from app.tool_registry.mysql_tool import MySQLQueryTool
from app.tool_registry.nl2sql_tool import DbSchemaTool, Nl2SqlQueryTool
from app.tool_registry.read_scratchpad_tool import ReadScratchpadTool
from app.tool_registry.reservation_demo_tool import ReservationDemoTool
from app.tool_registry.retrieval_tool import RetrievalTool
from app.tool_registry.self_healing_sql_tool import SelfHealingSqlTool
from app.tool_registry.sql_tool import SqlTool


def build_tool(tool: Tool) -> Any:
    """Turns one `tools` row into an ADK-callable tool/toolset.

    Never accepts or executes raw code from the row — each tool_type maps to
    a fixed Python class whose behavior is fully determined by declarative
    JSONB config.
    """
    if tool.tool_type == "http_tool":
        return HttpTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "sql_tool":
        return SqlTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "retrieval_tool":
        return RetrievalTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "mcp_tool":
        return build_mcp_toolset(tool.config)
    if tool.tool_type == "image_gen_tool":
        return ImageGenTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "db_schema_tool":
        return DbSchemaTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "nl2sql_query_tool":
        return Nl2SqlQueryTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "mongo_query_tool":
        return MongoQueryTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "mysql_query_tool":
        return MySQLQueryTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "data_query_tool":
        return DataQueryTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "self_healing_sql_tool":
        return SelfHealingSqlTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "read_scratchpad_tool":
        return ReadScratchpadTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )
    if tool.tool_type == "reservation_demo_tool":
        return ReservationDemoTool(
            name=tool.name,
            description=tool.description or tool.name,
            input_schema=tool.input_schema,
            config=tool.config,
        )

    raise ValueError(f"Unknown tool_type: {tool.tool_type}")
