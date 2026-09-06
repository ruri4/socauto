"""Run the offline verification suite with isolated migrations and real local tools."""

import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def run(*command: str, env: dict[str, str]) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True, timeout=180)


def main() -> None:
    for tool in ("uv", "bun", "ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise SystemExit(f"offline verification requires {tool} on PATH")
    browser = os.environ.get("SOCAUTO_TIKTOK_CHROMIUM_BINARY") or next(
        (
            path
            for name in ("chromium-browser", "chromium", "google-chrome")
            if (path := shutil.which(name))
        ),
        None,
    )
    if browser is None or not Path(browser).is_file():
        raise SystemExit("offline verification requires a system Chromium/Chrome binary")

    with TemporaryDirectory(prefix="socauto-verify-") as directory:
        env = {
            **os.environ,
            "SOCAUTO_DATA_DIR": directory,
            "SOCAUTO_TIKTOK_CHROMIUM_BINARY": browser,
        }
        run("uv", "run", "ruff", "format", "--check", ".", env=env)
        run("uv", "run", "ruff", "check", ".", env=env)
        run("uv", "run", "mypy", env=env)
        run("uv", "run", "pytest", "--cov=socauto", "--cov-report=term-missing", env=env)
        run("bun", "test", "signer/tiktok", env=env)
        for action, target in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
            run("uv", "run", "alembic", action, target, env=env)
        run("uv", "run", "alembic", "check", env=env)
        run("uv", "build", env=env)
        run("git", "diff", "--check", env=env)
    print("\nOffline verification passed. Live X/TikTok checks remain deferred.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"verification failed: {error}") from None
