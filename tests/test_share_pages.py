import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_generator(tmp_path: Path, feed: dict):
    tmp_path.mkdir(parents=True, exist_ok=True)
    feed_path = tmp_path / "feed.json"
    out_dir = tmp_path / "dist"
    feed_path.write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_share_pages.py"),
            "--feed",
            str(feed_path),
            "--out",
            str(out_dir),
            "--app-base",
            "https://example.com/poanta-demo/",
        ],
        check=True,
    )
    return out_dir


def test_generates_whatsapp_preview_page_and_article_manifest(tmp_path):
    feed = {
        "items": [
            {
                "source": "וואלה חדשות",
                "sourceUrl": "https://news.example/item/123?utm=abc",
                "originalTitle": "כותרת מקור",
                "headline": "כותרת פואנטה לשיתוף",
                "context": "זהו תקציר הידיעה שיופיע בתצוגה המקדימה של וואטסאפ.",
                "takeaway": "הפואנטה של הידיעה.",
                "category": "ביטחון",
                "imageUrl": "https://cdn.example/image.jpg",
                "publishedAt": "2026-05-27T10:00:00+03:00",
            }
        ]
    }

    out_dir = run_generator(tmp_path, feed)
    manifest = json.loads((out_dir / "share" / "articles.json").read_text(encoding="utf-8"))
    assert len(manifest["items"]) == 1
    article = manifest["items"][0]
    assert article["headline"] == "כותרת פואנטה לשיתוף"
    assert article["shareUrl"].startswith("https://example.com/poanta-demo/share/")

    page = (out_dir / "share" / article["shareId"] / "index.html").read_text(encoding="utf-8")
    assert '<meta property="og:title" content="כותרת פואנטה לשיתוף">' in page
    assert '<meta property="og:description" content="זהו תקציר הידיעה שיופיע בתצוגה המקדימה של וואטסאפ.">' in page
    assert '<meta property="og:image" content="https://cdn.example/image.jpg">' in page
    assert f"./../../app/?share={article['shareId']}&view=saved" in page


def test_share_ids_are_stable_for_same_source_url_without_tracking_params(tmp_path):
    base_item = {
        "source": "מקור",
        "sourceUrl": "https://example.com/article/42?utm_source=x#part",
        "headline": "כותרת",
        "context": "תקציר",
    }
    feed_a = {"items": [base_item]}
    feed_b = {"items": [{**base_item, "sourceUrl": "https://example.com/article/42?utm_source=y"}]}

    id_a = json.loads((run_generator(tmp_path / "a", feed_a) / "share" / "articles.json").read_text(encoding="utf-8"))["items"][0]["shareId"]
    id_b = json.loads((run_generator(tmp_path / "b", feed_b) / "share" / "articles.json").read_text(encoding="utf-8"))["items"][0]["shareId"]

    assert id_a == id_b


def test_rewrites_legacy_poenta_asset_host_for_whatsapp_preview(tmp_path):
    feed = {
        "items": [
            {
                "sourceUrl": "https://news.example/item/7",
                "headline": "כותרת",
                "context": "תקציר",
                "imageUrl": "https://poanta-demo.pages.dev/assets/poenta-image-bank/card.jpg",
            }
        ]
    }

    out_dir = run_generator(tmp_path, feed)
    article = json.loads((out_dir / "share" / "articles.json").read_text(encoding="utf-8"))["items"][0]
    page = (out_dir / "share" / article["shareId"] / "index.html").read_text(encoding="utf-8")
    expected = "https://example.com/assets/poenta-image-bank/card.jpg"
    assert f'<meta property="og:image" content="{expected}">' in page
    assert f'<meta property="og:image:secure_url" content="{expected}">' in page
