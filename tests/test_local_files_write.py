"""Tests for local_files write operations — covers AC-01 through AC-05."""

import os
import tempfile

import pytest

from apps.bot.tool.local_files.handler import Tool as LocalFilesTool


@pytest.fixture
def tool():
    """Create a local_files tool with a temp directory as allowed root."""
    t = LocalFilesTool()
    tmpdir = tempfile.mkdtemp()
    t._allowed_roots = [__import__("pathlib").Path(tmpdir).resolve()]
    yield t, tmpdir
    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# --- AC-01: write_file creates or overwrites a file ---

@pytest.mark.asyncio
async def test_write_file_create(tool):
    t, tmpdir = tool
    path = os.path.join(tmpdir, "hello.txt")
    result = await t.execute(action="write_file", path=path, content="Hello, World!")
    assert "File written" in result
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        assert f.read() == "Hello, World!"


@pytest.mark.asyncio
async def test_write_file_overwrite(tool):
    t, tmpdir = tool
    path = os.path.join(tmpdir, "overwrite.txt")
    await t.execute(action="write_file", path=path, content="First")
    await t.execute(action="write_file", path=path, content="Second")
    with open(path, encoding="utf-8") as f:
        assert f.read() == "Second"


@pytest.mark.asyncio
async def test_write_file_auto_create_parent(tool):
    """AC-01: Auto-create parent directories."""
    t, tmpdir = tool
    path = os.path.join(tmpdir, "sub", "deep", "file.txt")
    result = await t.execute(action="write_file", path=path, content="Nested!")
    assert "File written" in result
    assert os.path.isfile(path)


# --- AC-02: append_file appends to a file ---

@pytest.mark.asyncio
async def test_append_file(tool):
    t, tmpdir = tool
    path = os.path.join(tmpdir, "append.txt")
    await t.execute(action="write_file", path=path, content="Line 1\n")
    await t.execute(action="append_file", path=path, content="Line 2\n")
    with open(path, encoding="utf-8") as f:
        assert f.read() == "Line 1\nLine 2\n"


@pytest.mark.asyncio
async def test_append_file_creates_new(tool):
    """Append to non-existent file should create it."""
    t, tmpdir = tool
    path = os.path.join(tmpdir, "new_append.txt")
    result = await t.execute(action="append_file", path=path, content="First line")
    assert "appended" in result
    assert os.path.isfile(path)


# --- AC-03: mkdir creates directories ---

@pytest.mark.asyncio
async def test_mkdir(tool):
    t, tmpdir = tool
    path = os.path.join(tmpdir, "new_dir")
    result = await t.execute(action="mkdir", path=path)
    assert "Directory created" in result
    assert os.path.isdir(path)


@pytest.mark.asyncio
async def test_mkdir_nested(tool):
    t, tmpdir = tool
    path = os.path.join(tmpdir, "a", "b", "c")
    result = await t.execute(action="mkdir", path=path)
    assert "Directory created" in result
    assert os.path.isdir(path)


@pytest.mark.asyncio
async def test_mkdir_existing(tool):
    """mkdir on existing dir should succeed (exist_ok=True)."""
    t, tmpdir = tool
    result = await t.execute(action="mkdir", path=tmpdir)
    assert "Directory created" in result


# --- AC-04: Path whitelist enforcement ---

@pytest.mark.asyncio
async def test_write_outside_allowed_path(tool):
    t, _ = tool
    result = await t.execute(action="write_file", path="/tmp/evil.txt", content="hack")
    assert "outside allowed directories" in result


@pytest.mark.asyncio
async def test_append_outside_allowed_path(tool):
    t, _ = tool
    result = await t.execute(action="append_file", path="/tmp/evil.txt", content="hack")
    assert "outside allowed directories" in result


@pytest.mark.asyncio
async def test_mkdir_outside_allowed_path(tool):
    t, _ = tool
    result = await t.execute(action="mkdir", path="/tmp/evil_dir")
    assert "outside allowed directories" in result


# --- AC-05: Content size limit ---

@pytest.mark.asyncio
async def test_write_file_too_large(tool):
    t, tmpdir = tool
    path = os.path.join(tmpdir, "big.txt")
    # 102400 bytes = 100KB max, exceed it
    content = "x" * 102401
    result = await t.execute(action="write_file", path=path, content=content)
    assert "too large" in result
    assert not os.path.exists(path)


@pytest.mark.asyncio
async def test_write_file_at_limit(tool):
    t, tmpdir = tool
    path = os.path.join(tmpdir, "exact.txt")
    content = "x" * 102400  # exactly at limit
    result = await t.execute(action="write_file", path=path, content=content)
    assert "File written" in result


# --- Read operations still work ---

@pytest.mark.asyncio
async def test_read_after_write(tool):
    t, tmpdir = tool
    path = os.path.join(tmpdir, "readback.txt")
    await t.execute(action="write_file", path=path, content="Read me back")
    result = await t.execute(action="read_file", path=path)
    assert "Read me back" in result


@pytest.mark.asyncio
async def test_list_dir_after_write(tool):
    t, tmpdir = tool
    await t.execute(action="write_file", path=os.path.join(tmpdir, "a.txt"), content="A")
    await t.execute(action="mkdir", path=os.path.join(tmpdir, "subdir"))
    result = await t.execute(action="list_dir", path=tmpdir)
    assert "a.txt" in result
    assert "subdir" in result
