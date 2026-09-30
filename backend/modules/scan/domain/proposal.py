"""Every read page of a session into one proposal for the review screen.

Each page is first matched to the selected shift; pages of another shift stay out
unless the user includes them, and the bobines sheet is recognised but has no section
to fill yet (phase 2). The included pages of each fiche are merged into one, mapped,
and the draft is finished (lots completed and checked, a loss counted twice put aside).
"""
from __future__ import annotations

from typing import Callable, Collection, Sequence

from modules.scan.domain.attribution import Selection, attribute, header_of_page
from modules.scan.domain.conditionnement import map_conditionnement
from modules.scan.domain.draft import Draft, ProposalContext
from modules.scan.domain.fabrication import map_fabrication
from modules.scan.domain.merge import merge_pages
from modules.scan.domain.ocr_result import PageRead

_MAPPERS: dict[str, Callable[[PageRead, Draft], None]] = {
    "fabrication": map_fabrication,
    "conditionnement": map_conditionnement,
}
IMPORTABLE_FORMS = tuple(_MAPPERS)


def build_proposal(
    pages: Sequence[PageRead], ctx: ProposalContext, selection: Selection, include_pages: Collection[str]
) -> dict:
    summaries: dict[str, dict] = {}
    groups: dict[str, list[PageRead]] = {form: [] for form in _MAPPERS}
    for page in pages:
        attribution = attribute(header_of_page(page), selection)
        importable = page.form_type in _MAPPERS
        included = importable and (attribution.verdict != "other_shift" or page.page_id in include_pages)
        summaries[page.page_id] = {
            "form_type": page.form_type,
            "verdict": attribution.verdict,
            "reasons": list(attribution.reasons),
            "read": attribution.read,
            "importable": importable,
            "included": included,
        }
        if included:
            groups[page.form_type].append(page)
    draft = Draft(ctx)
    for form, mapper in _MAPPERS.items():
        if groups[form]:
            mapper(merge_pages(groups[form]), draft)
    draft.finish()
    return draft.to_json(summaries)
