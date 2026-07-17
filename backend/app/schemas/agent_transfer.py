from typing import Any

from pydantic import BaseModel

from app.schemas.skills import FewShotExample

EXPORT_FORMAT = "agent-forge-export-v1"


class ExportedTool(BaseModel):
    name: str
    tool_type: str
    config: dict[str, Any]
    input_schema: dict[str, Any]
    description: str | None = None


class ExportedSkill(BaseModel):
    name: str
    instruction_text: str
    few_shot_examples: list[FewShotExample] | None = None
    tags: list[str] | None = None


class ExportedAgentCore(BaseModel):
    name: str
    description: str | None
    base_instruction: str
    model_settings: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    output_key: str | None = None


class AgentExport(BaseModel):
    format: str = EXPORT_FORMAT
    agent: ExportedAgentCore
    tools: list[ExportedTool]
    skills: list[ExportedSkill]
    sub_agent_names: list[str]


class AgentImportResult(BaseModel):
    agent_id: str
    agent_name: str
    tools_created: list[str]
    tools_reused: list[str]
    skills_created: list[str]
    skills_reused: list[str]
    sub_agents_linked: list[str]
    sub_agents_missing: list[str]
