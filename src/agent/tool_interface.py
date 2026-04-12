"""
Tool Calling Interface
=======================
Defines the contract between the LLM and the tool layer.

Components:
  - Tool registry: what tools exist and their parameters
  - System prompt builder: instructs LLM on tool call format
  - Output parser: extracts tool calls from LLM output
  - Result formatter: formats tool results for LLM consumption

Format:
  LLM requests:  <tool_call>{"tool": "name", "params": {...}}</tool_call>
  Agent returns:  <tool_result tool="name" success="true/false">...</tool_result>
  LLM finishes:  <final_answer>...</final_answer>

Security design:
  - Tool names validated against registry (no arbitrary tool execution)
  - Parameters validated per tool schema
  - Malformed tool calls rejected with error feedback
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ── Tool Call Format Patterns ──

_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL,
)

_FINAL_ANSWER_PATTERN = re.compile(
    r"<final_answer>\s*(.*?)\s*</final_answer>",
    re.DOTALL,
)


@dataclass
class ToolCall:
    """Parsed tool call from LLM output."""

    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    raw: str = ""


@dataclass
class ToolResult:
    """Result of tool execution to feed back to LLM."""

    tool: str
    success: bool
    output: str
    error: Optional[str] = None

    def format_for_llm(self) -> str:
        """Format as XML for LLM consumption."""
        status = "true" if self.success else "false"
        content = self.output if self.success else f"Error: {self.error}"
        return (
            f'<tool_result tool="{self.tool}" success="{status}">\n'
            f"{content}\n"
            f"</tool_result>"
        )


@dataclass
class ParsedResponse:
    """Parsed LLM response containing tool calls and/or final answer."""

    tool_calls: list[ToolCall] = field(default_factory=list)
    final_answer: Optional[str] = None
    reasoning: str = ""
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_final(self) -> bool:
        return self.final_answer is not None

    @property
    def has_errors(self) -> bool:
        return len(self.parse_errors) > 0


# ── Tool Registry ──

TOOL_DEFINITIONS = {
    "read_file": {
        "description": "Read the contents of a file in the workspace.",
        "params": {
            "path": {
                "type": "string",
                "required": True,
                "description": "File path relative to workspace root.",
            },
        },
    },
    "write_file": {
        "description": "Write content to a file in the workspace. Requires human approval.",
        "params": {
            "path": {
                "type": "string",
                "required": True,
                "description": "File path relative to workspace root.",
            },
            "content": {
                "type": "string",
                "required": True,
                "description": "Content to write to the file.",
            },
        },
    },
    "list_files": {
        "description": "List files in a directory.",
        "params": {
            "path": {
                "type": "string",
                "required": False,
                "description": "Directory path. Defaults to workspace root.",
                "default": ".",
            },
            "recursive": {
                "type": "boolean",
                "required": False,
                "description": "Include subdirectories.",
                "default": False,
            },
        },
    },
    "search_files": {
        "description": "Search for files matching a glob pattern.",
        "params": {
            "pattern": {
                "type": "string",
                "required": True,
                "description": "Glob pattern (e.g., '*.py', 'test_*.py').",
            },
            "path": {
                "type": "string",
                "required": False,
                "description": "Directory to search in. Defaults to workspace root.",
                "default": ".",
            },
        },
    },
    "run_command": {
        "description": (
            "Execute a shell command in the workspace. "
            "Requires human approval. Only allowed commands can be executed."
        ),
        "params": {
            "command": {
                "type": "string",
                "required": True,
                "description": "Shell command to execute.",
            },
        },
    },
    "delete_file": {
        "description": (
            "Delete a file in the workspace. Requires human approval "
            "with justification. Only single files, no directories."
        ),
        "params": {
            "path": {
                "type": "string",
                "required": True,
                "description": "File path to delete.",
            },
            "reason": {
                "type": "string",
                "required": True,
                "description": "Justification for deletion.",
            },
        },
    },
    "git_status": {
        "description": "Show current git status (branch, modified files, untracked files).",
        "params": {},
    },
    "git_diff": {
        "description": "Show git diff for the workspace or a specific file.",
        "params": {
            "path": {
                "type": "string",
                "required": False,
                "description": "Specific file to diff. Omit for full workspace diff.",
            },
        },
    },
}


def build_tool_prompt() -> str:
    """
    Build the tool usage section of the system prompt.

    Returns a formatted string describing all available tools
    and the expected call/response format.
    """
    tool_descriptions = []
    for name, definition in TOOL_DEFINITIONS.items():
        params_desc = []
        for param_name, param_info in definition.get("params", {}).items():
            required = "required" if param_info.get("required") else "optional"
            default = param_info.get("default", "")
            default_str = f", default: {default}" if default != "" else ""
            params_desc.append(
                f"    - {param_name} ({param_info['type']}, {required}{default_str}): "
                f"{param_info['description']}"
            )

        params_section = "\n".join(params_desc) if params_desc else "    (no parameters)"

        tool_descriptions.append(
            f"  {name}: {definition['description']}\n"
            f"  Parameters:\n{params_section}"
        )

    tools_text = "\n\n".join(tool_descriptions)

    return f"""You have access to the following tools to interact with the workspace:

{tools_text}

IMPORTANT RULES FOR TOOL USAGE:
1. To use a tool, wrap your call in <tool_call> tags with a JSON object:
   <tool_call>
   {{"tool": "tool_name", "params": {{"param1": "value1"}}}}
   </tool_call>

2. You may use ONE tool call per response.
   Wait for the result before making another call.

3. After receiving a tool result, reason about the output
   and decide your next step.

4. When you have completed the task and have a final response,
   wrap it in <final_answer> tags:
   <final_answer>
   Your complete response to the user here.
   </final_answer>

5. Always explain your reasoning BEFORE making a tool call.
   The user should understand why you are calling each tool.

6. If a tool call fails, analyze the error and either retry
   with corrected parameters or explain the issue in your
   final answer.

7. NEVER fabricate tool results. Only use information from
   actual tool results.

8. For file modifications (write_file, delete_file,
   run_command), the user will be asked to approve before
   execution. Provide clear justification in your reasoning."""


def build_system_prompt(base_prompt: str = "") -> str:
    """
    Build the complete system prompt with tool instructions.

    Args:
        base_prompt: Base agent personality/instructions.

    Returns:
        Complete system prompt with tool usage instructions.
    """
    if not base_prompt:
        base_prompt = (
            "You are a highly capable AI coding assistant. "
            "You help with code generation, debugging, refactoring, "
            "architecture review, and security analysis. "
            "Be concise, accurate, and security-conscious. "
            "Always explain your reasoning."
        )

    tool_prompt = build_tool_prompt()

    return f"{base_prompt}\n\n{tool_prompt}"


# ── Output Parser ──


def parse_llm_output(output: str) -> ParsedResponse:
    """
    Parse LLM output to extract tool calls and/or final answer.

    Handles:
      - Single tool call per response
      - Final answer extraction
      - Reasoning text (everything outside tags)
      - Malformed JSON in tool calls
      - Missing required parameters

    Args:
        output: Raw LLM output string.

    Returns:
        ParsedResponse with extracted components.
    """
    result = ParsedResponse()

    # Extract final answer if present
    final_match = _FINAL_ANSWER_PATTERN.search(output)
    if final_match:
        result.final_answer = final_match.group(1).strip()

    # Extract tool calls
    tool_matches = _TOOL_CALL_PATTERN.findall(output)
    for raw_call in tool_matches:
        tool_call = _parse_single_tool_call(raw_call.strip())
        if tool_call:
            result.tool_calls.append(tool_call)
        else:
            result.parse_errors.append(
                f"Failed to parse tool call: {raw_call[:100]}"
            )

    # Extract reasoning (text outside tags)
    reasoning = output
    for pattern in [_TOOL_CALL_PATTERN, _FINAL_ANSWER_PATTERN]:
        reasoning = pattern.sub("", reasoning)
    result.reasoning = reasoning.strip()

    return result


def _parse_single_tool_call(raw: str) -> Optional[ToolCall]:
    """
    Parse a single tool call JSON string.

    Returns:
        ToolCall if valid, None if malformed.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    tool_name = data.get("tool", "")
    if not tool_name or tool_name not in TOOL_DEFINITIONS:
        return None

    params = data.get("params", {})
    if not isinstance(params, dict):
        params = {}

    # Validate required parameters
    tool_def = TOOL_DEFINITIONS[tool_name]
    for param_name, param_info in tool_def.get("params", {}).items():
        if param_info.get("required") and param_name not in params:
            return None

    return ToolCall(
        tool=tool_name,
        params=params,
        raw=raw,
    )


def validate_tool_call(tool_call: ToolCall) -> Optional[str]:
    """
    Validate a parsed tool call against the registry.

    Returns:
        Error message if invalid, None if valid.
    """
    if tool_call.tool not in TOOL_DEFINITIONS:
        return f"Unknown tool: '{tool_call.tool}'"

    tool_def = TOOL_DEFINITIONS[tool_call.tool]

    for param_name, param_info in tool_def.get("params", {}).items():
        if param_info.get("required") and param_name not in tool_call.params:
            return f"Missing required parameter: '{param_name}' for tool '{tool_call.tool}'"

    return None
