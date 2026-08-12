from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from opportunity_radar.models import EmployerConfig, SourceAuthority


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def employer() -> EmployerConfig:
    return EmployerConfig(
        id="test-employer",
        canonical_name="Test Employer",
        organisation_type="corporate",
        endpoint="https://example.invalid/jobs",
        source_authority=SourceAuthority.OFFICIAL_ATS,
        enabled=False,
        priority_tier="major",
        manual_review_required=False,
    )


@pytest.fixture
def isolated_root(tmp_path: Path, project_root: Path) -> Path:
    for directory in ("config", "fixtures", "site"):
        shutil.copytree(project_root / directory, tmp_path / directory)
    for document in ("METHODOLOGY.md", "PRIVACY.md"):
        shutil.copy2(project_root / document, tmp_path / document)
    (tmp_path / "data").mkdir()
    for filename, content in {
        "open_roles.json": "[]\n",
        "recent_roles.json": "[]\n",
        "possible_roles.json": "[]\n",
        "upcoming_roles.json": "[]\n",
        "closed_roles.json": "[]\n",
        "observations.json": "[]\n",
        "review_queue.json": "[]\n",
        "source_health.json": "[]\n",
        "metrics.json": "{}\n",
        "digest_state.json": '{"sent_role_ids":[],"successful_runs":[],"last_successful_digest_at":null}\n',
    }.items():
        (tmp_path / "data" / filename).write_text(content, encoding="utf-8")
    return tmp_path
