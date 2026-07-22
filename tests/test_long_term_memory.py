from datetime import datetime
from backend.core.long_term_memory import MemoryStore


def test_save_fact_creates_file_with_header_and_entry(tmp_path):
    store = MemoryStore(tmp_path)
    msg = store.save_fact("hakkimda", "Egemen Sakarya Üniversitesi mezunu")
    assert "hakkimda" in msg
    content = (tmp_path / "hakkimda.md").read_text(encoding="utf-8")
    assert "Egemen Sakarya Üniversitesi mezunu" in content


def test_save_fact_appends_without_duplicate_header(tmp_path):
    store = MemoryStore(tmp_path)
    store.save_fact("hakkimda", "Birinci gerçek")
    store.save_fact("hakkimda", "İkinci gerçek")
    content = (tmp_path / "hakkimda.md").read_text(encoding="utf-8")
    assert content.count("# hakkimda") == 1
    assert "Birinci gerçek" in content and "İkinci gerçek" in content


def test_save_fact_new_category_adds_to_index(tmp_path):
    store = MemoryStore(tmp_path)
    store.save_fact("is-hayati", "Yeni bir işe başladı")
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "is-hayati" in index


def test_save_fact_existing_category_does_not_duplicate_index(tmp_path):
    store = MemoryStore(tmp_path)
    store.save_fact("hakkimda", "Bir")
    store.save_fact("hakkimda", "İki")
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert index.count("hakkimda") == 1


def test_append_digest_creates_dated_file(tmp_path):
    store = MemoryStore(tmp_path)
    when = datetime(2026, 7, 22, 14, 30)
    store.append_digest("Bugün Faz 2 konuşuldu.", when=when)
    content = (tmp_path / "digests" / "2026-07-22.md").read_text(encoding="utf-8")
    assert "14:30" in content
    assert "Bugün Faz 2 konuşuldu." in content


def test_append_digest_same_day_appends_new_section(tmp_path):
    store = MemoryStore(tmp_path)
    store.append_digest("Sabah konuşması.", when=datetime(2026, 7, 22, 9, 0))
    store.append_digest("Akşam konuşması.", when=datetime(2026, 7, 22, 20, 0))
    content = (tmp_path / "digests" / "2026-07-22.md").read_text(encoding="utf-8")
    assert "Sabah konuşması." in content
    assert "Akşam konuşması." in content
    assert content.count("2026-07-22") == 1  # tek başlık, iki alt bölüm


def test_read_core_files_includes_only_core_categories(tmp_path):
    store = MemoryStore(tmp_path)
    store.save_fact("hakkimda", "Çekirdek bilgi")
    store.save_fact("cok-ozel-bir-konu", "Çekirdek dışı bilgi")
    core_text = store.read_core_files()
    assert "Çekirdek bilgi" in core_text
    assert "Çekirdek dışı bilgi" not in core_text


def test_read_core_files_empty_store_returns_empty_string(tmp_path):
    store = MemoryStore(tmp_path)
    assert store.read_core_files().strip() == ""


def test_add_and_read_todos(tmp_path):
    store = MemoryStore(tmp_path)
    store.add_todo("Sunucuyu yeniden başlat")
    todos = store.read_todos()
    assert "- [ ] Sunucuyu yeniden başlat" in todos


def test_complete_todo_marks_checkbox(tmp_path):
    store = MemoryStore(tmp_path)
    store.add_todo("Rapor yaz")
    msg = store.complete_todo("Rapor yaz")
    assert "Tamamlandı" in msg
    todos = store.read_todos()
    assert "- [x] Rapor yaz" in todos
    assert "- [ ] Rapor yaz" not in todos


def test_complete_todo_not_found(tmp_path):
    store = MemoryStore(tmp_path)
    msg = store.complete_todo("Olmayan madde")
    assert "bulunamadı" in msg


def test_read_todos_empty(tmp_path):
    store = MemoryStore(tmp_path)
    assert "boş" in store.read_todos()


def test_search_digests_finds_match(tmp_path):
    store = MemoryStore(tmp_path)
    store.append_digest("Görev ajanı hakkında konuşuldu.", when=datetime(2026, 7, 20, 10, 0))
    result = store.search_digests("görev ajanı")
    assert "Görev ajanı hakkında konuşuldu." in result


def test_search_digests_no_match(tmp_path):
    store = MemoryStore(tmp_path)
    result = store.search_digests("alakasız bir konu")
    assert "bulunamadı" in result
