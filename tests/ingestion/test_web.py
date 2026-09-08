import pytest

from app.auth.models import ResourceMetadata
from app.ingestion.chunking import chunk_document, version_document
from app.ingestion.extractor import StructuredKnowledgeExtractor
from app.ingestion.web import MainContentParser, canonicalize_url, stable_document_id
from app.models import Document, SourceMetadata


def test_main_content_parser_keeps_sections_and_drops_navigation() -> None:
    parser = MainContentParser()
    parser.feed(
        """
        <html lang="en"><head><title>Health coverage | Sun Life</title>
        <meta name="description" content="Public health coverage information">
        <link rel="canonical" href="/en/products/health/"></head><body>
        <nav>Do not index navigation</nav><main>
        <h1>Health coverage</h1><p>Coverage helps with eligible medical costs.</p>
        <h2>Coverage limits</h2><p>Limits depend on the plan selected.</p>
        <table><tr><th>Benefit</th><th>Limit</th></tr><tr><td>Physio</td><td>$500</td></tr></table>
        </main><footer>Do not index footer</footer></body></html>
        """
    )
    page = parser.page("https://www.sunlife.com/en/products/health/?campaign=1", "2026-01-01")
    assert page is not None
    assert page.canonical_url == "https://www.sunlife.com/en/products/health/"
    assert page.language == "en"
    assert "Do not index" not in page.text
    assert "# Health coverage" in page.text
    assert "## Coverage limits" in page.text
    assert "Physio | $500" in page.text


def test_web_chunking_is_section_aware_and_stable_across_crawl_times() -> None:
    source = SourceMetadata(
        source_type="web",
        source_url="https://www.sunlife.com/en/products/health/",
        canonical_url="https://www.sunlife.com/en/products/health/",
        crawled_at="2026-01-01T00:00:00Z",
        content_hash="abc",
    )
    document = Document(
        id=stable_document_id(source.canonical_url or ""),
        title="Health coverage",
        text="# Health coverage\n\nGeneral description.\n\n## Coverage limits\n\nLimits apply.",
        metadata=ResourceMetadata(visibility="public"),
        source_metadata=source,
    )
    first = version_document(document)
    second = version_document(
        document.model_copy(
            update={
                "source_metadata": source.model_copy(update={"crawled_at": "2026-01-02T00:00:00Z"})
            }
        )
    )
    assert first.version == second.version
    chunks = chunk_document(first)
    assert [chunk.source_metadata.heading_path for chunk in chunks] == [
        ["Health coverage"],
        ["Health coverage", "Coverage limits"],
    ]
    assert chunks == chunk_document(first)


def test_canonical_url_and_noindex() -> None:
    assert canonicalize_url("HTTPS://WWW.SUNLIFE.COM/en/?tracking=1#top") == (
        "https://www.sunlife.com/en/"
    )
    parser = MainContentParser()
    parser.feed(
        '<meta name="robots" content="noindex"><title>Hidden</title><p>' + "text " * 50 + "</p>"
    )
    assert parser.page("https://www.sunlife.com/en/hidden/", None) is None


def test_source_provenance_rejects_non_http_url() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        SourceMetadata(source_type="web", source_url="javascript:alert(1)")


def test_web_document_creates_page_and_topic_graph_fragment() -> None:
    document = Document(
        id="sunlife_page",
        title="Health coverage",
        text="# Health coverage\n\nDescription\n\n## Coverage limits\n\nLimits apply.",
        metadata=ResourceMetadata(visibility="public"),
        source_metadata=SourceMetadata(
            source_type="web", source_url="https://www.sunlife.com/en/health/"
        ),
    )
    fragment = StructuredKnowledgeExtractor().extract(document)
    assert {(entity.kind, entity.name) for entity in fragment.entities} >= {
        ("WebPage", "Health coverage"),
        ("Topic", "Health coverage"),
        ("Topic", "Health coverage / Coverage limits"),
    }
    assert {edge.kind for edge in fragment.edges} == {"DESCRIBES"}
