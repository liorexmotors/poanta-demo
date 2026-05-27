from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


def test_index_has_article_share_button_and_whatsapp_builder():
    html = INDEX.read_text(encoding="utf-8")
    assert "data-share-article" in html
    assert "function articleShareUrl" in html
    assert "function openArticleWhatsAppShare" in html
    assert "wa.me/?text=" in html


def test_index_handles_incoming_share_by_saving_and_opening_saved_view():
    html = INDEX.read_text(encoding="utf-8")
    assert "function handleIncomingSharedArticle" in html
    assert "share/articles.json" in html
    assert "shared_article_open" in html
    assert "ידיעה משיתוף נשמרה אצלך" in html
