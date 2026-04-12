"""
Tests for Tool Calling Interface
==================================
Validates tool call parsing, validation, and system prompt generation.
"""

from src.agent.tool_interface import (
    parse_llm_output,
    validate_tool_call,
    build_system_prompt,
    build_tool_prompt,
    ToolCall,
    ToolResult,
    TOOL_DEFINITIONS,
)


# ── Parser Tests ──


class TestOutputParser:
    """LLM output parser must correctly extract tool calls and answers."""

    def test_parse_single_tool_call(self) -> None:
        output = """I need to read the file first.

<tool_call>
{"tool": "read_file", "params": {"path": "src/main.py"}}
</tool_call>"""

        result = parse_llm_output(output)
        assert result.has_tool_calls
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool == "read_file"
        assert result.tool_calls[0].params["path"] == "src/main.py"
        assert not result.is_final

    def test_parse_final_answer(self) -> None:
        output = """Based on my analysis:

<final_answer>
The bug is on line 42. The variable `count` is never initialized.
</final_answer>"""

        result = parse_llm_output(output)
        assert result.is_final
        assert "line 42" in result.final_answer
        assert not result.has_tool_calls

    def test_parse_reasoning_extracted(self) -> None:
        output = """Let me check the file structure first.

<tool_call>
{"tool": "list_files", "params": {"path": "src/"}}
</tool_call>"""

        result = parse_llm_output(output)
        assert "check the file structure" in result.reasoning

    def test_parse_malformed_json_produces_error(self) -> None:
        output = """<tool_call>
{this is not valid json}
</tool_call>"""

        result = parse_llm_output(output)
        assert not result.has_tool_calls
        assert result.has_errors

    def test_parse_unknown_tool_rejected(self) -> None:
        output = """<tool_call>
{"tool": "hack_system", "params": {"target": "root"}}
</tool_call>"""

        result = parse_llm_output(output)
        assert not result.has_tool_calls

    def test_parse_missing_required_param_rejected(self) -> None:
        output = """<tool_call>
{"tool": "read_file", "params": {}}
</tool_call>"""

        result = parse_llm_output(output)
        assert not result.has_tool_calls

    def test_parse_no_tags_returns_empty(self) -> None:
        output = "Just a plain text response without any tool calls."
        result = parse_llm_output(output)
        assert not result.has_tool_calls
        assert not result.is_final
        assert "plain text response" in result.reasoning

    def test_parse_write_file_with_content(self) -> None:
        output = """<tool_call>
{"tool": "write_file", "params": {"path": "test.py", "content": "print('hello')"}}
</tool_call>"""

        result = parse_llm_output(output)
        assert result.has_tool_calls
        assert result.tool_calls[0].tool == "write_file"
        assert result.tool_calls[0].params["content"] == "print('hello')"

    def test_parse_run_command(self) -> None:
        output = """<tool_call>
{"tool": "run_command", "params": {"command": "pytest tests/"}}
</tool_call>"""

        result = parse_llm_output(output)
        assert result.has_tool_calls
        assert result.tool_calls[0].params["command"] == "pytest tests/"

    def test_parse_delete_with_reason(self) -> None:
        output = """<tool_call>
{"tool": "delete_file", "params": {"path": "old.py", "reason": "Replaced by new.py"}}
</tool_call>"""

        result = parse_llm_output(output)
        assert result.has_tool_calls
        assert result.tool_calls[0].params["reason"] == "Replaced by new.py"

    def test_parse_delete_without_reason_rejected(self) -> None:
        output = """<tool_call>
{"tool": "delete_file", "params": {"path": "old.py"}}
</tool_call>"""

        result = parse_llm_output(output)
        assert not result.has_tool_calls

    def test_parse_git_status_no_params(self) -> None:
        output = """<tool_call>
{"tool": "git_status", "params": {}}
</tool_call>"""

        result = parse_llm_output(output)
        assert result.has_tool_calls
        assert result.tool_calls[0].tool == "git_status"

    def test_parse_optional_params_use_defaults(self) -> None:
        output = """<tool_call>
{"tool": "list_files", "params": {}}
</tool_call>"""

        result = parse_llm_output(output)
        assert result.has_tool_calls
        assert result.tool_calls[0].tool == "list_files"


# ── Validation Tests ──


class TestToolValidation:
    """Tool call validation must catch invalid calls."""

    def test_valid_tool_passes(self) -> None:
        call = ToolCall(tool="read_file", params={"path": "test.py"})
        error = validate_tool_call(call)
        assert error is None

    def test_unknown_tool_rejected(self) -> None:
        call = ToolCall(tool="hack_system", params={})
        error = validate_tool_call(call)
        assert error is not None
        assert "Unknown tool" in error

    def test_missing_required_param_rejected(self) -> None:
        call = ToolCall(tool="read_file", params={})
        error = validate_tool_call(call)
        assert error is not None
        assert "Missing required" in error


# ── Tool Result Formatting ──


class TestToolResult:
    """Tool results must format correctly for LLM consumption."""

    def test_success_format(self) -> None:
        result = ToolResult(
            tool="read_file",
            success=True,
            output="print('hello')",
        )
        formatted = result.format_for_llm()
        assert 'success="true"' in formatted
        assert "print('hello')" in formatted

    def test_failure_format(self) -> None:
        result = ToolResult(
            tool="read_file",
            success=False,
            output="",
            error="File not found: test.py",
        )
        formatted = result.format_for_llm()
        assert 'success="false"' in formatted
        assert "File not found" in formatted


# ── System Prompt Tests ──


class TestSystemPrompt:
    """System prompt must include all tools and format instructions."""

    def test_prompt_includes_all_tools(self) -> None:
        prompt = build_tool_prompt()
        for tool_name in TOOL_DEFINITIONS:
            assert tool_name in prompt

    def test_prompt_includes_format_instructions(self) -> None:
        prompt = build_tool_prompt()
        assert "<tool_call>" in prompt
        assert "<final_answer>" in prompt
        assert "ONE tool call per response" in prompt

    def test_full_system_prompt_includes_base(self) -> None:
        prompt = build_system_prompt("You are a helpful assistant.")
        assert "helpful assistant" in prompt
        assert "<tool_call>" in prompt
