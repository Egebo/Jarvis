from pathlib import Path
from backend.skills.file_tools import FileTools, requires_approval


def test_write_and_read_inside_workspace(tmp_path):
    ft = FileTools(workspace=tmp_path)
    msg = ft.write_file("rapor.md", "# Merhaba")
    assert "rapor.md" in msg
    assert ft.read_file("rapor.md") == "# Merhaba"
    assert "rapor.md" in ft.list_dir("")


def test_workspace_created_on_init(tmp_path):
    ws = tmp_path / "yeni-workspace"
    FileTools(workspace=ws)
    assert ws.is_dir()


def test_read_missing_file_returns_error_text(tmp_path):
    ft = FileTools(workspace=tmp_path)
    assert "bulunamadı" in ft.read_file("yok.txt")


def test_delete_and_move_work(tmp_path):
    ft = FileTools(workspace=tmp_path)
    ft.write_file("a.txt", "x")
    ft.move_path("a.txt", "b.txt")
    assert (tmp_path / "b.txt").exists() and not (tmp_path / "a.txt").exists()
    ft.delete_path("b.txt")
    assert not (tmp_path / "b.txt").exists()


def test_approval_rules(tmp_path):
    ws = tmp_path
    ok, _ = requires_approval("read_file", {"path": "x.txt"}, ws)
    assert ok is False
    ok, _ = requires_approval("list_dir", {"path": ""}, ws)
    assert ok is False
    ok, _ = requires_approval("write_file", {"path": "rapor.md", "content": ""}, ws)
    assert ok is False  # workspace içi yazma serbest
    ok, desc = requires_approval("write_file", {"path": str(Path.home() / "x.txt"), "content": ""}, ws)
    assert ok is True and "x.txt" in desc  # workspace dışı yazma onaylı
    for tool in ("delete_path", "move_path", "copy_path", "run_command"):
        ok, _ = requires_approval(tool, {"path": "ws-ici.txt", "src": "a", "dst": "b", "command": "dir"}, ws)
        assert ok is True  # her zaman onaylı


def test_relative_traversal_requires_approval(tmp_path):
    ok, desc = requires_approval("write_file", {"path": "../kacak.txt", "content": ""}, tmp_path)
    assert ok is True and "kacak.txt" in desc
