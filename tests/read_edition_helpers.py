"""Test helpers for two-step Read Edition bootstrap."""

from __future__ import annotations

from pathlib import Path

from knowledgehub.edition.read_edition_steps import (
    load_structure,
    package_root,
    parse_micro_chapter,
    resolve_stripped_source,
    run_macro_step,
)


def bootstrap_read_edition(
    work_id: str,
    *,
    corpus: Path,
    use_llm: bool = False,
    force: bool = False,
) -> None:
    """Run macro + micro parse on all sections so publish/tests can proceed."""
    run_macro_step(work_id, corpus=corpus, use_llm=use_llm, force=force)
    _text, meta, _work = resolve_stripped_source(work_id, corpus=corpus)
    package_dir = package_root(work_id, str(meta["content_hash"]), corpus=corpus)
    structure = load_structure(package_dir)
    if not structure:
        raise RuntimeError(f"macro step failed for {work_id}")
    for section in structure.get("sections") or []:
        parse_micro_chapter(work_id, section["section_id"], corpus=corpus, use_llm=use_llm)
