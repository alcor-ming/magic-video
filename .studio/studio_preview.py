"""Thin, project-bound adapter for the pinned official HyperFrames Studio CLI."""

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import unquote, urlsplit
from urllib.request import ProxyHandler, build_opener

from visual_plan import VisualPlanError


def private_browser_profile(project):
    profile = project.parent / ".runtime" / "studio-browser"
    preferences = profile / "Default" / "Preferences"
    # Chrome rewrites Preferences and may drop the flag; restore it before every launch.
    try:
        data = json.loads(preferences.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = {}
    if data.get("enable_do_not_track") is not True:
        data["enable_do_not_track"] = True
        preferences.parent.mkdir(parents=True, exist_ok=True)
        preferences.write_text(json.dumps(data), encoding="utf-8")
    return profile


def browser_path():
    configured = os.environ.get("HYPERFRAMES_STUDIO_BROWSER_PATH")
    candidates = [Path(configured)] if configured else []
    if os.name == "nt" and not configured:
        candidates += [Path(os.environ[key]) / "Google/Chrome/Application/chrome.exe"
                       for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(key)]
    if not configured and os.environ.get("HYPERFRAMES_BROWSER_PATH"):
        candidates.append(Path(os.environ["HYPERFRAMES_BROWSER_PATH"]))
    for candidate in candidates:
        if candidate.is_file() and "headless" not in candidate.name:
            return candidate
    raise VisualPlanError("Set HYPERFRAMES_STUDIO_BROWSER_PATH to an installed Chrome/Chromium for isolated Studio review; --no-open is for agents with browser Do Not Track configured before navigation")


def run_cli(cli, project, arguments, *, json_output=True):
    env = {**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}
    # Keep upstream's managed-server records out of installed/frozen directories.
    env["XDG_STATE_HOME"] = str(project.parent / ".runtime" / "studio-state")
    command = [env.get("HYPERFRAMES_NODE", "node"), str(cli), "preview", str(project), *arguments]
    try:
        result = subprocess.run(command, cwd=project, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=90)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VisualPlanError(f"Pinned Studio CLI failed: {error}") from error
    if result.returncode:
        raise VisualPlanError(f"Pinned Studio CLI failed ({result.returncode}): {result.stderr or result.stdout}")
    if not json_output:
        return result.stdout
    try:
        data = json.loads(result.stdout)
    except ValueError as error:
        raise VisualPlanError(f"Pinned Studio did not return JSON: {result.stdout[:1000]}") from error
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise VisualPlanError(f"Studio query failed: {data}")
    return data


def assert_project(server, project, port=None):
    if (not isinstance(server, dict) or not server.get("projectDir")
            or Path(server["projectDir"]).resolve() != project.resolve()
            or type(server.get("port")) is not int or not 0 < server["port"] < 65536
            or port is not None and server["port"] != port):
        raise VisualPlanError("Studio returned a different project or port; no session was adopted")


def context(cli, project, port, fields="selection", detail="compact"):
    requested = fields.split(",")
    if not requested or set(requested) - {"server", "selection", "lint", "capabilities"}:
        raise VisualPlanError("Studio fields must be server, selection, lint or capabilities")
    if detail not in {"compact", "full"}:
        raise VisualPlanError("Studio detail must be compact or full")
    data = run_cli(cli, project, ["--context", "--json", "--port", str(port),
                                "--context-fields", ",".join(dict.fromkeys(["server", *requested])),
                                "--context-detail", detail])
    assert_project(data.get("server"), project, port)
    return data


def start(cli, project, port=0, *, no_open=False, layout=False):
    help_text = run_cli(cli, project, ["--help"], json_output=False)
    flags = ("--background", "--json", "--context", "--context-fields", "--context-detail", "--stop")
    if any(flag not in help_text for flag in flags):
        raise VisualPlanError("Pinned HyperFrames does not support the required Studio lifecycle/context flags; no legacy fallback was started")
    if not 0 <= port < 65536:
        raise VisualPlanError("Studio port must be between 0 and 65535")
    # Without an explicit port the official CLI reuses this project's running server;
    # a fresh random port would be rejected as a port mismatch.
    arguments = ["--background", "--json", *(["--port", str(port)] if port else [])]
    profile = private_browser_profile(project)
    if no_open:
        arguments.append("--no-open")
    else:
        arguments += ["--browser-path", str(browser_path()), "--user-data-dir", str(profile)]
    if layout:
        arguments.append("--no-proxy")
    data = run_cli(cli, project, arguments)
    session = data.get("result")
    assert_project(session, project)
    url = urlsplit(session.get("studioUrl", ""))
    if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or url.port != session["port"] or unquote(url.fragment) != f"project/{session.get('projectName')}"):
        raise VisualPlanError("Studio did not return a local project URL")
    context(cli, project, session["port"], "server")
    try:
        with build_opener(ProxyHandler({})).open(session["studioUrl"], timeout=10) as response:
            if response.status != 200:
                raise VisualPlanError(f"Studio URL is not ready: HTTP {response.status}")
    except OSError as error:
        raise VisualPlanError(f"Studio URL is not reachable: {error}") from error
    return {**session, "browser_profile": str(profile)}


def stop(cli, project, port):
    context(cli, project, port, "server")
    return run_cli(cli, project, ["--stop", "--json", "--port", str(port)])


def adapt_layout(project):
    """Add only static composition metadata to the disposable review copy."""
    path = project / "index.html"
    text = path.read_text(encoding="utf-8")

    class Canvas(HTMLParser):
        target = None

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if self.target is None and "data-width" in attributes and "data-height" in attributes:
                self.target = (self.getpos(), self.get_starttag_text(), attributes)

    parser = Canvas()
    parser.feed(text)
    if parser.target is None:
        raise VisualPlanError("Static Studio sample needs a data-width/data-height canvas")
    (line, column), tag, attributes = parser.target
    additions = {"data-composition-id": "layout-sample", "data-start": "0", "data-duration": "1"}
    suffix = "".join(f' {key}="{value}"' for key, value in additions.items() if key not in attributes)
    offset = sum(len(part) for part in text.splitlines(keepends=True)[:line - 1]) + column
    insertion = offset + len(tag) - (2 if tag.endswith("/>") else 1)
    path.write_text(text[:insertion] + suffix + text[insertion:], encoding="utf-8")
