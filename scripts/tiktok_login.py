"""Open a persistent, non-headless Chromium profile for manual TikTok login."""

import argparse
import subprocess

from socauto.config import Settings
from socauto.destinations.tiktok.signer import chromium_executable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--background", action="store_true", help="return while Chromium stays open"
    )
    args = parser.parse_args()

    settings = Settings()
    executable = chromium_executable(settings)
    if executable is None:
        parser.error("Chromium was not found; set SOCAUTO_TIKTOK_CHROMIUM_BINARY")
    profile = settings.tiktok_browser_profile_dir.resolve()
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    profile.chmod(0o700)
    command = [
        executable,
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://www.tiktok.com/login",
    ]
    if args.background:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"TikTok login profile opened at {profile}")
        return 0
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
