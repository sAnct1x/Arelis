"""Assemble a self-contained Arelis tree: interpreter, libraries and launchers.

What this produces
==================

`win-installer/dist/Arelis/`, a directory that runs Arelis on a machine that has never
had Python. Inside it: CPython's official Windows embeddable distribution, the locked
dependency set, the arelis wheel, and `Scripts/arelisw.exe` for a shortcut to point at.
Copy the directory anywhere and it works; there is nothing to register and nothing on
PATH. The Inno Setup script in this directory turns it into a single .exe, but that is
packaging, and this is the part that has to be right first.

Why an interpreter and not a frozen executable
==============================================

Settled earlier and recorded in .planning/installer-plan.md, but the reason belongs
next to the code it shapes. Arelis registers Windows scheduled tasks that launch it
again later, as `pythonw.exe -m arelis --run-job <id>`. PyInstaller and Nuitka produce
an executable with no `-m`, so freezing means every scheduled job a user already has
stops running, silently, because a scheduled task that fails leaves nothing on screen.
Shipping a real interpreter means `runner_command()` keeps naming a real interpreter and
that whole class of problem never opens. It also means no hidden-import guesswork for
the twelve or so libraries here that are imported lazily inside functions.

Why the embeddable distribution
===============================

It is the build python.org publishes for exactly this: no installer, no registry, no
PATH, no interference with any Python the user may later install. It is also missing
things a normal install has, and those absences are the interesting part of this file.
There is no `pip`, no `ensurepip` and no `venv`, and `site` is switched off by a `._pth`
file, so nothing on `sys.path` but the standard library and the program directory. So
the build has to enable `site`, put `pip` there itself, and take `pip` back out before
shipping -- an installed copy has no business being able to modify itself, and it is
15MB that never runs.

Verification, rather than a build that merely finished
=====================================================

A build script that exits zero having produced a tree that cannot start is worse than
one that fails, because the failure arrives on somebody else's machine. So the last
phase runs the tree: it imports every Qt module the codebase imports, brings up a real
QApplication offscreen, runs `-m arelis --version` in a subprocess because that is the
form every scheduled job takes, and runs `Scripts/arelis.exe --version` because that is
the form the shortcut takes. It also runs scripts/installed_smoke.py under the bundled
interpreter, which is the same set of checks CI runs against a wheel in a clean
virtualenv -- the tree is an install, so the rules for an install apply to it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CACHE = HERE / ".cache"
BUILD = HERE / "build"
DIST = HERE / "dist"
TREE = DIST / "Arelis"
LOCK = HERE / "requirements-win-amd64-cp314.txt"

PYTHON_VERSION = "3.14.7"
PYTHON_TAG = "314"

# python.org's own manifest for this release publishes the digest, so the download is
# checked rather than trusted:
#   https://www.python.org/ftp/python/3.14.7/windows-3.14.7.json
# Pinned here instead of fetched at build time so that a change to what we ship is an
# edit somebody made, visible in a diff, rather than whatever the network served.
EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embeddable-amd64.zip"
)
EMBED_SHA256 = "76c3c0384ab3f822486f32450f3a4d20f5d65ad0ec32ee34290971aa0eb817e6"

# Only present while the build runs. Pinned so two builds a month apart install the
# dependency set the same way.
PIP_VERSION = "25.3"

# Removed from the finished tree. setuptools and wheel are build-time only, and pip
# would let an installed copy rewrite itself.
BUILD_ONLY = ("pip", "setuptools", "wheel", "pkg_resources", "_distutils_hack")

# Every Qt module imported anywhere in the codebase, which is the whole basis for the
# prune being safe. Kept as data because the verification step imports exactly this
# list, so a module added to the app and not added here fails the build.
QT_MODULES = (
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtMultimedia",
    "QtMultimediaWidgets",
)

# One import per dependency this project declares, in the form that actually proves it
# arrived. Import names are not distribution names -- beautifulsoup4 is `bs4`, PyYAML is
# `yaml` -- and for the compiled ones the submodule is the point: `import lxml` succeeds
# on a package whose extension module is missing, `import lxml.etree` does not.
#
# Only the declared dependencies, not the 76 in the closure. A transitive package that
# cannot be imported on Windows for reasons of its own -- dlinfo is the example here --
# would turn this into a check people learn to ignore, and the transitive ones are
# reached through these anyway.
REQUIRED_IMPORTS = (
    "httpx",
    "bs4",
    "lxml.etree",
    "pandas",
    "numpy",
    "yaml",
    "pypdf",
    "google.auth",
    "google_auth_oauthlib",
    "msal",
    "faster_whisper",
    "sherpa_onnx",
    "onnxruntime",
    "espeakng_loader",
    "phonemizer",
    "playwright.async_api",
)


def say(message: str) -> None:
    print(message, flush=True)


def run(command: list[str], what: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command, capture_output=True, text=True, cwd=str(cwd) if cwd else None
    )
    if result.returncode != 0:
        sys.stderr.write(f"\n{what} failed (exit {result.returncode}).\n\n")
        sys.stderr.write((result.stdout or "").strip() + "\n")
        sys.stderr.write((result.stderr or "").strip() + "\n")
        raise SystemExit(result.returncode)
    return result.stdout


def human(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:,.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:,.1f}GB"


def tree_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# --------------------------------------------------------------------------------------
# Phase 1: the interpreter


def download(url: str, destination: Path, expected_sha256: str) -> Path:
    """Fetch once into the cache, and refuse anything whose digest is not the one named.

    Cached across builds because it is 12MB from python.org every time otherwise, but
    the cached copy is re-hashed rather than trusted for being present: a truncated
    download from an interrupted build would otherwise be reused forever.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and digest_of(destination) == expected_sha256:
        say(f"  cached: {destination.name}")
        return destination

    say(f"  fetching {url}")
    with urllib.request.urlopen(url) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)

    actual = digest_of(destination)
    if actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise SystemExit(
            "The download does not match the digest python.org publishes for it.\n"
            f"  expected {expected_sha256}\n"
            f"  received {actual}\n"
            "Nothing was kept. Either the release was re-cut, in which case update\n"
            "EMBED_SHA256 from the windows-*.json manifest, or something is wrong."
        )
    say(f"  verified: {destination.name} ({human(destination.stat().st_size)})")
    return destination


def digest_of(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def unpack_interpreter() -> None:
    archive = download(EMBED_URL, CACHE / Path(EMBED_URL).name, EMBED_SHA256)
    TREE.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(TREE)
    say(f"  unpacked CPython {PYTHON_VERSION} into {TREE.relative_to(REPO_ROOT)}")


def enable_site_packages() -> None:
    """Rewrite the `._pth` so the tree has a site-packages at all.

    The embeddable distribution ships `pythonXY._pth` listing the standard library zip
    and the program directory, with `import site` present but commented out. While it
    stays that way there is nowhere for a third-party package to live and `-m pip` does
    not exist, so this is the difference between a Python and a Python that can have
    Qt in it. `import site` also has to be on for the `.pth` files that several of
    these packages install to run at startup.

    Left as a `._pth` rather than removed, because that file is also what keeps the
    tree from reading `PYTHONPATH` or a user's site-packages: an Arelis install must not
    change behaviour because of an unrelated Python somewhere else on the machine.
    """
    matches = list(TREE.glob("python*._pth"))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one ._pth in the embeddable tree, found {matches}")
    path = matches[0]
    path.write_text(
        "\n".join(
            [
                f"python{PYTHON_TAG}.zip",
                ".",
                "Lib\\site-packages",
                "import site",
            ]
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (TREE / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    say(f"  {path.name}: site enabled, Lib\\site-packages on the path")


# --------------------------------------------------------------------------------------
# Phase 2: the libraries


def bootstrap_pip() -> None:
    """Put pip into the tree using the build machine's pip.

    There is no ensurepip here to call, and get-pip.py would mean running a script
    fetched from the network against an unpinned pip. This installs a pinned pip as a
    plain package instead, which is all pip is.
    """
    run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--upgrade",
         "--target", str(TREE / "Lib" / "site-packages"), f"pip=={PIP_VERSION}"],
        f"Installing pip {PIP_VERSION} into the tree",
    )
    say(f"  pip {PIP_VERSION} available to the bundled interpreter")


def python_exe() -> Path:
    return TREE / "python.exe"


def installed_version() -> str:
    """Ask the tree what version it is, rather than assuming.

    So the number on the installer is the number in the tree. cwd is the tree itself:
    the `._pth` resolves its relative entries against the interpreter's own directory
    rather than the working directory, so this cannot accidentally read the checkout,
    but relying on that quietly is how the smoke script's console-script bug happened.
    """
    return run(
        [str(python_exe()), "-c", "import arelis; print(arelis.__version__)"],
        "Reading the version installed in the tree",
        cwd=TREE,
    ).strip()


def install_locked_dependencies() -> None:
    """Install the lock, with hashes enforced.

    --require-hashes is the reason the lock exists. It makes pip refuse an archive whose
    contents are not the ones resolved and reviewed, so a mirror serving something else
    fails this build instead of being packaged into an installer and handed out.

    Bytecode is compiled on purpose. An installed copy under Program Files or a
    read-only directory cannot write .pyc, and without them every launch recompiles the
    same modules and throws the result away.
    """
    run(
        [str(python_exe()), "-m", "pip", "install",
         "--require-hashes",
         "--only-binary", ":all:",
         "--no-warn-script-location",
         "-r", str(LOCK)],
        "Installing the locked dependency set",
    )
    say(f"  installed the {LOCK.name} set")


def build_and_install_arelis() -> str:
    """Build the wheel from this checkout and install it without touching its deps.

    --no-deps because the dependency set is the lock's business. Without it pip would
    re-resolve from the floors in pyproject.toml and quietly replace pinned versions
    with whatever is current, which would undo the point of the previous step.
    """
    BUILD.mkdir(parents=True, exist_ok=True)
    wheelhouse = BUILD / "wheel"
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheelhouse),
         str(REPO_ROOT)],
        "Building the arelis wheel",
    )
    wheels = sorted(wheelhouse.glob("arelis-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one arelis wheel, found {wheels}")
    run(
        [str(python_exe()), "-m", "pip", "install", "--no-deps", "--no-warn-script-location",
         str(wheels[0])],
        "Installing arelis into the tree",
    )
    say(f"  installed {wheels[0].name}")
    return wheels[0].name


def replace_console_launchers() -> None:
    """Throw away pip's .exe launchers and ship .cmd shims that find their own interpreter.

    pip writes the absolute path of the interpreter that installed the wheel into every
    launcher it generates. Here that is the build directory, so the shipped arelis.exe said

        #!C:\\Users\\...\\Documents\\Arelis\\win-installer\\dist\\Arelis\\python.exe

    which exists on exactly one computer. On the machine that built it the launcher works
    and runs the *build tree*, so it looks fine and is testing the wrong copy -- that is how
    this survived a green build and an install. Anywhere else the path is absent.

    What made it worth deleting rather than patching is what the launcher does when the path
    is wrong. A shebang of a bare name, which is the only relocatable form these launchers
    accept, is resolved against PATH: measured on this machine, arelis.exe with `#!python.exe`
    started an unrelated Python 3.11 from %LOCALAPPDATA%\\Programs and imported arelis out of
    a source checkout. Failing would have been better. `#!..\\python.exe` is simply not
    understood, and there is no other relative form, so a correct launcher cannot be produced
    without knowing the install directory, which a per-user install does not know until the
    user picks it.

    So nothing in the shipped tree is allowed to depend on them. Shortcuts, the uninstall
    hook, the update relaunch and every scheduled task name {app}\\python[w].exe directly.
    These shims exist for the person who opens Scripts\\ expecting to find something to run,
    and %~dp0 makes them work from any directory the tree is ever moved to.
    """
    scripts = TREE / "Scripts"

    # Every one of them, not just Arelis's two. The build that first ran this check found
    # 61: pyside6-designer, tqdm, rdfpipe, sherpa-onnx-cli, huggingface-cli and the rest,
    # each carrying the same dead path. They are the command-line tools of our dependencies,
    # nothing in Arelis runs one, and Scripts\ is not on PATH after a per-user install, so
    # they were 60MB of executables that could only mislead somebody who found them.
    removed = sorted(p.name for p in scripts.glob("*.exe"))
    for launcher in scripts.glob("*.exe"):
        launcher.unlink()

    # pip's own launchers, which land in a bin/ directory inside site-packages rather than in
    # Scripts\ and so were not swept up when pip itself was removed. Left behind they are
    # three executables that name a missing interpreter in order to run a missing pip.
    stray = TREE / "Lib" / "site-packages" / "bin"
    if stray.is_dir():
        shutil.rmtree(stray)
        say("  removed site-packages\\bin, pip's launchers left behind by its own removal")

    # cmd /c resolves %~dp0 to Scripts\ with a trailing backslash, so ..\ climbs to the tree
    # root where the interpreter lives. Quoted throughout because %LOCALAPPDATA% contains a
    # space for anybody whose account name does.
    (scripts / "arelis.cmd").write_text(
        '@echo off\r\n"%~dp0..\\python.exe" -m arelis %*\r\n',
        encoding="ascii",
    )
    # start "" so the console this was typed into is returned immediately rather than being
    # held for the lifetime of the window.
    (scripts / "arelisw.cmd").write_text(
        '@echo off\r\nstart "" "%~dp0..\\pythonw.exe" -m arelis %*\r\n',
        encoding="ascii",
    )
    say(f"  removed {len(removed)} .exe launchers from Scripts, all naming this machine")
    say("  wrote arelis.cmd and arelisw.cmd, which locate their own interpreter")


def check_no_build_paths_leak() -> None:
    """Fail the build if any shipped file names the directory it was built in.

    The general form of the launcher bug, and the check that would have caught it. A tree
    that mentions where it was built is a tree that only works there, and the failure is
    invisible to whoever built it for exactly that reason.

    UTF-16 as well as ASCII, because Windows binaries embed paths both ways, and the
    launchers that started this were plain bytes while a .exe manifest may not be.

    Compiled bytecode is exempt, and it is worth being clear that this is a judgement rather
    than an oversight: 3,149 of the 3,213 files the first run of this check objected to were
    .pyc. Every one records the source path it was compiled from in ``co_filename``, which
    Python uses for tracebacks and for nothing else -- import does not consult it, and
    staleness is decided by the size and mtime of the source file sitting next to the cache.
    So the cost is a traceback quoting a directory the reader does not have. The alternatives
    are worse: shipping no bytecode means either recompiling on first import, which an
    admin-installed tree under Program Files may not be allowed to do at all, or losing the
    cache permanently and paying for it on every launch. compileall can rewrite the recorded
    path, but only to another fixed one, and the install directory is chosen by the user.
    """
    # Most specific first, and one reason per file: the build tree lives inside the
    # repository, so its path contains the repository's and every offender would otherwise be
    # reported twice.
    needles = (
        ("the build tree", str(TREE.resolve())),
        ("the repository", str(REPO_ROOT.resolve())),
    )
    encoded = [
        (label, text.encode("utf-8"), text.encode("utf-16-le")) for label, text in needles
    ]

    offenders: list[str] = []
    exempt = 0
    for path in TREE.rglob("*"):
        if not path.is_file():
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        for label, ascii_bytes, wide_bytes in encoded:
            if ascii_bytes not in blob and wide_bytes not in blob:
                continue
            if path.suffix == ".pyc":
                exempt += 1
            else:
                offenders.append(f"    {path.relative_to(TREE)} names {label}")
            break

    if offenders:
        sys.stderr.write(
            "\nFiles in the shipped tree name a path from this machine, so they would be "
            "wrong on any other:\n" + "\n".join(sorted(offenders)) + "\n\n"
            "This is what pip's console-script launchers did. Whatever produced these has "
            "to be given a relative path or removed.\n"
        )
        raise SystemExit(1)
    say(
        f"  nothing outside bytecode names this machine "
        f"({exempt:,} .pyc carry a co_filename, which only affects tracebacks)"
    )


def remove_build_only_packages() -> None:
    """Take pip and setuptools back out, and any .pth file left pointing at them.

    A `.pth` in site-packages is executed by `site` on every interpreter start, so
    removing a package while leaving the file that imports it means a traceback printed
    before Arelis gets a word in. setuptools installs exactly such a file --
    distutils-precedence.pth, which imports _distutils_hack -- and the first build here
    did precisely that. Found by reading the .pth files rather than by naming that one,
    because the next package to install a hook will not be called setuptools.
    """
    site = TREE / "Lib" / "site-packages"
    freed = 0
    for name in BUILD_ONLY:
        for path in list(site.glob(name)) + list(site.glob(f"{name}-*")) + list(
            site.glob(f"{name}.py")
        ):
            freed += tree_size(path) if path.is_dir() else path.stat().st_size
            shutil.rmtree(path) if path.is_dir() else path.unlink()

    orphaned = []
    for hook in site.glob("*.pth"):
        text = hook.read_text(encoding="utf-8", errors="replace")
        if any(name in text for name in BUILD_ONLY):
            orphaned.append(hook.name)
            freed += hook.stat().st_size
            hook.unlink()
    if orphaned:
        say(f"  removed startup hooks left without their package: {', '.join(orphaned)}")
    say(f"  removed build-only packages, {human(freed)}")


# --------------------------------------------------------------------------------------
# Phase 3: the prune
#
# PySide6 installs 634MB, which is more than half the tree and more than everything
# else in it put together. It is a build of all of Qt, and Arelis imports five modules
# of it. What follows removes feature families the codebase never mentions, and the
# reason it can be this aggressive is that the import census and the offscreen
# QApplication run afterwards: a wrong entry here fails this build rather than somebody
# else's launch.
#
# Two things in that directory look like obvious waste and are not:
#
# avcodec-61.dll and its siblings are not leftovers, they are QtMultimedia's FFmpeg
# backend, which is the default media backend on Windows from Qt 6.5. Removing them
# takes audio capture, playback and the camera panel with them, and does it without
# breaking any import, so nothing here would have noticed.
#
# opengl32sw.dll is a 20MB software OpenGL implementation, kept deliberately. The
# source-checkout solar lab can use an offscreen OpenGL context. The installer does not ship that plate,
# but Qt still reaches for this DLL when there is no usable GPU driver -- a virtual
# machine, a remote desktop session, a fresh install with no drivers yet. It is 3% of
# the finished tree to not have that class of bug.

# Whole directories. Everything here is either a feature family with no import anywhere
# in the codebase, or build-time material with no runtime role at all.
QT_DROP_DIRECTORIES = {
    "resources": "QtWebEngine's data files: icudtl.dat and the .pak bundles",
    "translations": "Qt's own UI translations, most of it QtWebEngine's locales",
    "qml": "QML modules, for a UI written in QML rather than Widgets",
    "metatypes": "JSON type registrations read by Qt's build tools, never at runtime",
    "include": "C++ headers for building against Qt",
    "typesystems": "shiboken binding definitions, used to generate PySide, not to run it",
    "glue": "shiboken's injected C++ snippets, same story",
    "examples": "Qt's example programs",
}

# Any file whose name starts with one of these. Prefixes rather than exact names so a
# family is removed whole -- "Qt6Quick" also takes Qt6QuickControls2Imagine and the
# other eleven of them -- and so a Qt upgrade that adds another one does not silently
# start shipping it.
QT_DROP_PREFIXES = (
    # The single largest item in the distribution, at 195MB, plus its bindings.
    "Qt6WebEngine", "QtWebEngine", "Qt6WebView", "QtWebView",
    "Qt6WebSockets", "QtWebSockets", "Qt6WebChannel", "QtWebChannel",
    # Qt's other UI toolkit. Arelis is Widgets throughout.
    "Qt6Quick", "QtQuick", "Qt6Qml", "QtQml", "Qt6LabsStyleKit", "Qt6ShaderTools",
    # 3D, charting and data visualisation.
    "Qt63D", "Qt3D", "Qt6Charts", "QtCharts",
    "Qt6DataVisualization", "QtDataVisualization", "Qt6Graphs", "QtGraphs",
    # Qt's own development tools, shipped inside the runtime wheel.
    "Qt6Designer", "QtDesigner", "Qt6UiTools", "QtUiTools", "Qt6Help", "QtHelp",
    # Hardware and protocol modules for hardware Arelis does not talk to.
    "Qt6Bluetooth", "QtBluetooth", "Qt6Nfc", "QtNfc",
    "Qt6SerialPort", "QtSerialPort", "Qt6SerialBus", "QtSerialBus",
    "Qt6Location", "QtLocation", "Qt6Positioning", "QtPositioning",
    "Qt6Sensors", "QtSensors",
    # Modules with a real Arelis counterpart elsewhere: PDF is pypdf, speech is Kokoro
    # and Piper, OAuth is msal and google-auth, and nothing prints.
    "Qt6Pdf", "QtPdf", "Qt6TextToSpeech", "QtTextToSpeech",
    "Qt6NetworkAuth", "QtNetworkAuth", "Qt6PrintSupport", "QtPrintSupport",
    # SQL, state machines, remote objects, Qt's own test framework.
    "Qt6Sql", "QtSql", "Qt6Scxml", "QtScxml", "Qt6StateMachine", "QtStateMachine",
    "Qt6RemoteObjects", "QtRemoteObjects", "Qt6Test", "QtTest",
    # The Python QtOpenGL* bindings. The installer does not enter the solar plate, so
    # it does not import them. Qt6OpenGL.dll itself stays: it is 1.9MB and Qt6Gui can
    # reach for it.
    "QtOpenGL",
)

# Plugins are a keep-list rather than a drop-list, the one place that inversion is
# right: a missing plugin directory is a feature that quietly does not work, while an
# unrecognised new one is only wasted space, so the failure mode of forgetting to update
# this is the harmless direction.
QT_KEEP_PLUGINS = {
    "platforms",  # qwindows.dll. Without this Qt cannot open a window at all.
    "platformthemes",
    "platforminputcontexts",
    "styles",
    "imageformats",  # PNG for the icon, and the rest of what QPixmap can load.
    "iconengines",
    "multimedia",  # the FFmpeg and Windows media backends: capture and playback.
    "tls",  # schannel, for anything Qt itself opens over HTTPS.
    "generic",
    "networkinformation",
}

# Locale data for something over 800 locales, at 28MB, reached only through
# phonemizer-fork -> segments -> csvw -> babel, on the English G2P path. `root` is
# Babel's fallback and has to stay for Locale.parse to work at all.
BABEL_KEEP_LOCALES = ("root", "en")


def prune_qt(site: Path) -> int:
    pyside = site / "PySide6"
    if not pyside.exists():
        return 0
    freed = 0

    for name, reason in QT_DROP_DIRECTORIES.items():
        target = pyside / name
        if target.is_dir():
            size = tree_size(target)
            shutil.rmtree(target)
            freed += size
            say(f"    {human(size):>10}  {name}/ -- {reason}")

    families = 0
    family_bytes = 0
    for entry in list(pyside.iterdir()):
        if entry.name.startswith(QT_DROP_PREFIXES):
            size = tree_size(entry) if entry.is_dir() else entry.stat().st_size
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
            freed += size
            family_bytes += size
            families += 1
    say(f"    {human(family_bytes):>10}  {families} files from unimported Qt modules")

    # Qt's tools ship inside the runtime wheel: designer, linguist, assistant, the qml
    # tooling, the lupdate/lrelease pair. None of them is reachable from Arelis.
    tools = 0
    tool_bytes = 0
    for exe in pyside.glob("*.exe"):
        tool_bytes += exe.stat().st_size
        exe.unlink()
        tools += 1
    if tools:
        freed += tool_bytes
        say(f"    {human(tool_bytes):>10}  {tools} Qt developer tools (designer, linguist, qml)")

    stubs = 0
    stub_bytes = 0
    for stub in pyside.rglob("*.pyi"):
        stub_bytes += stub.stat().st_size
        stub.unlink()
        stubs += 1
    if stubs:
        freed += stub_bytes
        say(f"    {human(stub_bytes):>10}  {stubs} type stubs, which only a type checker reads")

    plugins = pyside / "plugins"
    if plugins.is_dir():
        dropped = 0
        plugin_bytes = 0
        for entry in list(plugins.iterdir()):
            if entry.is_dir() and entry.name not in QT_KEEP_PLUGINS:
                plugin_bytes += tree_size(entry)
                shutil.rmtree(entry)
                dropped += 1
        if dropped:
            freed += plugin_bytes
            say(f"    {human(plugin_bytes):>10}  {dropped} plugin dirs outside the keep-list")

    return freed


def prune_babel(site: Path) -> int:
    data = site / "babel" / "locale-data"
    if not data.is_dir():
        return 0
    freed = 0
    kept = 0
    for entry in data.glob("*.dat"):
        if entry.stem.split("_")[0] in BABEL_KEEP_LOCALES:
            kept += 1
            continue
        freed += entry.stat().st_size
        entry.unlink()
    say(f"    {human(freed):>10}  Babel locale data, keeping {kept} files for root and en")
    return freed


def prune_duplicates(tree: Path) -> int:
    """One 16.6MB copy of onnxruntime.dll, not two.

    The onnxruntime wheel installs its library twice: once in onnxruntime/capi/, which
    is the copy the extension module loads, and once into Scripts/ as a data file. The
    second is never opened from here -- Scripts is not on this tree's DLL search path
    and nothing adds it -- and `import onnxruntime` in the verification below loads the
    real one, so removing the wrong copy fails the build.

    sherpa-onnx also puts a DLL in Scripts and that one stays: it is documented as
    loading from there on Windows, and 4MB is not worth finding out.
    """
    duplicate = tree / "Scripts" / "onnxruntime.dll"
    if not duplicate.exists():
        return 0
    size = duplicate.stat().st_size
    duplicate.unlink()
    say(f"    {human(size):>10}  the second copy of onnxruntime.dll in Scripts/")
    return size


def prune_test_suites(site: Path) -> int:
    """Packages that ship their own test suite, which no installed copy ever runs.

    Only a package's own top-level `tests` directory, not anything nested, and the
    import census afterwards is what makes it safe rather than the naming convention.
    """
    freed = 0
    dropped = []
    for package in site.iterdir():
        if not package.is_dir() or package.name.endswith(".dist-info"):
            continue
        tests = package / "tests"
        if tests.is_dir():
            size = tree_size(tests)
            if size < 1024 * 1024:
                continue
            shutil.rmtree(tests)
            freed += size
            dropped.append(f"{package.name} ({human(size)})")
    if dropped:
        say(f"    {human(freed):>10}  bundled test suites: {', '.join(dropped)}")
    return freed


def prune(before: int) -> None:
    site = TREE / "Lib" / "site-packages"
    freed = 0
    say("  Qt, which is 634MB of which Arelis imports five modules:")
    freed += prune_qt(site)
    say("  elsewhere:")
    freed += prune_babel(site)
    freed += prune_duplicates(TREE)
    freed += prune_test_suites(site)
    after = tree_size(TREE)
    say("")
    say(
        f"  removed {human(freed)}: {human(before)} -> {human(after)} "
        f"({100 * freed / before:.0f}% smaller)"
    )


# --------------------------------------------------------------------------------------
# Phase 4: measurement


def largest(path: Path, count: int = 20) -> list[tuple[str, int]]:
    """The biggest things in the tree, as the basis for deciding what to prune.

    Directories one level below site-packages, plus loose files, so the answer is
    'PySide6 is 600MB' rather than ten thousand individual DLLs.
    """
    site = path / "Lib" / "site-packages"
    entries: list[tuple[str, int]] = []
    if site.exists():
        for child in site.iterdir():
            size = tree_size(child) if child.is_dir() else child.stat().st_size
            entries.append((f"Lib/site-packages/{child.name}", size))
    for child in path.iterdir():
        if child.name == "Lib":
            continue
        size = tree_size(child) if child.is_dir() else child.stat().st_size
        entries.append((child.name, size))
    entries.sort(key=lambda pair: pair[1], reverse=True)
    return entries[:count]


def report_size(label: str) -> int:
    total = tree_size(TREE)
    say("")
    say(f"{label}: {human(total)}")
    for name, size in largest(TREE):
        if size < 1024 * 1024:
            continue
        say(f"  {human(size):>10}  {name}")
    return total


# --------------------------------------------------------------------------------------
# Phase 6: the setup .exe


ISS = HERE / "arelis.iss"

# The directories Inno Setup installs under, most likely first. %LOCALAPPDATA%\Programs
# leads because that is where it lands from the winget line this file prints: an
# unelevated `winget install` is a per-user install, and neither Program Files location
# gets a directory at all. Looked for first because the recommended command produces it.
ISCC_PARENTS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
    # A 32-bit program even on 64-bit Windows, so the x86 directory is the usual answer
    # for a machine-wide install rather than the fallback.
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
)


def find_iscc() -> Path | None:
    """PATH first, then the install directories, newest major version first.

    Globbed rather than named, so that Inno Setup 7 is found without an edit here. Inno
    Setup does not put itself on PATH, so the glob is the path that actually runs.
    """
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found:
        return Path(found)
    for parent in ISCC_PARENTS:
        if not parent.is_dir():
            continue
        for directory in sorted(parent.glob("Inno Setup*"), reverse=True):
            candidate = directory / "ISCC.exe"
            if candidate.exists():
                return candidate
    return None


def install_over_existing(installer: Path) -> None:
    """Run the installer we just built, replacing the copy already on this machine.

    For the author's own loop rather than for anybody else: edit the checkout, then
    promote it to the Arelis actually being used, in one command instead of building and
    then going to find the .exe.

    An upgrade rather than a second install, because arelis.iss pins AppId -- same
    directory, same Start Menu entry, one row in Apps & Features. %LOCALAPPDATA%\\Arelis
    is untouched, so conversations, memory, saved jobs and tokens come straight back.

    /SILENT and not /VERYSILENT: a progress window for something that takes a minute is
    worth having, and it is the difference between a slow install and a hung one.
    """
    say(f"  installing {installer.name} over the existing copy...")
    result = subprocess.run(
        [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(
            f"\nThe installer exited {result.returncode}.\n"
            "Exit code 5 is a cancelled elevation prompt; 2 is a cancelled wizard.\n"
        )
        sys.stderr.write((result.stdout or "") + "\n" + (result.stderr or "") + "\n")
        raise SystemExit(result.returncode)

    # Ask the installed copy what it is, rather than reporting what we hoped to install.
    #
    # Through {app}\python.exe, and this is the third place the same mistake had to be taken
    # out. This used to run {app}\Scripts\arelis.exe, and the first build after the launchers
    # were removed still printed a version from it: the file was left over from the previous
    # install, because Inno only writes the files it ships and does not delete the ones it no
    # longer has, and its baked-in shebang pointed at the build tree, which had just been
    # rebuilt. So the check that exists to confirm the install worked was satisfied by the
    # build directory. Nothing that verifies an install may go through a launcher.
    installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Arelis"
    interpreter = installed / "python.exe"
    if not interpreter.exists():
        raise SystemExit(f"the installer reported success but {interpreter} is not there")
    version = run(
        [str(interpreter), "-m", "arelis", "--version"], "Reading the installed version"
    ).strip()
    say(f"  {installed}")
    say(f"  {version}")

    # And that it knows it is one, which is the question the updater asks. A tree missing its
    # uninstaller, or one whose package resolves somewhere else, answers no and quietly never
    # offers an update again.
    report = run(
        [str(interpreter), "-m", "arelis", "--check-update"], "Asking the installed copy"
    )
    for line in report.strip().splitlines():
        say(f"    {line}")
    if "not an installed copy" in report:
        raise SystemExit(
            "the installed copy does not recognise itself as installed, so it would never "
            "offer an update. See install_root() in arelis/update.py."
        )


def package_installer(version: str) -> Path | None:
    """Compile the tree into one setup .exe, if Inno Setup is here to do it.

    Optional rather than required, because the tree above is the part that has to be
    right and it is testable without any of this. Compressing 640MB with solid LZMA2
    takes minutes and produces something only Windows can open, so a build that stops
    short of it is still a useful build.
    """
    iscc = find_iscc()
    if iscc is None:
        say("  Inno Setup is not installed, so there is no setup .exe.")
        say("    winget install -e --id JRSoftware.InnoSetup")
        say(f"    then re-run, or: ISCC.exe /DAppVersion={version} {ISS.name}")
        return None

    say(f"  {iscc}")
    say("  compressing with solid LZMA2, which is slow on purpose...")
    run(
        [
            str(iscc),
            f"/DAppVersion={version}",
            f"/DSourceTree={TREE}",
            str(ISS),
        ],
        "Compiling the installer",
        cwd=HERE,
    )
    installers = sorted(DIST.glob("*-setup.exe"), key=lambda p: p.stat().st_mtime)
    if not installers:
        raise SystemExit(f"Inno Setup reported success but produced nothing in {DIST}")
    installer = installers[-1]
    say("")
    say(f"  {installer.name}")
    say(f"  {human(installer.stat().st_size)}")
    # The thing to publish beside a download that is not signed. Somebody who wants to
    # check what they got has no certificate to check, so this is what they have.
    say(f"  sha256: {digest_of(installer)}")
    return installer


# --------------------------------------------------------------------------------------
# Phase 5: verification


def verify() -> None:
    site = TREE / "Lib" / "site-packages"

    say("  importing every Qt module the codebase imports...")
    imports = "; ".join(f"import PySide6.{name}" for name in QT_MODULES)
    run(
        [str(python_exe()), "-c", imports],
        "Importing the Qt modules Arelis uses",
    )

    say(f"  importing all {len(REQUIRED_IMPORTS)} declared dependencies...")
    # In one interpreter, reporting every failure rather than stopping at the first, so
    # a prune that broke three things is not discovered three builds from now.
    census = (
        "import importlib, sys\n"
        f"names = {REQUIRED_IMPORTS!r}\n"
        "broken = []\n"
        "for name in names:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except BaseException as error:\n"
        "        broken.append(name + ': ' + type(error).__name__ + ': ' + str(error))\n"
        "print('\\n'.join(broken))\n"
        "sys.exit(1 if broken else 0)\n"
    )
    result = subprocess.run(
        [str(python_exe()), "-c", census], capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.stderr.write("\nDeclared dependencies that do not import in the built tree:\n\n")
        sys.stderr.write((result.stdout or "").strip() + "\n")
        sys.stderr.write((result.stderr or "").strip() + "\n")
        raise SystemExit(1)

    say("  bringing up a real QApplication offscreen...")
    # Imports are not enough. A missing platform plugin, a missing style or a Qt DLL
    # whose dependency was pruned all import cleanly and fail when something is drawn.
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    probe = (
        "from PySide6.QtWidgets import QApplication, QLabel;"
        "app = QApplication([]);"
        "label = QLabel('arelis');"
        "label.show();"
        "app.processEvents();"
        "print('qt ok')"
    )
    result = subprocess.run(
        [str(python_exe()), "-c", probe], capture_output=True, text=True, env=environment
    )
    if result.returncode != 0 or "qt ok" not in result.stdout:
        sys.stderr.write("\nQt cannot start in the built tree.\n\n")
        sys.stderr.write((result.stdout or "") + "\n" + (result.stderr or "") + "\n")
        raise SystemExit(1)

    say("  the ways Arelis is started...")
    # Every one of these is a real launch path: the shortcuts and the update relaunch use
    # pythonw.exe -m arelis, scheduled tasks use the same, the uninstall hook uses
    # python.exe -m arelis, and the shim is what a person finds in Scripts. All four name
    # the interpreter by its position in the tree, which is what makes the tree movable.
    module = run([str(python_exe()), "-m", "arelis", "--version"], "-m arelis --version").strip()
    say(f"    -m arelis      -> {module}")

    shim = TREE / "Scripts" / "arelis.cmd"
    if not shim.exists():
        raise SystemExit(f"no console shim at {shim}")
    viacmd = run(["cmd", "/c", str(shim), "--version"], "arelis.cmd --version").strip()
    say(f"    arelis.cmd     -> {viacmd}")
    if module != viacmd:
        raise SystemExit(f"the two entry points disagree: {module!r} vs {viacmd!r}")

    for stale in ("arelis.exe", "arelisw.exe"):
        if (TREE / "Scripts" / stale).exists():
            raise SystemExit(
                f"{stale} is back in the tree. pip writes this machine's interpreter path "
                "into it, so it works here and nowhere else -- see replace_console_launchers."
            )
    say("    no pip launchers, which would carry this machine's paths")

    say("  pythonw.exe, which is what shortcuts and scheduled jobs run...")
    if not (TREE / "pythonw.exe").exists():
        raise SystemExit("no pythonw.exe in the tree; scheduled jobs would open a console")
    windowless = subprocess.run(
        [str(TREE / "pythonw.exe"), "-c", "import arelis; print(arelis.__version__)"],
        capture_output=True,
        text=True,
    )
    if windowless.returncode != 0:
        sys.stderr.write((windowless.stdout or "") + "\n" + (windowless.stderr or "") + "\n")
        raise SystemExit("pythonw.exe cannot import arelis, so every shortcut would do nothing")

    say("  nothing in the tree names where it was built...")
    check_no_build_paths_leak()

    say("  the installed-copy checks, under the bundled interpreter...")
    # The same script CI runs against a wheel in a clean virtualenv. The bundled tree is
    # an install, so every rule about an install applies to it: assets present, nothing
    # writable inside the program, both entry points working.
    smoke = REPO_ROOT / "scripts" / "installed_smoke.py"
    result = subprocess.run(
        [str(python_exe()), str(smoke)],
        capture_output=True,
        text=True,
        # Not the repository. From inside it, `import arelis` would find the source tree
        # and the checks would pass while saying nothing about the tree just built.
        cwd=str(TREE.parent),
    )
    for line in (result.stdout or "").splitlines():
        say(f"    {line}")
    if result.returncode != 0:
        sys.stderr.write((result.stderr or "") + "\n")
        raise SystemExit("the bundled tree failed the installed-copy checks")

    say("")
    say(f"  site-packages holds {len(list(site.glob('*.dist-info')))} distributions")


# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Assemble a self-contained Arelis tree for Windows.",
    )
    parser.add_argument(
        "--keep-tree",
        action="store_true",
        help="Reuse an existing dist/Arelis instead of starting from a clean unpack.",
    )
    parser.add_argument(
        "--measure-only",
        action="store_true",
        help="Report the size of an already-built tree and stop. Builds nothing.",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help=(
            "After building, run the installer over the copy already on this machine. "
            "Promotes this checkout to the Arelis you actually use. Your data is not "
            "touched."
        ),
    )
    parser.add_argument(
        "--installer-only",
        action="store_true",
        help=(
            "Compile an existing dist/Arelis without rebuilding it. Verifies the tree "
            "first, so this is a shortcut past the build and not past the checks."
        ),
    )
    parser.add_argument(
        "--no-installer",
        action="store_true",
        help=(
            "Stop after the verified tree. Compressing 640MB takes minutes, and the "
            "tree is the part that has to be right."
        ),
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help=(
            "Keep all of Qt. Four times the size and not shippable, but it is the "
            "comparison to make when something works unpruned and not pruned."
        ),
    )
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        raise SystemExit(
            "This builds a Windows tree using the bundled interpreter itself, so it has "
            "to run on Windows: the verification step imports every dependency and starts "
            "Qt under the interpreter that will ship, which is the part worth having."
        )
    if not LOCK.exists():
        raise SystemExit(f"no lock at {LOCK}. Run: python win-installer/lock.py")

    if args.measure_only:
        if not TREE.exists():
            raise SystemExit(f"nothing built at {TREE}")
        report_size("Built tree")
        return 0

    started = time.monotonic()

    if args.installer_only:
        if not TREE.exists():
            raise SystemExit(f"nothing built at {TREE}. Run without --installer-only.")
        total = report_size("Existing tree")
        say("\n== Verification ==")
        verify()
        say("\n== Setup .exe ==")
        installer = package_installer(installed_version())
        if installer and args.install:
            say("\n== Install ==")
            install_over_existing(installer)
        say("")
        say(f"{human(total)} in {time.monotonic() - started:,.0f}s")
        if installer:
            say(f"Installer: {installer.relative_to(REPO_ROOT)}")
        return 0

    if not args.keep_tree and DIST.exists():
        say(f"Clearing {DIST.relative_to(REPO_ROOT)}...")
        shutil.rmtree(DIST)

    say(f"\n== Interpreter: CPython {PYTHON_VERSION}, embeddable, amd64 ==")
    unpack_interpreter()
    enable_site_packages()

    say("\n== Libraries ==")
    bootstrap_pip()
    install_locked_dependencies()
    wheel_name = build_and_install_arelis()
    replace_console_launchers()
    remove_build_only_packages()

    before = report_size("Unpruned tree")

    if args.no_prune:
        say("\n== Prune skipped (--no-prune) ==")
        total = before
    else:
        say("\n== Prune ==")
        prune(before)
        total = report_size("Shipped tree")

    say("\n== Verification ==")
    verify()

    installer = None
    if not args.no_installer:
        say("\n== Setup .exe ==")
        installer = package_installer(installed_version())
        if installer and args.install:
            say("\n== Install ==")
            install_over_existing(installer)

    say("")
    say(f"Built {TREE.relative_to(REPO_ROOT)} from {wheel_name}")
    say(f"{human(total)} in {time.monotonic() - started:,.0f}s")
    if installer:
        say(f"Installer: {installer.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
