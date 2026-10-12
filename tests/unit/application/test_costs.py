from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from transcribl.application.costs import estimate_cost, recorded_cost
from transcribl.config import load_project_config
from transcribl.domain.costs import CostSettings, CostSummary, TokenPrice
from transcribl.domain.models import DocumentTranslation


def document(
    *,
    model: str = "gemini-3.8-flash",
    provider: str = "gemini",
    incoming: int | None = 1000,
    outgoing: int | None = 200,
    count: int = 1,
    table: bool = False,
    thinking: str = "default",
    day: int = 0,
) -> DocumentTranslation:
    run_id = uuid4().hex
    when = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=day)
    usage = {
        "provider": provider,
        "model": model,
        "prompt_version": "test",
        "input_tokens": incoming,
        "output_tokens": outgoing,
        "configuration": {"thinking_level": thinking},
    }
    pages = []
    for number in range(1, count + 1):
        block_id = f"p{number:04}-b0001"
        pages.append(
            {
                "translation_run_id": run_id,
                "original_page_number": number,
                "extraction_status": "extracted",
                "extracted_character_count": 1,
                "source_markdown": "X",
                "input_fingerprint": "a" * 64,
                "source_markdown_artifact": {
                    "path": "source.md",
                    "sha256": "a" * 64,
                    "media_type": "text/markdown",
                    "byte_count": 1,
                },
                "source_image": {
                    "path": "page.png",
                    "sha256": "b" * 64,
                    "media_type": "image/png",
                    "byte_count": 1,
                },
                "provider": usage,
                "translated_at": when,
                "blocks": [
                    {
                        "block_id": block_id,
                        "original_page_number": number,
                        "order": 1,
                        "type": "table",
                        "source_text": None,
                        "translated_text": "| A | B |\n|---|---|\n|1|2|",
                        "segment_handling": "table_reconstruction",
                        "manual_insertion_reason": "table",
                        "continuation": "complete",
                    }
                ]
                if table
                else [],
                "table_reconstruction": {
                    "input_fingerprint": "c" * 64,
                    "block_ids": [block_id],
                    "provider": usage,
                    "reconstructed_at": when,
                }
                if table
                else None,
            }
        )
    return DocumentTranslation.model_validate(
        {
            "translation_run_id": run_id,
            "document_id": "a" * 64,
            "job_id": "test-job",
            "source_file_name": "synthetic.pdf",
            "source_file_sha256": "a" * 64,
            "page_count": count,
            "translation_settings": {},
            "pages": pages,
            "created_at": when,
        }
    )


def settings() -> CostSettings:
    return load_project_config(Path("config/default.toml")).costs


def estimate(
    docs: list[DocumentTranslation],
    config: CostSettings | None = None,
    model: str = "gemini-3.8-flash",
    provider: str = "gemini",
) -> CostSummary:
    return estimate_cost(
        docs,
        config or settings(),
        model=model,
        provider=provider,
        thinking_level="default",
        page_count=10,
        today=date(2026, 10, 12),
    )


def test_both_passes_count_once_and_history_learns_from_new_runs() -> None:
    first = document(table=True)
    cost = recorded_cost(first, settings())
    assert cost.input_tokens == 2000
    assert cost.output_tokens == 400
    assert cost.total_usd == pytest.approx(0.003)
    assert any("thinking tokens" in note for note in cost.notes)
    assert CostSummary.model_validate_json(cost.model_dump_json()) == cost
    before = estimate([first, first])
    assert before.sample_pages == 1
    assert before.total_usd == pytest.approx(0.03)
    after = estimate([first, document(incoming=4000, outgoing=800)])
    assert after.sample_pages == 2
    assert after.total_usd == pytest.approx(0.045)
    assert after.input_tokens == 30000


def test_matching_model_and_thinking_take_priority_with_bounded_recent_history() -> None:
    config = settings().model_copy(update={"minimum_matching_pages": 2, "max_history_pages": 2})
    old = document(count=2, incoming=8000, day=0)
    recent = document(count=2, incoming=1000, day=1)
    other_thinking = document(count=4, incoming=9000, thinking="high", day=2)
    result = estimate([old, recent, other_thinking], config)
    assert result.sample_pages == 2
    assert result.basis == "same model and thinking level"
    assert result.total_usd == pytest.approx(0.015)
    assert estimate([other_thinking], config).basis == "same model"
    assert estimate([old], config, model="gpt-6-astra", provider="openai").basis == "all models"
    legacy = document(model="gemini-3.6-flash", count=2)
    assert estimate([legacy], config).basis == "same provider"
    assert recorded_cost(legacy, config).total_usd == pytest.approx(0.003)


def test_missing_tokens_prices_or_history_never_become_a_zero_cost() -> None:
    missing = document(incoming=None, table=True)
    assert recorded_cost(missing, settings()).total_usd is None
    assert estimate([missing]).total_usd is None
    assert estimate([]).total_usd is None
    assert recorded_cost(document(model="unknown"), settings()).total_usd is None
    free = document(incoming=0, outgoing=0)
    assert recorded_cost(free, settings()).total_usd == 0
    assert estimate([free]).total_usd == 0
    expired = estimate_cost(
        [free],
        settings(),
        model="gemini-3.8-flash",
        provider="gemini",
        thinking_level="default",
        page_count=2,
        today=date(2027, 1, 1),
    )
    assert expired.total_usd is None
    assert "expired" in expired.basis
    # Past runs remain costed at their recorded date, independent of today's date.
    assert recorded_cost(free, settings()).total_usd == 0


def test_long_context_tier_is_applied_per_request_including_tables() -> None:
    short = document(
        model="claude-haiku-5-5", provider="anthropic", incoming=100000, outgoing=1000, table=True
    )
    long = document(
        model="claude-haiku-5-5", provider="anthropic", incoming=100001, outgoing=1000, table=True
    )
    assert recorded_cost(short, settings()).total_usd == pytest.approx(0.021)
    assert recorded_cost(long, settings()).total_usd == pytest.approx(0.105001)
    assert estimate(
        [short], model="claude-haiku-5-5", provider="anthropic"
    ).total_usd == pytest.approx(0.21)


@pytest.mark.parametrize(
    "change",
    [
        {"input_usd_per_million": -1},
        {"output_usd_per_million": float("nan")},
        {"long_context_threshold": 100},
        {"unknown": True},
        {"valid_until": "2020-01-01"},
        {"source": "javascript:alert(1)"},
    ],
)
def test_price_config_is_strict(change: dict[str, object]) -> None:
    raw = settings().prices["gemini-3.8-flash"].model_dump()
    with pytest.raises(ValidationError):
        TokenPrice.model_validate({**raw, **change})
