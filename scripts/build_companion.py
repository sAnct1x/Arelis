"""Build the Android companion APK and stage it for the house to serve.

Does not run from the Settings UI. Arelis will not shell out to Gradle.
You run this when you want a new APK on the phone.

Release signing uses ARELIS_ANDROID_KEYSTORE* in the environment. Without
those this produces a debug APK, which will update a phone that already
has a debug build from the same machine and will not update a release
install. Never commit a keystore — the repo is public.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "arelis-notify"
STAGED = ROOT / "companion"


def _gradle() -> list[str]:
    if os.name == "nt":
        wrapper = ANDROID / "gradlew.bat"
        if wrapper.is_file() and (ANDROID / "gradle" / "wrapper" / "gradle-wrapper.jar").is_file():
            return [str(wrapper)]
    else:
        wrapper = ANDROID / "gradlew"
        if wrapper.is_file() and (ANDROID / "gradle" / "wrapper" / "gradle-wrapper.jar").is_file():
            return [str(wrapper)]
    return ["gradle"]


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from arelis.companion_pack import (
        describe_apk,
        env_keystore_configured,
        parse_gradle_version,
        write_sidecar,
    )

    gradle = ANDROID / "app" / "build.gradle.kts"
    expected = parse_gradle_version(gradle.read_text(encoding="utf-8"))
    if expected is None:
        print("Could not read versionCode from android/arelis-notify/app/build.gradle.kts", file=sys.stderr)
        return 2
    signed = env_keystore_configured()
    task = ":app:assembleRelease" if signed else ":app:assembleDebug"
    kind = "release" if signed else "debug"
    print(f"Building companion {expected.version_name} ({kind})…")
    cmd = [*_gradle(), task]
    result = subprocess.run(cmd, cwd=str(ANDROID))
    if result.returncode != 0:
        return result.returncode
    built = (
        ANDROID
        / "app"
        / "build"
        / "outputs"
        / "apk"
        / kind
        / f"app-{kind}.apk"
    )
    if not built.is_file():
        print(f"Gradle finished but {built} is missing.", file=sys.stderr)
        return 2
    STAGED.mkdir(parents=True, exist_ok=True)
    dest = STAGED / "arelis.apk"
    shutil.copy2(built, dest)
    offer = describe_apk(dest)
    if offer is None:
        print("Built APK could not be described.", file=sys.stderr)
        return 2
    write_sidecar(dest, offer)
    print(f"Staged {dest}")
    print(f"  version {offer.version_name} ({offer.version_code})")
    print(f"  {offer.size} bytes")
    print(f"  sha256 {offer.sha256}")
    print("  signed", offer.signed)
    print("Settings → Notify will now grow a download QR once Arelis is running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
