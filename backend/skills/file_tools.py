"""
Görev ajanının dosya araçları + riskli işlem sınıflandırması.
Kural: workspace içine yazma serbest; workspace dışına yazma, her türlü
silme/taşıma/kopyalama ve run_command ONAY ister (spec: 2026-07-22).
"""
import shutil
from pathlib import Path

READ_LIMIT = 50_000  # karakter; uzun dosyalar kırpılır

ALWAYS_APPROVAL = {"delete_path", "move_path", "copy_path", "run_command"}

# read_file için hassas dosya/klasör engeli (büyük/küçük harf duyarsız):
# - yol parçalarından biri bu isimlerden biriyse (ör. .env klasörü/dosyası, .ssh)
# - VEYA dosya adı bu alt dizeleri içeriyorsa / bu uzantılarla bitiyorsa
SENSITIVE_PATTERNS = {
    "dir_names": {".env", ".git", ".ssh", ".aws"},
    "name_contains": ("id_rsa", "credentials"),
    "suffixes": (".pem", ".key"),
}


def _is_sensitive_path(p: Path) -> bool:
    parts_lower = {part.lower() for part in p.parts}
    if parts_lower & SENSITIVE_PATTERNS["dir_names"]:
        return True
    name_lower = p.name.lower()
    if any(sub in name_lower for sub in SENSITIVE_PATTERNS["name_contains"]):
        return True
    if name_lower.endswith(SENSITIVE_PATTERNS["suffixes"]):
        return True
    return False


class FileTools:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        return p.resolve()

    def list_dir(self, path: str = "") -> str:
        p = self._resolve(path)
        if not p.is_dir():
            return f"Klasör bulunamadı: {p}"
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        lines = [f"{'[D]' if e.is_dir() else '[F]'} {e.name}" for e in entries]
        return "\n".join(lines) or "(boş klasör)"

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if _is_sensitive_path(p):
            return f"Bu dosya hassas bilgiler içerebilir, okumuyorum: {p.name}"
        if not p.is_file():
            return f"Dosya bulunamadı: {p}"
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > READ_LIMIT:
            return text[:READ_LIMIT] + f"\n... (kırpıldı, toplam {len(text)} karakter)"
        return text

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Yazıldı: {p} ({len(content)} karakter)"

    def delete_path(self, path: str) -> str:
        p = self._resolve(path)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
        else:
            return f"Zaten yok: {p}"
        return f"Silindi: {p}"

    def move_path(self, src: str, dst: str) -> str:
        s, d = self._resolve(src), self._resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"Taşındı: {s} -> {d}"

    def copy_path(self, src: str, dst: str) -> str:
        s, d = self._resolve(src), self._resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        return f"Kopyalandı: {s} -> {d}"


def _resolve_arg(raw: str, workspace: Path) -> Path:
    """FileTools._resolve ile aynı mantık: göreli yol workspace'e göre çözülür."""
    p = Path(raw)
    if not p.is_absolute():
        p = workspace / p
    return p.resolve()


def requires_approval(tool_name: str, args: dict, workspace: Path) -> tuple[bool, str]:
    """(onay_gerekli_mi, insan-okur eylem açıklaması) döndürür.
    Silme/taşıma/kopyalama açıklamaları, kullanıcının gerçek hedefi duyması
    için FileTools._resolve ile aynı şekilde çözülmüş (mutlak) yolları içerir."""
    workspace = Path(workspace).resolve()

    if tool_name in ALWAYS_APPROVAL:
        if tool_name == "run_command":
            return True, f"şu komutu çalıştıracağım: {args.get('command', '?')}"
        if tool_name == "delete_path":
            p = _resolve_arg(args.get("path", "?"), workspace)
            return True, f"şunu sileceğim: {p}"
        if tool_name == "move_path":
            s = _resolve_arg(args.get("src", "?"), workspace)
            d = _resolve_arg(args.get("dst", "?"), workspace)
            return True, f"şunu taşıyacağım: {s} -> {d}"
        s = _resolve_arg(args.get("src", "?"), workspace)
        d = _resolve_arg(args.get("dst", "?"), workspace)
        return True, f"şunu kopyalayacağım: {s} -> {d}"

    if tool_name == "write_file":
        p = _resolve_arg(args.get("path", ""), workspace)
        try:
            p.relative_to(workspace)
            return False, ""
        except ValueError:
            return True, f"workspace dışına dosya yazacağım: {p}"

    return False, ""
