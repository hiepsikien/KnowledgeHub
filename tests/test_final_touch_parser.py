"""Final Touch parser, Bach matchers, block_id patches, translation inherit."""

from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.block_ids import assign_block_ids, block_prefix
from knowledgehub.edition.figures import bind_figure_src, figures_from_text, ingest_gutenberg_zip_images
from knowledgehub.edition.inline_spans import annotate_inline_spans
from knowledgehub.edition.overrides import apply_block_patches, merge_block_patches
from knowledgehub.edition.ref import build_read_edition
from knowledgehub.edition.ref_schema import validate_block
from knowledgehub.edition.serialize import blocks_to_markdown, reader_visible_blocks
from knowledgehub.translation.ref_chapters import inherit_translated_blocks, ref_blocks_for_translation

BACH = "bach--abdy_williams"


def _parse(text: str, *, work_id: str | None = BACH, chapter_id: str = "ch-001", title: str = ""):
    return build_read_edition(
        text,
        family="gutenberg",
        language="en",
        use_llm=False,
        work_id=work_id,
        chapter_id=chapter_id,
        chapter_title=title,
    )


def test_speaker_cues_not_headings():
    raw = (
        "ILLE.\n"
        '"I have heard him play."\n\n'
        "DER SUPERINTEND.\n"
        '"The organ was sadly out of tune."\n'
    )
    edition, _ = _parse(raw)
    assert not any(b["type"] == "heading" and "ILLE" in b.get("text", "") for b in edition["blocks"])
    assert not any(b["type"] == "heading" and "SUPERINTEND" in b.get("text", "") for b in edition["blocks"])
    speakers = {b.get("speaker") for b in edition["blocks"] if b["type"] == "dialogue"}
    assert "ILLE" in speakers
    assert any("SUPERINTEND" in (s or "") for s in speakers)


def test_bach_family_heading_not_speaker():
    raw = "THE BACH FAMILY.\n\nHilgenfeldt collected the names of the clan at some length here.\n"
    edition, _ = _parse(raw)
    assert any(b["type"] == "heading" and "BACH FAMILY" in b.get("text", "") for b in edition["blocks"])
    assert not any(b.get("speaker") == "THE BACH FAMILY" for b in edition["blocks"])


def test_wasserflussen_stays_in_paragraph():
    raw = (
        "He wrote a chorale prelude on “An Wasserflüssen Babylon”;[12] and a "
        "toccata on the same melody in the following year.\n"
    )
    edition, _ = _parse(raw)
    assert not any(b["type"] == "blockquote" for b in edition["blocks"])
    joined = " ".join(b.get("text", "") for b in edition["blocks"] if b["type"] == "paragraph")
    assert "Wasserflüssen" in joined
    assert "toccata" in joined


def test_wasserflussen_wrapped_quote_stays_in_paragraph():
    raw = (
        "He wrote a chorale prelude on “An Wasserflüssen Babylon”;[12] and a\n"
        "toccata on the same melody in the following year.\n"
    )
    edition, _ = _parse(raw)
    assert not any(b["type"] == "blockquote" for b in edition["blocks"])
    joined = " ".join(b.get("text", "") for b in edition["blocks"] if b["type"] == "paragraph")
    assert "Wasserflüssen" in joined
    assert "toccata" in joined
    assert joined.count("toccata") == 1


def test_gutenberg_tilde_is_strong_not_strike():
    spans = annotate_inline_spans("See ~Adlung~, _Musica mechanica_.")
    assert any(s.style == "strong" and "Adlung" in s.text for s in spans)
    assert any(s.style == "em" for s in spans)


def test_chapter_banner_suppressed_from_markdown():
    raw = "CHAPTER III\n\nBach went to Weimar for a longer stay than the last visit.\n"
    edition, _ = _parse(raw, title="CHAPTER III")
    banners = [b for b in edition["blocks"] if b.get("suppress_in_reader")]
    assert banners
    assert banners[0]["type"] == "heading"
    md = blocks_to_markdown(edition["blocks"])
    assert "Bach went to Weimar" in md
    assert not md.startswith("CHAPTER III")


def test_notes_carry_host_block_id():
    raw = (
        "CHAPTER I\n\n"
        "True, biologists are not agreed on what is gained.[5] More follows here.\n\n"
        "FOOTNOTES:\n\n"
        "[Footnote 5: Residual substances crust it over.]\n"
    )
    edition, _ = _parse(raw, title="CHAPTER I")
    notes = edition.get("notes") or []
    assert notes
    host = notes[0]
    assert host.get("host_text")
    assert "[5]" in host["host_text"]
    assert host.get("host_block_id")
    assert host["host_block_id"].startswith("ch-001:")


def test_block_ids_stable_prefix_and_collision_suffix():
    blocks = [
        {"type": "paragraph", "text": "Same opening words in both."},
        {"type": "paragraph", "text": "Same opening words in both, but a tail."},
    ]
    assign_block_ids(blocks, chapter_id="ch-002")
    assert blocks[0]["block_id"].startswith("ch-002:paragraph:")
    assert block_prefix("Same opening words in both.") == block_prefix(blocks[0]["text"])
    assert blocks[0]["block_id"] != blocks[1]["block_id"]
    twins = [
        {"type": "paragraph", "text": "Identical."},
        {"type": "paragraph", "text": "Identical."},
    ]
    assign_block_ids(twins, chapter_id="ch-002")
    assert twins[1]["block_id"].endswith("-2")


def test_arnold_italic_essay_title_stays_heading():
    raw = (
        "_THE FUNCTION OF CRITICISM AT THE PRESENT TIME_\n\n"
        "The essay proper begins with a connected paragraph about poetry and life in England.\n"
    )
    edition, _ = _parse(raw, work_id="arnold--essays_in_criticism")
    assert any(
        b["type"] == "heading" and "FUNCTION OF CRITICISM" in b.get("text", "")
        for b in edition["blocks"]
    )


def test_bastiat_italic_series_title_stays_heading():
    raw = (
        "_SOPHISMS OF PROTECTION FIRST SERIES_\n\n"
        "Political economy has a host of popular fallacies to answer in every age of debate.\n"
    )
    edition, _ = _parse(raw, work_id="bastiat--economic_sophisms")
    assert any(
        b["type"] == "heading" and "SOPHISMS OF PROTECTION" in b.get("text", "")
        for b in edition["blocks"]
    )


def test_letter_dedication_italic_stays_heading():
    raw = (
        "_To Mrs. Saville, England._\n\n"
        "You will rejoice to hear that no disaster has accompanied the commencement of an enterprise.\n"
    )
    edition, _ = _parse(raw, work_id="shelley--frankenstein")
    assert any(
        b["type"] == "heading" and "Saville" in b.get("text", "")
        for b in edition["blocks"]
    )


def test_sons_of_johann_not_heading():
    raw = (
        "THE BACH FAMILY\n\n"
        "Hilgenfeldt printed the tree as follows.\n\n"
        "_Sons of Johann (No. 4)._\n\n"
        "10. JOHANN NICOLAUS, 1653-1682.\n"
    )
    edition, _ = _parse(raw)
    sons = [b for b in edition["blocks"] if "Sons of Johann" in b.get("text", "")]
    assert sons
    assert sons[0]["type"] != "heading"
    assert sons[0].get("role") == "list_caption"


def test_caps_year_is_list_item_not_heading():
    raw = (
        "THE BACH FAMILY\n\n"
        "Hilgenfeldt collected these names.\n\n"
        "10. JOHANN NICOLAUS, 1653-1682.\n"
    )
    edition, _ = _parse(raw)
    assert not any(
        b["type"] == "heading" and "NICOLAUS" in b.get("text", "") for b in edition["blocks"]
    )
    items = [b for b in edition["blocks"] if b["type"] == "list_item"]
    assert any("NICOLAUS" in b.get("text", "") for b in items)


def test_genealogy_splits_two_numbers_on_one_line():
    raw = (
        "THE BACH FAMILY\n\n"
        "Hilgenfeldt gives the following list of the clan.\n\n"
        "8. JOHANN AMBROSIUS, 1645-1695. 9. JOHANN CHRISTOPH, 1645-1693.\n"
    )
    edition, _ = _parse(raw)
    items = [b for b in edition["blocks"] if b.get("role") == "genealogy"]
    assert len(items) >= 2
    assert any(b["text"].startswith("8.") for b in items)
    assert any(b["text"].startswith("9.") for b in items)
    assert not any("9." in b["text"] and b["text"].startswith("8.") for b in items)


def test_sidenote_hidden_and_stripped_from_body():
    raw = (
        "CHAPTER III\n\n"
        "[Sidenote: Weimar]\n\n"
        "Bach went to Weimar in the next year of his appointment.\n"
    )
    edition, _ = _parse(raw, title="CHAPTER III")
    asides = [b for b in edition["blocks"] if b.get("role") == "aside"]
    assert asides
    assert asides[0]["hidden"] is True
    assert asides[0]["text"] == "Weimar"
    body = " ".join(b.get("text", "") for b in edition["blocks"])
    assert "[Sidenote:" not in body
    md = edition["reading_markdown"]
    assert "[Sidenote:" not in md
    assert "Bach went to Weimar" in md


def test_chapter_synopsis_role():
    raw = (
        "CHAPTER III\n\n"
        "Early years at Weimar—the duke—the organ—Italian influence—return.\n\n"
        "The body of the chapter starts here with a long enough paragraph about Bach at court.\n"
    )
    edition, _ = _parse(raw, title="CHAPTER III")
    syn = [b for b in edition["blocks"] if b.get("role") == "synopsis"]
    assert syn
    assert syn[0]["type"] == "paragraph"
    assert "Weimar" in syn[0]["text"]


def test_synopsis_matcher_ignores_master_substring():
    raw = (
        "CHAPTER III\n\n"
        "Early years at Weimar—the duke—the organ—Italian influence—return.\n\n"
        "The body of the chapter starts here with a long enough paragraph about the court.\n"
    )
    edition, _ = _parse(raw, work_id="smith--masterpiece_essays", title="CHAPTER III")
    assert not any(b.get("role") == "synopsis" for b in edition["blocks"])


def test_illustration_becomes_figure_role():
    raw = (
        "A page of music follows. [Illustration: Autograph of a prelude] "
        "Then the prose continues at some length after the plate.\n"
    )
    edition, _ = _parse(raw)
    figs = [b for b in edition["blocks"] if b.get("role") == "figure"]
    assert figs
    assert "prelude" in figs[0]["text"]
    assert "[Illustration:" not in " ".join(b.get("text", "") for b in edition["blocks"])


def test_hidden_blocks_dropped_from_reader_payload():
    blocks = [
        {"type": "heading", "text": "CHAPTER III", "level": 1, "suppress_in_reader": True},
        {"type": "paragraph", "text": "Aside", "hidden": True, "role": "aside"},
        {"type": "paragraph", "text": "Visible body."},
    ]
    visible = reader_visible_blocks(blocks)
    assert [b["text"] for b in visible] == ["Visible body."]


def test_hide_patch_by_block_id_and_stale_after_mismatch():
    blocks = [
        {"type": "paragraph", "text": "Keep this sentence in view."},
        {"type": "paragraph", "text": "Hide the sidenote running header."},
    ]
    assign_block_ids(blocks, chapter_id="ch-001")
    target = blocks[1]["block_id"]
    patched, stale = apply_block_patches(blocks, [{"block_id": target, "action": "hide"}])
    assert patched[1]["hidden"] is True
    assert not stale
    _patched2, stale2 = apply_block_patches(
        patched, [{"block_id": "ch-001:paragraph:does-not-exist", "action": "hide"}]
    )
    assert stale2
    assert stale2[0]["stale"] is True


def test_stale_block_id_does_not_fall_back_to_index():
    """Chế bản always sends block_id + block_index. A type change after re-parse
    must report stale, not hide whatever now sits at that index."""
    blocks = [
        {"type": "list_item", "text": "JOHANN NICOLAUS, 1653-1682."},
        {"type": "paragraph", "text": "Keep this body paragraph visible."},
    ]
    assign_block_ids(blocks, chapter_id="ch-001")
    old_heading_id = "ch-001:heading:johann-nicolaus-1653-1682"
    patched, stale = apply_block_patches(
        blocks,
        [
            {
                "action": "hide",
                "block_id": old_heading_id,
                "block_index": 0,
            }
        ],
    )
    assert stale
    assert patched[0].get("hidden") is not True
    assert patched[1].get("hidden") is not True


def test_index_used_only_without_block_id():
    blocks = [
        {"type": "paragraph", "text": "Alpha block remains visible."},
        {"type": "paragraph", "text": "Beta block should hide."},
    ]
    assign_block_ids(blocks, chapter_id="ch-001")
    patched, stale = apply_block_patches(blocks, [{"block_index": 1, "action": "hide"}])
    assert not stale
    assert patched[1]["hidden"] is True
    assert patched[0].get("hidden") is not True


def test_split_then_hide_right_half_replays_on_reparse():
    blocks = [
        {"type": "paragraph", "text": "Left half. Right half stays."},
        {"type": "paragraph", "text": "Later sidenote to keep."},
    ]
    assign_block_ids(blocks, chapter_id="ch-001")
    original_id = blocks[0]["block_id"]
    at = blocks[0]["text"].index("Right")
    first, stale_split = apply_block_patches(
        blocks,
        [{"block_id": original_id, "block_index": 0, "action": "split", "at": at}],
    )
    assert not stale_split
    right_id = first[1]["block_id"]
    assert right_id
    replayed, stale = apply_block_patches(
        blocks,
        [
            {"block_id": original_id, "block_index": 0, "action": "split", "at": at},
            {"block_id": right_id, "block_index": 1, "action": "hide"},
        ],
    )
    assert not stale
    assert replayed[1]["hidden"] is True
    assert "Right half" in replayed[1]["text"]
    assert replayed[2].get("hidden") is not True


def test_split_and_merge_patches():
    blocks = [{"type": "paragraph", "text": "Left half. Right half stays."}]
    assign_block_ids(blocks, chapter_id="ch-001")
    at = blocks[0]["text"].index("Right")
    split, stale = apply_block_patches(blocks, [{"block_id": blocks[0]["block_id"], "action": "split", "at": at}])
    assert not stale
    assert len(split) == 2
    assert "Left half." in split[0]["text"]
    merged, stale_m = apply_block_patches(split, [{"block_id": split[0]["block_id"], "action": "merge_with_next"}])
    assert not stale_m
    assert len(merged) == 1
    assert "Right half" in merged[0]["text"]


def test_merge_block_patches_by_block_id():
    first = [{"block_id": "ch-001:paragraph:hello", "action": "hide"}]
    second = [{"block_id": "ch-001:paragraph:hello", "action": "show"}]
    merged = merge_block_patches(first, second)
    assert len(merged) == 1
    assert merged[0]["action"] == "show"


def test_set_text_is_lexical():
    blocks = [{"type": "paragraph", "text": "Original wording here."}]
    assign_block_ids(blocks, chapter_id="ch-001")
    patched, _ = apply_block_patches(
        blocks,
        [{"block_id": blocks[0]["block_id"], "action": "set_text", "text": "Curator rewrite."}],
    )
    assert patched[0]["text"] == "Curator rewrite."
    assert patched[0]["lexical"] is True


def test_json_editor_text_patch_is_lexical():
    blocks = [{"type": "paragraph", "text": "Original wording here."}]
    assign_block_ids(blocks, chapter_id="ch-001")
    patched, _ = apply_block_patches(
        blocks,
        [
            {
                "block_id": blocks[0]["block_id"],
                "block_index": 0,
                "type": "paragraph",
                "text": "Curator rewrite from JSON.",
            }
        ],
    )
    assert patched[0]["text"] == "Curator rewrite from JSON."
    assert patched[0]["lexical"] is True


def test_set_type_heading_defaults_level():
    blocks = [{"type": "paragraph", "text": "A section title that should be a heading."}]
    assign_block_ids(blocks, chapter_id="ch-001")
    patched, stale = apply_block_patches(
        blocks,
        [
            {
                "block_id": blocks[0]["block_id"],
                "block_index": 0,
                "action": "set_type",
                "type": "heading",
            }
        ],
    )
    assert not stale
    assert patched[0]["type"] == "heading"
    assert patched[0]["level"] == 2
    assert validate_block(patched[0], index=0) == []


def test_translation_inherit_keeps_hidden_skips_lexical():
    en = [
        {
            "block_id": "ch-001:paragraph:aside",
            "type": "paragraph",
            "role": "aside",
            "hidden": True,
            "text": "Weimar",
        },
        {
            "block_id": "ch-001:paragraph:body",
            "type": "paragraph",
            "text": "Bach went to Weimar.",
        },
        {
            "block_id": "ch-001:paragraph:rewrite",
            "type": "paragraph",
            "lexical": True,
            "text": "Curator English only.",
        },
    ]
    graph = inherit_translated_blocks(
        en,
        {
            "ch-001:paragraph:aside": "Viên-ma",
            "ch-001:paragraph:body": "Bach đến Weimar.",
            "ch-001:paragraph:rewrite": "Bản dịch không được dùng.",
        },
    )
    by_id = {b["block_id"]: b for b in graph}
    assert by_id["ch-001:paragraph:aside"]["hidden"] is True
    assert by_id["ch-001:paragraph:aside"]["text"] == "Viên-ma"
    assert by_id["ch-001:paragraph:body"]["text"] == "Bach đến Weimar."
    assert by_id["ch-001:paragraph:rewrite"]["text"] == "Curator English only."
    copied = ref_blocks_for_translation(en)
    assert copied[0]["hidden"] is True


def test_figures_from_footnote_body():
    figures = figures_from_text("[Illustration: Autograph of the prelude, 1722]")
    assert figures[0]["caption"].startswith("Autograph")


def test_ingest_zip_images(tmp_path: Path):
    import zipfile

    zip_path = tmp_path / "pg.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("images/cover.jpg", b"fake-jpeg")
        zf.writestr("pg43650.html", b"<html></html>")
    dest = tmp_path / "assets"
    copied = ingest_gutenberg_zip_images(zip_path, dest)
    assert copied
    assert (dest / "cover.jpg").is_file()


def test_bind_figure_src_matches_caption(tmp_path: Path):
    dest = tmp_path / "assets"
    dest.mkdir()
    (dest / "autograph.jpg").write_bytes(b"x")
    figures = figures_from_text("[Illustration: Autograph of the prelude]")
    bound = bind_figure_src(figures, dest, src_prefix="/assets/bach--abdy_williams")
    assert bound[0]["src"] == "/assets/bach--abdy_williams/autograph.jpg"
