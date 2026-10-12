from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr

from transcribl.adapters.secrets import DotenvSecretStore
from transcribl.application.jobs.manager import JobManager
from transcribl.application.jobs.records import (
    JobNotFoundError,
    JobSnapshot,
    LocalJobStatus,
    ReviewSnapshot,
)
from transcribl.config import ProjectConfig, load_project_config
from transcribl.interfaces.web import create_app


def test_settings_are_persistent_validated_and_snapshotted_per_job(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()

    def client_for_app() -> TestClient:
        return TestClient(create_app(config, job_manager=cast(JobManager, manager)))

    with client_for_app() as client:
        client.get("/session")
        headers = {"X-CSRF-Token": client.cookies["at_csrf"]}
        public = client.get("/api/config").json()
        values = public["preferences"]["values"]
        assert values["default_glossary"] == "none"
        glossary = client.post(
            "/api/glossaries",
            json={
                "name": "Medical",
                "entries": [{"source_term": "Vattersot", "target_translation": "Dropsy"}],
            },
            headers=headers,
        ).json()
        values.update(
            default_model="claude-haiku-5-5",
            default_style="Research",
            default_glossary=glossary["glossary_id"],
        )
        values["style_prompts"]["Research"] = "Preserve historical terminology and register."
        values["thinking_levels"]["anthropic"] = "high"
        command = {"values": values, "expected_revision": 0}
        assert client.put("/api/settings", json=command).status_code == 403
        response = client.put("/api/settings", json=command, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert client.put("/api/settings", json=command, headers=headers).status_code == 409
        for field, invalid in (
            ("default_model", "gemini-3.5-flash"),
            ("default_style", "absent"),
            ("default_glossary", "../../file"),
        ):
            assert (
                client.put(
                    "/api/settings",
                    json={"values": {**values, field: invalid}, "expected_revision": 1},
                    headers=headers,
                ).status_code
                == 422
            )
        assert (
            client.post(
                "/api/jobs",
                files={"pdf": ("test.pdf", b"%PDF-1.7", "application/pdf")},
                headers=headers,
            ).status_code
            == 202
        )
        first = manager.submissions[-1][4]
        assert first.provider.name == "anthropic"
        assert first.provider.anthropic.model == "claude-haiku-5-5"
        assert first.provider.anthropic.thinking_level == "high"
        assert first.translation.style_prompt == values["style_prompts"]["Research"]
        assert first.translation.style_name == "Research"
        assert manager.submissions[-1][2] == {"Vattersot": "Dropsy"}
        values["style_prompts"]["Research"] = "Use modern terminology."
        assert (
            client.put(
                "/api/settings", json={"values": values, "expected_revision": 1}, headers=headers
            ).status_code
            == 200
        )
        assert first.translation.style_prompt == "Preserve historical terminology and register."
    with client_for_app() as restarted:
        public = restarted.get("/api/config").json()
        assert public["preferences"]["revision"] == 2
        assert public["preferences"]["values"] == values
        assert public["translation"]["style_prompt"] == "Use modern terminology."
        assert "style_prompt" in public["prompts"]["translation"]
        assert "style_prompt" in public["prompts"]["table"]


class RecordingJobManager:
    def __init__(self) -> None:
        self.submissions: list[
            tuple[
                bytes,
                str,
                dict[str, str],
                Path,
                ProjectConfig,
                SecretStr | None,
                bool,
            ]
        ] = []
        self.snapshot = JobSnapshot(
            job_id="a" * 32,
            status=LocalJobStatus.QUEUED,
            filename="article.pdf",
            current_page=0,
            total_pages=None,
            error=None,
            translation_run_id=None,
        )
        self.deleted_reviews: list[str] = []
        self.continued_keys: list[SecretStr | None] = []
        self.cancelled_jobs: list[str] = []
        self.recoverable_snapshot = JobSnapshot(
            job_id="c" * 32,
            status=LocalJobStatus.FAILED,
            filename="stopped.pdf",
            current_page=53,
            total_pages=95,
            error="Page 53: stopped",
            translation_run_id="c" * 32,
        )

    def submit(
        self,
        *,
        upload_path: Path,
        display_filename: str,
        glossary: dict[str, str],
        runtime_config: ProjectConfig,
        api_key: SecretStr | None,
        auto_continue: bool,
    ) -> JobSnapshot:
        self.submissions.append(
            (
                upload_path.read_bytes(),
                display_filename,
                glossary,
                upload_path,
                runtime_config,
                api_key,
                auto_continue,
            )
        )
        shutil.rmtree(upload_path.parent)
        return self.snapshot

    def get(self, job_id: str) -> JobSnapshot:
        if job_id != self.snapshot.job_id:
            raise JobNotFoundError("Translation job was not found")
        return self.snapshot

    def list_reviews(self) -> list[ReviewSnapshot]:
        return [
            ReviewSnapshot(
                job_id="b" * 32,
                status=LocalJobStatus.READY,
                filename="completed.pdf",
                page_count=95,
                continue_page=42,
                accepted_blocks=80,
                total_blocks=100,
                review_complete=False,
                translation_run_id="b" * 32,
                updated_at=datetime(2026, 8, 4, 12, tzinfo=UTC),
            )
        ]

    def list_recoverable_jobs(self) -> list[JobSnapshot]:
        return [self.recoverable_snapshot]

    def continue_job(
        self,
        job_id: str,
        *,
        api_key: SecretStr | None = None,
    ) -> JobSnapshot:
        if job_id != self.recoverable_snapshot.job_id:
            raise JobNotFoundError("Translation job was not found")
        self.continued_keys.append(api_key)
        return replace(
            self.recoverable_snapshot,
            status=LocalJobStatus.QUEUED,
            error=None,
        )

    def cancel_job(self, job_id: str) -> JobSnapshot:
        if job_id != self.recoverable_snapshot.job_id:
            raise JobNotFoundError("Translation job was not found")
        self.cancelled_jobs.append(job_id)
        return replace(
            self.recoverable_snapshot,
            status=LocalJobStatus.CANCELLED,
            error="Translation paused. Completed page checkpoints were kept.",
        )

    def delete_review(self, translation_run_id: str) -> None:
        if translation_run_id != "b" * 32:
            raise JobNotFoundError("Translation job was not found")
        self.deleted_reviews.append(translation_run_id)

    def shutdown(self) -> None:
        return None


def configured_for_tmp(tmp_path: Path) -> ProjectConfig:
    config = load_project_config(Path("config/default.toml"))
    return config.model_copy(
        update={"paths": config.paths.model_copy(update={"artifacts_dir": tmp_path / "artifacts"})}
    )


def test_index_and_public_config_never_expose_secret(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        index = client.get("/")
        public_config = client.get("/api/config")

    assert index.status_code == 200
    assert app.title == "Transcribl"
    assert index.json() == {"application": "Transcribl"}
    assert "at_csrf" in index.cookies
    assert index.headers["cache-control"] == "no-store"
    assert public_config.status_code == 200
    payload_text = public_config.text
    assert "GEMINI_API_KEY" not in payload_text
    assert "gemini_api_key" not in payload_text
    payload = public_config.json()
    assert payload["translation"]["source_language"] == "Danish"
    assert payload["translation"]["target_language"] == "English"
    assert payload["translation"]["footnote_appearance_instructions"] is None
    assert payload["translation"]["mark_uncertain_terms"] is True
    assert payload["translation"]["uncertainty_level"] == "standard"
    assert payload["translation"]["uncertainty_instructions"] is None
    assert payload["uncertainty"]["level_choices"] == [
        "off",
        "low",
        "standard",
        "high",
    ]
    assert payload["provider"]["model"] == "gemini-3.8-flash"
    assert payload["extraction"]["image_dpi"] == 150
    assert payload["automation"] == {
        "auto_continue_default": False,
        "auto_continue_attempts": 1,
    }
    assert payload["review"] == {
        "zoom_levels": [100, 125, 150, 175, 200],
        "zoom_default_percent": 100,
    }
    assert "gemini-3.5-flash-lite" not in payload["provider"]["selectable_models"]
    assert "review_context_pages" not in payload["limits"]
    assert payload["limits"]["max_instruction_characters"] == 4_000


def test_blank_environment_key_does_not_prevent_settings_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(
        config,
        job_manager=cast(JobManager, manager),
        secret_store=DotenvSecretStore(tmp_path / ".env"),
    )

    with TestClient(app) as client:
        response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["api_key_configured"] is False


def test_review_catalog_returns_stable_completed_runs(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        response = client.get("/api/jobs")

    assert response.status_code == 200
    assert response.json() == {
        "jobs": [
            {
                "job_id": "b" * 32,
                "status": "ready",
                "filename": "completed.pdf",
                "page_count": 95,
                "continue_page": 42,
                "accepted_blocks": 80,
                "total_blocks": 100,
                "review_complete": False,
                "translation_run_id": "b" * 32,
                "updated_at": "2026-08-04T12:00:00Z",
                "cost": None,
            }
        ]
    }


def test_failed_job_commands_require_csrf_and_never_return_api_key(
    tmp_path: Path,
) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))
    run_id = manager.recoverable_snapshot.job_id

    with TestClient(app) as client:
        recoverable = client.get("/api/jobs/recoverable")
        rejected = client.post(
            f"/api/jobs/{run_id}/continue",
            json={"api_key": "temporary-key"},
        )
        client.get("/")
        token = client.cookies["at_csrf"]
        continued = client.post(
            f"/api/jobs/{run_id}/continue",
            json={"api_key": "temporary-key"},
            headers={"X-CSRF-Token": token},
        )
        cancelled = client.post(
            f"/api/jobs/{run_id}/cancel",
            headers={"X-CSRF-Token": token},
        )

    assert recoverable.status_code == 200
    assert recoverable.json()["jobs"][0]["current_page"] == 53
    assert rejected.status_code == 403
    assert continued.status_code == 202
    assert "temporary-key" not in continued.text
    assert manager.continued_keys[0] is not None
    assert manager.continued_keys[0].get_secret_value() == "temporary-key"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert manager.cancelled_jobs == [run_id]


def test_article_delete_requires_csrf_and_calls_manager(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))
    run_id = "b" * 32

    with TestClient(app) as client:
        rejected = client.delete(f"/api/jobs/{run_id}")
        client.get("/")
        deleted = client.delete(
            f"/api/jobs/{run_id}",
            headers={"X-CSRF-Token": client.cookies["at_csrf"]},
        )

    assert rejected.status_code == 403
    assert deleted.status_code == 204
    assert manager.deleted_reviews == [run_id]


def test_upload_requires_csrf_and_confines_hostile_filename(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))
    file_payload = b"%PDF-1.7\nsynthetic"
    glossary = '[{"source_term":"Vattersot","target_translation":"Dropsy"}]'

    with TestClient(app) as client:
        rejected = client.post(
            "/api/jobs",
            files={"pdf": ("../../article.pdf", file_payload, "application/pdf")},
            data={"glossary": glossary},
        )
        client.get("/")
        token = client.cookies["at_csrf"]
        accepted = client.post(
            "/api/jobs",
            files={"pdf": ("../../article.pdf", file_payload, "text/plain")},
            data={"glossary": glossary},
            headers={"X-CSRF-Token": token},
        )

    assert rejected.status_code == 403
    assert accepted.status_code == 202
    assert manager.submissions[0][:3] == (
        file_payload,
        "article.pdf",
        {"Vattersot": "Dropsy"},
    )
    staged_path = manager.submissions[0][3]
    runtime_config = manager.submissions[0][4]
    assert runtime_config.translation.source_language == "Danish"
    assert runtime_config.translation.target_language == "English"
    assert manager.submissions[0][5] is None
    assert manager.submissions[0][6] is False
    assert staged_path.parent.parent == config.paths.artifacts_dir / ".uploads"
    assert not staged_path.exists()


def test_invalid_pdf_and_duplicate_glossary_fail_before_submission(
    tmp_path: Path,
) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        client.get("/")
        token = client.cookies["at_csrf"]
        invalid_pdf = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"plain text", "application/pdf")},
            data={"glossary": "[]"},
            headers={"X-CSRF-Token": token},
        )
        duplicate_glossary = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"%PDF-1.7", "application/pdf")},
            data={
                "glossary": (
                    '[{"source_term":"Term","target_translation":"First"},'
                    '{"source_term":" term ","target_translation":"Second"}]'
                )
            },
            headers={"X-CSRF-Token": token},
        )

    assert invalid_pdf.status_code == 415
    assert duplicate_glossary.status_code == 422
    assert manager.submissions == []
    uploads = config.paths.artifacts_dir / ".uploads"
    assert not uploads.exists() or not list(uploads.iterdir())


def test_job_uses_selected_languages_model_style_and_session_key(
    tmp_path: Path,
) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))
    settings = {
        "model": "gemini-3.8-flash",
        "source_language": "Latin",
        "target_language": "German",
        "style": "faithful",
        "footnote_appearance_instructions": "Tiny notes below a rule.",
        "uncertainty_level": "high",
        "uncertainty_instructions": "Mark all medical terms.",
        "previous_page_context_count": 4,
        "image_dpi": 225,
        "auto_continue": True,
    }

    with TestClient(app) as client:
        client.get("/")
        token = client.cookies["at_csrf"]
        response = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"%PDF-1.7", "application/pdf")},
            data={
                "glossary": "[]",
                "settings": json.dumps(settings),
                "gemini_api_key": "temporary_key_123",
            },
            headers={"X-CSRF-Token": token},
        )

    assert response.status_code == 202
    assert "temporary_key_123" not in response.text
    runtime_config = manager.submissions[0][4]
    assert runtime_config.provider.gemini.model == "gemini-3.8-flash"
    assert runtime_config.translation.source_language == "Latin"
    assert runtime_config.translation.target_language == "German"
    assert runtime_config.translation.style.value == "faithful"
    assert runtime_config.translation.footnote_appearance_instructions == "Tiny notes below a rule."
    assert runtime_config.translation.mark_uncertain_terms is True
    assert runtime_config.translation.uncertainty_level.value == "high"
    assert runtime_config.translation.uncertainty_instructions == "Mark all medical terms."
    assert runtime_config.translation.previous_page_context_count == 4
    assert runtime_config.extraction.image_dpi == 225
    submitted_secret = manager.submissions[0][5]
    assert submitted_secret is not None
    assert submitted_secret.get_secret_value() == "temporary_key_123"
    assert manager.submissions[0][6] is True


def test_job_rejects_model_outside_config_allowlist(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        client.get("/")
        token = client.cookies["at_csrf"]
        response = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"%PDF-1.7", "application/pdf")},
            data={
                "glossary": "[]",
                "settings": json.dumps(
                    {
                        "model": "unconfigured-model",
                        "source_language": "Danish",
                        "target_language": "English",
                        "style": "balanced",
                        "previous_page_context_count": 2,
                        "image_dpi": 150,
                        "auto_continue": False,
                    }
                ),
            },
            headers={"X-CSRF-Token": token},
        )

    assert response.status_code == 422
    assert manager.submissions == []
    assert not config.paths.artifacts_dir.exists()


def test_job_maps_uncertainty_off_to_legacy_flag_and_keeps_configured_level(
    tmp_path: Path,
) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))
    settings = {
        "model": config.provider.gemini.model,
        "source_language": "Danish",
        "target_language": "English",
        "style": "balanced",
        "uncertainty_level": "off",
        "uncertainty_instructions": "  Mark all numbers.  ",
        "previous_page_context_count": 2,
        "image_dpi": 150,
        "auto_continue": False,
    }

    with TestClient(app) as client:
        client.get("/")
        response = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"%PDF-1.7", "application/pdf")},
            data={"glossary": "[]", "settings": json.dumps(settings)},
            headers={"X-CSRF-Token": client.cookies["at_csrf"]},
        )

    assert response.status_code == 202
    runtime_config = manager.submissions[0][4]
    assert runtime_config.translation.mark_uncertain_terms is False
    assert runtime_config.translation.uncertainty_level.value == "standard"
    assert runtime_config.translation.uncertainty_instructions == "Mark all numbers."


def test_job_rejects_uncertainty_level_outside_configured_choices(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    config = config.model_copy(
        update={
            "web": config.web.model_copy(
                update={"uncertainty_level_choices": ["off", "low", "standard"]}
            )
        }
    )
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        client.get("/")
        response = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"%PDF-1.7", "application/pdf")},
            data={
                "glossary": "[]",
                "settings": json.dumps(
                    {
                        "model": config.provider.gemini.model,
                        "source_language": "Danish",
                        "target_language": "English",
                        "style": "balanced",
                        "uncertainty_level": "high",
                        "previous_page_context_count": 2,
                        "image_dpi": 150,
                        "auto_continue": False,
                    }
                ),
            },
            headers={"X-CSRF-Token": client.cookies["at_csrf"]},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Select an uncertainty level allowed by the project configuration"
    )
    assert manager.submissions == []


def test_job_rejects_footnote_guidance_above_configured_limit(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    config = config.model_copy(
        update={"web": config.web.model_copy(update={"max_instruction_characters": 10})}
    )
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        client.get("/")
        response = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"%PDF-1.7", "application/pdf")},
            data={
                "glossary": "[]",
                "settings": json.dumps(
                    {
                        "model": config.provider.gemini.model,
                        "source_language": "Danish",
                        "target_language": "English",
                        "style": "balanced",
                        "footnote_appearance_instructions": "x" * 11,
                        "previous_page_context_count": 2,
                        "image_dpi": 150,
                        "auto_continue": False,
                    }
                ),
            },
            headers={"X-CSRF-Token": client.cookies["at_csrf"]},
        )

    assert response.status_code == 422
    assert manager.submissions == []


def test_job_rejects_uncertainty_instructions_above_configured_limit(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    config = config.model_copy(
        update={"web": config.web.model_copy(update={"max_instruction_characters": 10})}
    )
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        client.get("/")
        response = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"%PDF-1.7", "application/pdf")},
            data={
                "glossary": "[]",
                "settings": json.dumps(
                    {
                        "model": config.provider.gemini.model,
                        "source_language": "Danish",
                        "target_language": "English",
                        "style": "balanced",
                        "uncertainty_level": "standard",
                        "uncertainty_instructions": "Mark every number",
                        "previous_page_context_count": 2,
                        "image_dpi": 150,
                        "auto_continue": False,
                    }
                ),
            },
            headers={"X-CSRF-Token": client.cookies["at_csrf"]},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Uncertainty instructions exceed the configured character limit"
    )
    assert manager.submissions == []


@pytest.mark.parametrize(
    ("previous_page_context_count", "image_dpi"),
    [(11, 150), (2, 601)],
)
def test_job_rejects_out_of_range_context_and_render_settings(
    tmp_path: Path,
    previous_page_context_count: int,
    image_dpi: int,
) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        client.get("/")
        response = client.post(
            "/api/jobs",
            files={"pdf": ("article.pdf", b"%PDF-1.7", "application/pdf")},
            data={
                "glossary": "[]",
                "settings": json.dumps(
                    {
                        "model": config.provider.gemini.model,
                        "source_language": "Danish",
                        "target_language": "English",
                        "style": "balanced",
                        "previous_page_context_count": previous_page_context_count,
                        "image_dpi": image_dpi,
                        "auto_continue": False,
                    }
                ),
            },
            headers={"X-CSRF-Token": client.cookies["at_csrf"]},
        )

    assert response.status_code == 422
    assert manager.submissions == []


def test_settings_can_keep_key_for_session_or_save_and_clear_it_locally(
    tmp_path: Path,
) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("# colleague settings\nOTHER=preserved\n", encoding="utf-8")
    store = DotenvSecretStore(dotenv_path)
    app = create_app(
        config,
        job_manager=cast(JobManager, manager),
        secret_store=store,
    )

    with TestClient(app) as client:
        client.get("/")
        token = client.cookies["at_csrf"]
        invalid = client.post(
            "/api/settings/api-key",
            json={
                "api_key": "must-not-leak\ninjected",
                "save_on_computer": True,
            },
            headers={"X-CSRF-Token": token},
        )
        session_only = client.post(
            "/api/settings/api-key",
            json={
                "api_key": "session_key_123",
                "save_on_computer": False,
            },
            headers={"X-CSRF-Token": token},
        )
        session_only_content = dotenv_path.read_text(encoding="utf-8")
        saved = client.post(
            "/api/settings/api-key",
            json={
                "api_key": "saved_key_456",
                "save_on_computer": True,
            },
            headers={"X-CSRF-Token": token},
        )
        saved_content = dotenv_path.read_text(encoding="utf-8")
        cleared = client.delete(
            "/api/settings/api-key",
            headers={"X-CSRF-Token": token},
        )

    assert invalid.status_code == 422
    assert "must-not-leak" not in invalid.text
    assert session_only.status_code == 200
    assert "session_key_123" not in session_only.text
    assert session_only_content == "# colleague settings\nOTHER=preserved\n"
    assert saved.status_code == 200
    assert "saved_key_456" not in saved.text
    assert saved.json()["saved_on_computer"] is True
    assert saved_content == (
        "# colleague settings\nOTHER=preserved\nGEMINI_API_KEY='saved_key_456'\n"
    )
    assert cleared.status_code == 200
    assert cleared.json()["saved_on_computer"] is False
    assert dotenv_path.read_text(encoding="utf-8") == ("# colleague settings\nOTHER=preserved\n")


def test_unknown_job_does_not_create_artifact_directory(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))

    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{'b' * 32}")

    assert response.status_code == 404
    assert not config.paths.artifacts_dir.exists()


@pytest.mark.parametrize(
    "provider,model", [("openai", "gpt-6-astra"), ("anthropic", "claude-opus-5-5")]
)
def test_new_provider_job_and_saved_key_are_isolated(
    tmp_path: Path, provider: str, model: str
) -> None:
    config = configured_for_tmp(tmp_path)
    manager = RecordingJobManager()
    store = DotenvSecretStore(tmp_path / ".env")
    app = create_app(config, job_manager=cast(JobManager, manager), secret_store=store)
    with TestClient(app) as client:
        client.get("/")
        headers = {"X-CSRF-Token": client.cookies["at_csrf"]}
        command = {"provider": provider, "api_key": "private-test-key", "save_on_computer": True}
        assert client.post("/api/settings/api-key", json=command).status_code == 403
        saved = client.post("/api/settings/api-key", json=command, headers=headers)
        assert saved.status_code == 200 and saved.json()["saved_on_computer"]
        public = client.get("/api/config")
        assert "private-test-key" not in public.text
        assert public.json()["api_keys"][provider]["saved_on_computer"]
        assert not public.json()["api_keys"]["gemini"]["saved_on_computer"]
        settings = {
            "model": model,
            "source_language": "Old Danish",
            "target_language": "English",
            "style": "balanced",
            "previous_page_context_count": 2,
            "image_dpi": 150,
            "auto_continue": False,
        }
        response = client.post(
            "/api/jobs",
            headers=headers,
            files={"pdf": ("test.pdf", b"%PDF-1.7", "application/pdf")},
            data={"settings": json.dumps(settings), "api_key": "session-test-key"},
        )
        assert response.status_code == 202
        runtime = manager.submissions[-1][4]
        assert runtime.provider.name == provider and runtime.provider.selected.model == model
        assert runtime.translation.source_language == "Old Danish"
        assert "session-test-key" not in response.text
        invalid = client.delete("/api/settings/api-key?provider=unknown", headers=headers)
        assert invalid.status_code == 422
        cleared = client.delete(f"/api/settings/api-key?provider={provider}", headers=headers)
        assert not cleared.json()["saved_on_computer"]


def test_glossary_routes_persist_selection_and_protect_mutations(tmp_path: Path) -> None:
    config = configured_for_tmp(tmp_path)
    config = config.model_copy(
        update={
            "translation": config.translation.model_copy(
                update={"glossary": {"Baseline": "Default"}}
            )
        }
    )
    manager = RecordingJobManager()

    def app_client() -> TestClient:
        return TestClient(create_app(config, job_manager=cast(JobManager, manager)))

    with app_client() as client:
        client.get("/session")
        headers = {"X-CSRF-Token": client.cookies["at_csrf"]}
        command = {
            "name": "Historical",
            "entries": [{"source_term": "Vattersot", "target_translation": "Dropsy"}],
        }
        assert client.post("/api/glossaries", json=command).status_code == 403
        created = client.post("/api/glossaries", json=command, headers=headers)
        assert created.status_code == 201
        saved = created.json()
        url = f"/api/glossaries/{saved['glossary_id']}"
        assert "path" not in saved
        assert created.headers["Cache-Control"] == "no-store"
        assert client.put(url, json={**command, "expected_revision": 1}).status_code == 403
        assert client.delete(url + "?expected_revision=1").status_code == 403
        assert client.put(url, json=command, headers=headers).status_code == 422

        def submit(data: dict[str, str]) -> Response:
            return client.post(
                "/api/jobs",
                files={"pdf": ("test.pdf", b"%PDF-1.7", "application/pdf")},
                data=data,
                headers=headers,
            )

        response = submit({"glossary_id": saved["glossary_id"], "glossary_revision": "1"})
        assert response.status_code == 202
        assert manager.submissions[-1][2] == {"Vattersot": "Dropsy"}
        assert manager.submissions[-1][4].translation.glossary == {}
        assert submit({"glossary_id": "none"}).status_code == 202
        assert (
            manager.submissions[-1][2] == {}
            and manager.submissions[-1][4].translation.glossary == {}
        )
        assert submit({}).status_code == 202
        assert manager.submissions[-1][4].translation.glossary == {}
        assert submit({"glossary_id": "configured"}).status_code == 202
        assert manager.submissions[-1][4].translation.glossary == {"Baseline": "Default"}
        changed = {
            "name": "Modern",
            "entries": [{"source_term": "Vattersot", "target_translation": "Edema"}],
            "expected_revision": 1,
        }
        updated = client.put(url, json=changed, headers=headers)
        assert updated.status_code == 200 and updated.json()["revision"] == 2
        assert client.put(url, json=changed, headers=headers).status_code == 409
        assert (
            submit({"glossary_id": saved["glossary_id"], "glossary_revision": "1"}).status_code
            == 409
        )
        assert submit({"glossary_id": saved["glossary_id"]}).status_code == 422
        assert (
            submit({"glossary_id": "none", "glossary": json.dumps(command["entries"])}).status_code
            == 422
        )
        assert submit({"glossary_id": "../outside", "glossary_revision": "1"}).status_code == 404
        assert len(manager.submissions) == 4
        assert manager.submissions[0][2] == {"Vattersot": "Dropsy"}
    with app_client() as restarted:
        restarted.get("/")
        headers = {"X-CSRF-Token": restarted.cookies["at_csrf"]}
        assert restarted.get("/api/glossaries").json()["glossaries"][0]["name"] == "Modern"
        assert restarted.delete(url + "?expected_revision=1", headers=headers).status_code == 409
        assert restarted.delete(url + "?expected_revision=2", headers=headers).status_code == 204
        assert restarted.get("/api/glossaries").json() == {"glossaries": []}


@pytest.mark.parametrize(
    "command",
    [
        {"name": "Bad", "entries": [], "unknown": True},
        {"name": "Bad", "entries": []},
        {"name": "N" * 101, "entries": [{"source_term": "A", "target_translation": "B"}]},
        {"name": "Bad", "entries": [{"source_term": "A" * 501, "target_translation": "B"}]},
    ],
)
def test_glossary_requests_enforce_strict_models_and_configured_limits(
    tmp_path: Path, command: dict[str, object]
) -> None:
    manager = RecordingJobManager()
    with TestClient(
        create_app(configured_for_tmp(tmp_path), job_manager=cast(JobManager, manager))
    ) as client:
        client.get("/")
        response = client.post(
            "/api/glossaries", json=command, headers={"X-CSRF-Token": client.cookies["at_csrf"]}
        )
        assert response.status_code == 422
        assert client.get("/api/glossaries").json() == {"glossaries": []}


def test_pdf_info_counts_locally_and_always_cleans_staging(tmp_path: Path) -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    config = configured_for_tmp(tmp_path)
    config = config.model_copy(update={"web": config.web.model_copy(update={"max_pdf_pages": 2})})
    manager = RecordingJobManager()
    app = create_app(config, job_manager=cast(JobManager, manager))
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=100, height=100)
    data = BytesIO()
    writer.write(data)
    files = {"pdf": ("../../two.pdf", data.getvalue(), "application/pdf")}
    with TestClient(app) as client:
        assert client.post("/api/pdf-info", files=files).status_code == 403
        client.get("/session")
        headers = {"X-CSRF-Token": client.cookies["at_csrf"]}
        response = client.post("/api/pdf-info", files=files, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"page_count": 2}
        assert response.headers["cache-control"] == "no-store"
        for content in (b"not a pdf", b"%PDF-1.7 invalid"):
            bad = client.post("/api/pdf-info", files={"pdf": ("bad.pdf", content)}, headers=headers)
            assert bad.status_code in (415, 422)
        writer.add_blank_page(width=100, height=100)
        too_large = BytesIO()
        writer.write(too_large)
        assert (
            client.post(
                "/api/pdf-info", files={"pdf": ("large.pdf", too_large.getvalue())}, headers=headers
            ).status_code
            == 422
        )
        writer.encrypt("secret-password")
        encrypted = BytesIO()
        writer.write(encrypted)
        assert (
            client.post(
                "/api/pdf-info",
                files={"pdf": ("locked.pdf", encrypted.getvalue())},
                headers=headers,
            ).status_code
            == 422
        )
    assert not manager.submissions
    assert not list((config.paths.artifacts_dir / ".uploads").iterdir())


def test_api_key_defaults_follow_configured_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for provider in ("gemini", "openai", "anthropic"):
        monkeypatch.delenv(f"{provider.upper()}_API_KEY", raising=False)
    config = configured_for_tmp(tmp_path)
    config = config.model_copy(
        update={"provider": config.provider.model_copy(update={"name": "openai"})}
    )
    store = DotenvSecretStore(tmp_path / ".env")
    with TestClient(
        create_app(config, job_manager=cast(JobManager, RecordingJobManager()), secret_store=store)
    ) as client:
        client.get("/session")
        headers = {"X-CSRF-Token": client.cookies["at_csrf"]}
        response = client.post(
            "/api/settings/api-key",
            headers=headers,
            json={"api_key": "test-openai-only", "save_on_computer": True},
        )
        assert response.status_code == 200
        assert store.has_api_key("openai")
        assert not store.has_api_key("gemini")
        public = client.get("/api/config").json()
        assert public["api_key_configured"]
        assert public["api_key_saved_on_computer"]
        assert "test-openai-only" not in str(public)
        assert client.delete("/api/settings/api-key", headers=headers).status_code == 200
        assert not store.has_api_key("openai")
