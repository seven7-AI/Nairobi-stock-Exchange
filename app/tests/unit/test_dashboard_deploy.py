"""The dashboard's systemd unit and installer: the template renders with every
placeholder filled and the settings the public port relies on."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = REPO / "deployment/systemd/nse-dashboard.service"
INSTALLER = REPO / "scripts/install_dashboard_service.sh"


def test_unit_template_declares_the_public_port_contract() -> None:
    text = TEMPLATE.read_text()
    assert "Environment=DASHBOARD_STANDALONE=true" in text
    assert "Environment=DASHBOARD_PUBLIC=true" in text
    assert "Environment=ENVIRONMENT=staging" in text
    assert "--host 0.0.0.0 --port __PORT__ --workers 1" in text
    assert "--no-server-header" in text and "Restart=always" in text
    assert "WantedBy=default.target" in text  # a user unit
    assert "__REPO_ROOT__" in text and "__UV_BIN__" in text


def test_installer_renders_without_placeholders(tmp_path: Path) -> None:
    rendered = subprocess.run(
        ["bash", str(INSTALLER), "--print"],
        check=True,
        capture_output=True,
        text=True,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
            "UV_BIN": "/opt/uv",
            "DASHBOARD_PORT": "4747",
        },
    ).stdout
    assert "__" not in rendered
    assert f"WorkingDirectory={REPO}" in rendered
    assert (
        "ExecStart=/opt/uv run --no-sync uvicorn app.web.main:app --host 0.0.0.0 --port 4747"
        in rendered
    )
    assert "EnvironmentFile=-" in rendered  # optional env files never block start-up


def test_installer_rejects_unknown_modes() -> None:
    result = subprocess.run(["bash", str(INSTALLER), "--bogus"], capture_output=True, text=True)
    assert result.returncode == 2 and "usage" in result.stdout
