"""WSL argv adapter for the same physical root's Windows launcher."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys


PATH_OPTIONS = {"--config", "--appearance-file", "--alignment", "--file", "--brief", "--source", "--output",
                "--project", "--plan", "--body-file", "--exceptions", "--manifest", "--audio",
                "--component", "--binding", "--delivery", "--context-file", "--from", "--to",
                "--root", "--path", "--research-root", "--mapping", "--title-overrides", "--purpose-overrides", "--classification",
                "--refined-project", "--hyperframes-dist", "--approved-component", "--hyperframes-cli", "--browser", "--ffmpeg", "--ffprobe"}
RELATIVE_OPTIONS = {"--audio", "--manifest", "--context-file", "--item", "--sample-dir", "--destination-binding"}


def convert(root, value):
    if re.match(r"^[A-Za-z]:[\\/]", value):
        value = subprocess.check_output(["wslpath", "-u", value], text=True).strip()
    value = value.replace("\\", "/")
    if ":" in value:
        raise ValueError("Unsupported path stream or drive-relative path")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or any(p.is_symlink() for p in (candidate, *candidate.parents)):
        raise ValueError("WSL path escapes the production root or uses a symlink")
    return subprocess.check_output(["wslpath", "-w", str(resolved)], text=True).strip()


def command(root, arguments):
    import argparse
    from work import build_parser
    parser_root = build_parser()
    parsers, options, path_options = [parser_root], set(), set(PATH_OPTIONS)
    def invalid(message):
        raise ValueError(message)
    while parsers:
        parser = parsers.pop()
        parser.allow_abbrev = False
        parser.error = invalid
        options.update(parser._option_string_actions)
        for action in parser._actions:
            if set(action.option_strings) & PATH_OPTIONS:
                path_options.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                parsers.extend(action.choices.values())
    positional_paths = set()
    parsed = None
    if not any(value in {"--help", "-h"} for value in arguments):
        try:
            parsed = parser_root.parse_args(arguments)
        except ValueError:
            parsed = None  # The Windows parser will reject incomplete/invalid invocations.
        if parsed is not None:
            keys = {"path", "draft_file", "final_file"}
            if parsed.command == "request":
                keys.add("revision")
            if parsed.command == "component" and getattr(parsed, "candidate", False):
                keys.add("component")
            positional_paths = {str(getattr(parsed, key)) for key in keys if getattr(parsed, key, None) is not None}
    root = root.resolve()
    result = [convert(root, "work.cmd")]
    previous = None
    relative_options = RELATIVE_OPTIONS | ({"--file"} if "request" in arguments and "freeze" in arguments else set())
    if parsed is not None and parsed.command == "showcase":
        relative_options |= {"--input", "--output"}
    if parsed is not None and parsed.command == "tts" and parsed.tts_command in {"adopt", "audit"}:
        relative_options |= {"--alignment"}
    for argument in arguments:
        if not argument or any(c in argument for c in '\"%!?^&|<>\r\n\x00'):
            raise ValueError("Unsupported cmd metacharacter in argument; use a root-local input file")
        option, separator, value = argument.partition("=")
        if option.startswith("--") and option not in options:
            raise ValueError("Use an exact supported option name; abbreviations are not accepted")
        path_option = option in path_options | relative_options and separator
        candidate = value if separator and option.startswith("--") else argument
        if (option if path_option else previous) in relative_options:
            if Path(candidate).is_absolute() or ".." in Path(candidate).parts or "\\" in candidate or ":" in candidate:
                raise ValueError("This option requires a scoped relative path")
            result.append(argument)
            previous = None
            continue
        if re.match(r"^[A-Za-z]:(?![\\/])", candidate):
            raise ValueError("Drive-relative paths are not supported")
        reference = (option if path_option else previous) in {"--source", "--from"} and (
            re.fullmatch(r"[A-Za-z0-9_.-]+@v[0-9]+", candidate)
            or parsed is not None and parsed.command == 'design' and parsed.design_command == 'new'
                and (option if path_option else previous) == '--from'
            or "variant" in arguments and "add" in arguments and (option if path_option else previous) == "--from")
        path_like = Path(candidate).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", candidate) or candidate.startswith("\\")
        if ".." in Path(candidate.replace("\\", "/")).parts:
            raise ValueError("Path traversal is not supported")
        positional_path = candidate in positional_paths or len(result) >= 3 and result[-2:] == ["root", "set"]
        if not reference and (path_option or previous in path_options or path_like or positional_path):
            converted = convert(root, candidate)
            argument = option + "=" + converted if separator and option.startswith("--") else converted
        result.append(argument)
        previous = option if not separator else None
    if any(any(c in arg for c in '\"%!?^&|<>\r\n\x00') for arg in result):
        raise ValueError("Unsafe Windows command path")
    # WSL interop quotes each argv element; prequoting a command string escapes it twice.
    return ["cmd.exe", "/d", "/s", "/c", "call", *result]


def main(arguments=None):
    try:
        root = Path(__file__).resolve().parent.parent
        argv = command(root, sys.argv[1:] if arguments is None else arguments)
        if not shutil.which(argv[0]):
            fallback = subprocess.check_output(['wslpath', '-u', r'C:\Windows\System32\cmd.exe'], text=True).strip()
            if Path(fallback).is_file():
                argv[0] = fallback
        env = os.environ.copy()
        env['HYPERFRAMES_INVOCATION'] = 'wsl-forwarded'
        forwarded = [entry for entry in env.get('WSLENV', '').split(':')
                     if entry and entry.split('/')[0] != 'HYPERFRAMES_INVOCATION']
        env['WSLENV'] = ':'.join([*forwarded, 'HYPERFRAMES_INVOCATION'])
        return subprocess.run(argv, cwd=root, env=env).returncode
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"work-wsl: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
