from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.auth.models import ResourceMetadata
from app.ingestion.chunking import chunk_document, version_document
from app.ingestion.loaders import load_document
from scripts.demo import IDENTITIES, documents


def test_content_and_acl_changes_invalidate_chunk_ids():
    doc = version_document(documents()[0])
    assert chunk_document(doc) == chunk_document(version_document(doc))
    modified = version_document(doc.model_copy(update={"text": doc.text + " Changed."}))
    assert chunk_document(doc)[0].id != chunk_document(modified)[0].id
    private = version_document(
        doc.model_copy(
            update={
                "metadata": ResourceMetadata(
                    visibility="internal", allowed_departments=["actuarial"]
                )
            }
        )
    )
    assert private.version != doc.version


def test_reindex_replaces_old_vectors_and_graph(service):
    original = service.resolver.catalog.get("public_faq")
    old_key = f"{original.id}:{original.version}"
    service.ingestion.stage(original.model_copy(update={"text": original.text + " New wording."}))
    assert old_key not in service.resolver.allowed_scope(IDENTITIES["guest"])
    updated = service.ingestion.index(original.id)
    assert original.version != updated.version
    assert old_key not in service.ingestion.graph.rows
    assert all(c.resource_key != old_key for c, _ in service.ingestion.vectors.rows.values())


def test_partial_index_failure_stays_inactive(service, monkeypatch):
    def fail(*args):
        raise RuntimeError("graph unavailable")

    monkeypatch.setattr(service.ingestion.graph, "replace", fail)
    with pytest.raises(RuntimeError):
        service.ingestion.index("public_faq")
    assert service.resolver.catalog.get("public_faq") is None
    candidates, _ = service.retriever.retrieve("pricing", IDENTITIES["guest"])
    assert all(c.chunk.document_id != "public_faq" for c in candidates)


@pytest.mark.parametrize("filename", ["x.md", "x.txt"])
def test_text_loaders(filename):
    assert load_document(filename, b"hello") == "hello"


def test_pdf_loader_and_unsupported_formats():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Hello policy) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    assert "Hello policy" in load_document("policy.pdf", output.getvalue())
    with pytest.raises(ValueError):
        load_document("file.exe", b"anything")


def test_graph_fragment_has_domain_edges(service):
    fragments = [fragment for _, fragment in service.ingestion.graph.rows.values()]
    assert all(len(f.entities) >= 2 and f.edges for f in fragments)
    assert any(e.kind == "PRICED_BY" for f in fragments for e in f.edges)
