"""Cost projections from canonical successful usage; never an invoice or cache input."""

from collections.abc import Iterable
from datetime import date

from transcribl.domain.costs import CostSettings, CostSummary, TokenPrice
from transcribl.domain.models import DocumentTranslation, PageTranslation, ProviderMetadata


def requests(page: PageTranslation) -> list[ProviderMetadata]:
    return [page.provider] + (
        [page.table_reconstruction.provider] if page.table_reconstruction is not None else []
    )


def complete_usage(page: PageTranslation) -> bool:
    return all(p.input_tokens is not None and p.output_tokens is not None for p in requests(page))


def request_cost(usage: ProviderMetadata, price: TokenPrice) -> float:
    assert usage.input_tokens is not None and usage.output_tokens is not None
    incoming, outgoing = price.input_usd_per_million, price.output_usd_per_million
    if (
        price.long_context_threshold is not None
        and usage.input_tokens > price.long_context_threshold
    ):
        assert price.long_input_usd_per_million is not None
        assert price.long_output_usd_per_million is not None
        incoming, outgoing = price.long_input_usd_per_million, price.long_output_usd_per_million
    return (usage.input_tokens * incoming + usage.output_tokens * outgoing) / 1_000_000


def _notes(pages: list[PageTranslation]) -> list[str]:
    notes = [
        "Approximate paid-tier cost; excludes unrecorded retries, caching discounts, "
        "free allowances and taxes."
    ]
    if any(
        p.provider == "gemini"
        and p.configuration.get("output_token_accounting") != "includes_reasoning"
        for page in pages
        for p in requests(page)
    ):
        notes.append("Older Gemini usage excludes thinking tokens; this may underestimate cost.")
    return notes


def recorded_cost(document: DocumentTranslation, settings: CostSettings) -> CostSummary:
    pages = document.pages
    result = CostSummary(
        kind="recorded",
        page_count=document.page_count,
        basis="Recorded successful translation and table requests",
        notes=_notes(pages),
    )
    total = 0.0
    missing = False
    for page in pages:
        for usage in requests(page):
            result.input_tokens += usage.input_tokens or 0
            result.output_tokens += usage.output_tokens or 0
            price = settings.prices.get(usage.model)
            if (
                price is None
                or price.provider != usage.provider
                or usage.input_tokens is None
                or usage.output_tokens is None
                or (price.valid_until and page.translated_at.date() > price.valid_until)
            ):
                missing = True
                continue
            total += request_cost(usage, price)
            result.pricing_checked_on.append(price.checked_on)
            result.sources.append(str(price.source))
            if price.note:
                result.notes.append(price.note)
    if missing:
        result.notes.append("Cost unavailable: some recorded usage or model pricing is missing.")
    else:
        result.total_usd = total
        result.per_page_usd = total / document.page_count
    result.pricing_checked_on = sorted(set(result.pricing_checked_on))
    result.sources = sorted(set(result.sources))
    result.notes = list(dict.fromkeys(result.notes))
    return result


def estimate_cost(
    documents: Iterable[DocumentTranslation],
    settings: CostSettings,
    *,
    model: str,
    provider: str,
    thinking_level: str,
    page_count: int,
    today: date | None = None,
) -> CostSummary:
    result = CostSummary(kind="estimate", page_count=page_count, basis="No completed usage yet")
    price = settings.prices.get(model)
    if (
        price is None
        or price.provider != provider
        or (price.valid_until and (today or date.today()) > price.valid_until)
    ):
        result.basis = "Model pricing is missing or expired"
        return result
    # Each immutable run/page is counted once; checkpoints and editorial copies never enter here.
    unique = {
        (d.translation_run_id, p.original_page_number): p
        for d in documents
        for p in d.pages
        if complete_usage(p)
    }
    pages = sorted(unique.values(), key=lambda p: p.translated_at, reverse=True)
    groups = [
        (
            "same model and thinking level",
            [
                p
                for p in pages
                if p.provider.model == model
                and p.provider.configuration.get("thinking_level", "default") == thinking_level
            ],
        ),
        ("same model", [p for p in pages if p.provider.model == model]),
        ("same provider", [p for p in pages if p.provider.provider == provider]),
        ("all models", pages),
    ]
    selected: list[PageTranslation] = []
    for basis, group in groups:
        if len(group) >= settings.minimum_matching_pages or basis == "all models":
            selected = group[: settings.max_history_pages]
            result.basis = basis
            break
    if not selected:
        result.basis = "No completed usage yet"
        return result
    size = len(selected)
    usages = [usage for page in selected for usage in requests(page)]
    result.sample_pages = size
    result.per_page_usd = sum(request_cost(u, price) for u in usages) / size
    result.total_usd = result.per_page_usd * page_count
    result.input_tokens = sum(u.input_tokens or 0 for u in usages) / size * page_count
    result.output_tokens = sum(u.output_tokens or 0 for u in usages) / size * page_count
    result.pricing_checked_on = [price.checked_on]
    result.sources = [str(price.source)]
    result.notes = _notes(selected)
    result.notes.append("Page density, language, image DPI, prompts and thinking can change usage.")
    if result.basis != "same model and thinking level":
        result.notes.append("Uses broader history until enough matching pages complete.")
    if price.note:
        result.notes.append(price.note)
    return result
