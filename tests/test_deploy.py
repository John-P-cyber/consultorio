import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_isolated(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_uvicorn_logging_bootstrap_does_not_import_app_config():
    env = os.environ.copy()
    for key in ("DATABASE_URL", "SECRET_KEY", "MFA_MASTER_KEY", "CLINIC_PROVISIONING_TOKEN"):
        env.pop(key, None)

    script = (
        "import json, logging.config, pathlib; "
        "config = json.loads(pathlib.Path('deploy/logging.json').read_text(encoding='utf-8')); "
        "logging.config.dictConfig(config)"
    )
    result = run_isolated(script, env)

    assert result.returncode == 0, result.stderr


def test_render_url_supplies_secure_public_defaults():
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "production",
            "DATABASE_URL": "sqlite:///render-test.sqlite",
            "SECRET_KEY": "render-secret-key-with-at-least-32-characters",
            "MFA_MASTER_KEY": "render-mfa-key-different-with-at-least-32-characters",
            "CLINIC_PROVISIONING_TOKEN": "render-provisioning-token-with-at-least-32-characters",
            "RENDER": "true",
            "RENDER_EXTERNAL_URL": "https://consultorio-demo.onrender.com",
        }
    )
    env.pop("ALLOWED_ORIGINS", None)
    env.pop("RESET_URL", None)

    script = (
        "import json, config; "
        "print(json.dumps({'origins': config.ALLOWED_ORIGINS, 'reset': config.RESET_URL}))"
    )
    result = run_isolated(script, env)

    assert result.returncode == 0, result.stderr
    configured = json.loads(result.stdout)
    assert configured == {
        "origins": ["https://consultorio-demo.onrender.com"],
        "reset": "https://consultorio-demo.onrender.com/recuperar-senha.html",
    }
