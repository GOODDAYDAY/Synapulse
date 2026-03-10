"""Tests for shell_exec handler — covers AC-06 through AC-09, AC-12."""

import os
import tempfile

import pytest

from apps.bot.tool.shell_exec.handler import Tool as ShellExecTool, _decode_output, _format_result


@pytest.fixture
def tool():
    """Create a shell_exec tool with a temp directory as default cwd."""
    t = ShellExecTool()
    tmpdir = tempfile.mkdtemp()
    t._default_cwd = tmpdir
    yield t, tmpdir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# --- AC-06: Execute a safe command and get output ---

@pytest.mark.asyncio
async def test_echo_command(tool):
    t, _ = tool
    result = await t.execute(command="echo hello world")
    assert "exit_code: 0" in result
    assert "hello world" in result


@pytest.mark.asyncio
async def test_command_with_working_dir(tool):
    t, tmpdir = tool
    # Create a file in tmpdir, then list it
    with open(os.path.join(tmpdir, "test_file.txt"), "w") as f:
        f.write("test")
    result = await t.execute(command="ls", working_dir=tmpdir)
    assert "exit_code: 0" in result
    assert "test_file.txt" in result


# --- AC-07: Dangerous commands are blocked ---

@pytest.mark.asyncio
async def test_blocked_command(tool):
    t, _ = tool
    result = await t.execute(command="rm -rf /")
    assert "blocked by safety policy" in result
    assert "recursive delete" in result


@pytest.mark.asyncio
async def test_blocked_sudo(tool):
    t, _ = tool
    result = await t.execute(command="sudo apt install something")
    assert "blocked by safety policy" in result


# --- AC-08: Timeout ---

@pytest.mark.asyncio
async def test_timeout(tool):
    """AC-08: Command that exceeds timeout is killed."""
    t, _ = tool
    # Use a 1-second timeout with a sleep command
    result = await t.execute(command="sleep 10", timeout=1)
    assert "timed out" in result


@pytest.mark.asyncio
async def test_timeout_clamped_to_max(tool):
    """Timeout > MAX_TIMEOUT is clamped to MAX_TIMEOUT (120s)."""
    t, _ = tool
    # Just verify it doesn't crash — actual timeout clamp is internal
    result = await t.execute(command="echo ok", timeout=9999)
    assert "exit_code: 0" in result


# --- AC-09: Output truncation ---

def test_format_result_truncation():
    """AC-09: Output longer than MAX_OUTPUT_CHARS is truncated."""
    long_stdout = "x" * 20000
    result = _format_result(0, long_stdout, "")
    assert "truncated" in result
    assert len(result) < 20000 + 200  # some overhead for prefix


# --- AC-12: Empty and whitespace-only commands ---

@pytest.mark.asyncio
async def test_empty_command(tool):
    t, _ = tool
    result = await t.execute(command="")
    assert "Error" in result
    assert "required" in result


@pytest.mark.asyncio
async def test_whitespace_command(tool):
    t, _ = tool
    result = await t.execute(command="   ")
    assert "Error" in result


# --- Helper function tests ---

def test_decode_output_utf8():
    assert _decode_output(b"hello") == "hello"


def test_decode_output_empty():
    assert _decode_output(b"") == ""


def test_decode_output_binary():
    result = _decode_output(b"\x80\x81\x82\x83" * 100)
    assert "binary output" in result


def test_format_result_no_output():
    result = _format_result(0, "", "")
    assert "no output" in result


def test_format_result_with_stderr():
    result = _format_result(1, "", "error occurred")
    assert "exit_code: 1" in result
    assert "stderr" in result
    assert "error occurred" in result


# --- Invalid working directory ---

@pytest.mark.asyncio
async def test_invalid_working_dir(tool):
    t, _ = tool
    result = await t.execute(command="echo test", working_dir="/nonexistent/dir")
    assert "does not exist" in result


# --- Non-zero exit code ---

@pytest.mark.asyncio
async def test_nonzero_exit_code(tool):
    t, _ = tool
    result = await t.execute(command="false")
    assert "exit_code: 1" in result
