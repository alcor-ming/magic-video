"""WorkStore-local configuration; no credentials, server, or second database."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class AccountService:
    def __init__(self, api: Any, root: Path):
        self.api, self.root = api, root
        self.directory = api.runtime_root(root) / "control-plane"

    def get(self, kind: str, identity: str) -> dict:
        if not isinstance(identity, str):
            raise self.api.HarnessError(f"Invalid {kind} identity")
        identity = self.api.validate_id(identity, kind)
        return self.api.read_json(self.directory / kind / f"{identity}.json")

    def put(self, kind: str, identity: str, data: dict) -> dict:
        identity = self.api.validate_id(identity, kind)
        if kind == "series":
            self.api.series_folder(self.root, identity)
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise self.api.HarnessError("Configuration requires a name")
        allowed = {"account": {"name", "theme", "background", "motion", "overrides", "fps", "seed", "ratio", "mode", "design", "captions", "style", "delivery"},
                   "series": {"name", "route", "accounts", "ip", "mode", "design", "spec", "overrides", "workflow", "stages"},
                   "theme": {"name", "ratios", "modes", "tokens"}}[kind]
        if set(data) - allowed:
            raise self.api.HarnessError("Unsupported configuration fields")
        if kind == 'series':
            import workflow_config
            workflow_config.validate(data.get('workflow', {}), 'series')
            workflow_config.recipes({}, 'script', data.get('stages', {}))
        if kind in ("account", "series"):
            self.design(data.get("design"))
            if "overrides" in data:
                self.overrides(data["overrides"], kind)
        if kind == "theme":
            if not isinstance(data.get("ratios"), list) or not data["ratios"] or not all(isinstance(item, str) for item in data["ratios"]) or not set(data["ratios"]).issubset(self.api.RATIOS - {"source"}):
                raise self.api.HarnessError("Theme requires explicit supported ratios")
        if kind == "account":
            self.appearance(data)
        if kind == "series":
            from appearance import check_mode
            check_mode(data.get("mode"), "Series")
            if "spec" in data or data.get("mode") == "math" or data.get("design") == "math":
                raise self.api.HarnessError("The math card and its math-rap spec are retired; choose another design for this series")
            if not isinstance(data.get("accounts", []), list):
                raise self.api.HarnessError("Series accounts must be a list")
            for account in data.get("accounts", []):
                self.get("account", account)
        self.api.runtime_root(self.root).mkdir(parents=True, exist_ok=True)
        with self.api.naming_lock(self.root):
            path = self.directory / kind / f"{identity}.json"
            previous = self.api.read_json(path) if path.exists() else {}
            record = {**data, "id": identity, "revision": previous.get("revision", 0) + 1}
            if previous:
                self.api.write_json(self.directory / kind / "history" / identity / f"{previous['revision']}.json", previous)
            self.api.write_json(path, record)
        return record

    def rules_paths(self, series: str) -> tuple[Path, Path, Path]:
        """(current rules in works/<series>/AGENTS.md, rules history, pre-layout rules file).

        Rules are addressed by series identity; history stays in the control plane.
        """
        series = self.api.validate_id(series, "series")
        if series == "history":
            raise self.api.HarnessError("Series identity 'history' is reserved")
        self.get("series", series)
        folder = self.api.series_folder(self.root, series)
        legacy = self.directory / "series" / series
        if any(path.is_symlink() for path in (folder, folder / "AGENTS.md", legacy, legacy / "AGENTS.md", legacy / "history")):
            raise self.api.HarnessError("Series rules cannot be linked")
        return folder / "AGENTS.md", legacy / "history", legacy / "AGENTS.md"

    def rules_path(self, series: str) -> Path:
        return self.rules_paths(series)[0]

    def adopt_legacy_rules(self, series: str) -> None:
        """Move a pre-layout rules file into the series folder; the caller holds the naming lock."""
        path, _, legacy = self.rules_paths(series)
        if legacy.is_file():
            if path.exists():
                raise self.api.HarnessError(f"Series rules exist in both {legacy} and {path}; keep one")
            path.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(path)

    def get_rules(self, series: str) -> dict:
        path, history, legacy = self.rules_paths(series)
        source = path if path.is_file() or not legacy.is_file() else legacy
        try:
            content = source.read_text(encoding="utf-8") if source.is_file() else None
        except (OSError, UnicodeDecodeError) as error:
            raise self.api.HarnessError(f"Cannot read series rules {source}: {error}") from error
        return {"series": series, "path": str(path), "exists": content is not None,
                "revisions": len(list(history.glob("*.md"))) + (content is not None), "content": content}

    def put_rules(self, series: str, content: str) -> dict:
        if not content.strip():
            raise self.api.HarnessError("Series rules cannot be empty")
        path, history, _ = self.rules_paths(series)
        with self.api.naming_lock(self.root):
            self.adopt_legacy_rules(series)
            previous = path.read_text(encoding="utf-8") if path.is_file() else None
            if previous != content:
                if previous is not None:
                    self.api.atomic_write(history / f"{len(list(history.glob('*.md'))) + 1}.md", previous)
                path.parent.mkdir(parents=True, exist_ok=True)
                self.api.atomic_write(path, content)
        return {**self.get_rules(series), "changed": previous != content, "content": None}

    def delete_rules(self, series: str) -> dict:
        path, history, _ = self.rules_paths(series)
        with self.api.naming_lock(self.root):
            self.adopt_legacy_rules(series)
            previous = path.read_text(encoding="utf-8") if path.is_file() else None
            if previous is not None:
                self.api.atomic_write(history / f"{len(list(history.glob('*.md'))) + 1}.md", previous)
                path.unlink()
        return {**self.get_rules(series), "changed": previous is not None, "content": None}

    def delete_series(self, series: str, works: list[dict]) -> dict:
        """Retire an unreferenced series; the caller holds the naming lock while listing works.

        Configuration history and rules move together into control-plane/deleted, so a later
        series with the same identity starts clean and nothing is hard-deleted.
        """
        series = self.api.validate_id(series, "series")
        if series == "history":
            raise self.api.HarnessError("Series identity 'history' is reserved")
        record = self.get("series", series)
        owners = sorted(row["id"] for row in works if row.get("series") == series)
        if owners:
            raise self.api.HarnessError(f"Series {series} still owns Works: {', '.join(owners)}; move them with work series move first")
        unreadable = sorted(row["id"] for row in works if row.get("error") and row.get("series") is None
                            and (Path(row["path"]) / "WORK.md").exists())
        if unreadable:
            raise self.api.HarnessError(f"Cannot confirm series ownership of unreadable Works: {', '.join(unreadable)}")
        base = self.directory / "series"
        sources = [(base / f"{series}.json", f"{series}.json"),
                   (base / "history" / series, "history"), (base / series, "rules")]
        if any(source.is_symlink() for source, _ in sources):
            raise self.api.HarnessError("Series configuration cannot be linked")
        self.adopt_legacy_rules(series)
        folder = self.api.series_folder(self.root, series)
        if folder.is_dir() and any(child.name != "AGENTS.md" for child in folder.iterdir()):
            raise self.api.HarnessError(f"Series folder still has content besides AGENTS.md: {folder}")
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = self.directory / "deleted" / "series" / f"{series}-r{record.get('revision', 0)}-{stamp}"
        if target.exists():
            raise self.api.HarnessError(f"Deleted series archive already exists: {target}")
        target.mkdir(parents=True)
        for source, name in sources[1:]:
            if source.exists():
                source.replace(target / name)
        if (folder / "AGENTS.md").is_file():
            (target / "rules").mkdir(exist_ok=True)
            (folder / "AGENTS.md").replace(target / "rules" / "AGENTS.md")
        if folder.is_dir():
            folder.rmdir()
        # The live configuration moves last: an interrupted delete still leaves the series visible.
        sources[0][0].replace(target / sources[0][1])
        return {"series": series, "deleted": True, "archive": str(target)}

    def delete_account(self, account: str, works: list[dict]) -> dict:
        """Retire an account no Variant or series references; the caller holds the naming lock.

        Configuration, history and account assets move together into control-plane/deleted,
        so a later account with the same identity starts clean and nothing is hard-deleted.
        """
        account = self.api.validate_id(account, "account")
        if account == "history":
            raise self.api.HarnessError("Account identity 'history' is reserved")
        record = self.get("account", account)
        users = sorted({f"{row['id']}/{variant['id']}" for row in works
                        for variant in row["variants"] if variant.get("account") == account})
        if users:
            raise self.api.HarnessError(f"Account {account} is frozen into Variants: {', '.join(users)}")
        # A folder without WORK.md is not a Work (e.g. materials kept in a series folder).
        unreadable = sorted(row["id"] for row in works if row.get("error") and (Path(row["path"]) / "WORK.md").exists())
        if unreadable:
            raise self.api.HarnessError(f"Cannot confirm account use of unreadable Works: {', '.join(unreadable)}")
        series = sorted(path.stem for path in (self.directory / "series").glob("*.json")
                        if account in (self.api.read_json(path).get("accounts") or []))
        if series:
            raise self.api.HarnessError(f"Account {account} is listed by series: {', '.join(series)}; update their accounts first")
        sources = [(self.directory / "account" / f"{account}.json", f"{account}.json"),
                   (self.directory / "account" / "history" / account, "history"),
                   (self.directory / "account-assets" / account, "assets")]
        if any(source.is_symlink() for source, _ in sources):
            raise self.api.HarnessError("Account configuration cannot be linked")
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = self.directory / "deleted" / "account" / f"{account}-r{record.get('revision', 0)}-{stamp}"
        if target.exists():
            raise self.api.HarnessError(f"Deleted account archive already exists: {target}")
        target.mkdir(parents=True)
        for source, name in sources[1:]:
            if source.exists():
                source.replace(target / name)
        # The live configuration moves last: an interrupted delete still leaves the account visible.
        sources[0][0].replace(target / sources[0][1])
        return {"account": account, "deleted": True, "archive": str(target)}

    def add_cover_character(self, account: str, name: str, image: Path, *, prompt: str, model: str,
                            tool: str | None = None, references=(), replace: bool = False) -> dict:
        """Register one generated character image in the account's cover library, with how it was made."""
        import hashlib
        import json
        import shutil
        from designs import FILE_MAP_KEY
        record = self.get("account", account)
        if not isinstance(name, str) or not FILE_MAP_KEY.fullmatch(name):
            raise self.api.HarnessError("Character name must be 1-40 letters, digits, _ or -")
        for label, value in (("prompt", prompt), ("model", model)):
            if not isinstance(value, str) or not value.strip():
                raise self.api.HarnessError(f"Character registration requires the image {label}")
        image = Path(image).absolute()
        if not image.is_file() or image.is_symlink():
            raise self.api.HarnessError("Character image must be a local file")
        data = image.read_bytes()
        if not png_has_alpha(data):
            raise self.api.HarnessError("Character image must be a PNG with transparency; generate with background: transparent")
        overrides = dict(record.get("overrides") or {})
        cover = dict(overrides.get("cover") or {})
        library = dict(cover.get("characters") or {})
        if name in library and not replace:
            raise self.api.HarnessError(f"Character {name} already exists; pass --replace to point it at the new image")
        missing = [item for item in references if item not in library]
        if missing:
            raise self.api.HarnessError("Unknown reference characters: " + ", ".join(missing))
        sha = hashlib.sha256(data).hexdigest()
        folder = self.directory / "account-assets" / self.api.validate_id(account, "account") / "cover-characters"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{name}-{sha[:12]}.png"
        if not target.exists():
            temporary = target.with_name("." + target.name + ".tmp")
            shutil.copyfile(image, temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != sha:
                temporary.unlink()
                raise self.api.HarnessError("Character image changed while copying")
            temporary.replace(target)
        provenance = {"name": name, "sha256": sha, "tool": tool.strip() if tool and tool.strip() else None, "model": model.strip(), "prompt": prompt,
                      "background": "transparent", "character_style": cover.get("character_style"),
                      "references": {item: library[item]["sha256"] for item in references}}
        target.with_suffix(".json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        library[name] = {"path": str(target), "sha256": sha}
        overrides["cover"] = {**cover, "characters": library}
        saved = self.put("account", account, {**{key: value for key, value in record.items()
                                                 if key not in {"id", "revision"}}, "overrides": overrides})
        return {"account": account, "character": name, **library[name], "provenance": str(target.with_suffix(".json")),
                "revision": saved["revision"]}

    def design(self, identity) -> dict | None:
        if identity is None:
            return None
        from designs import DesignError, require
        try:
            return require(identity)
        except DesignError as error:
            raise self.api.HarnessError(str(error)) from error

    def overrides(self, overrides, kind: str) -> dict:
        from designs import DesignError, layer_values
        try:
            return layer_values(overrides, kind.capitalize())
        except DesignError as error:
            raise self.api.HarnessError(str(error)) from error

    def appearance(self, settings: dict) -> dict:
        from appearance import check_mode, is_asset_appearance, resolve
        from component_harness import ComponentError
        if is_asset_appearance(settings):
            try:
                return resolve(self.root, settings)
            except (ValueError, ComponentError) as error:
                raise self.api.HarnessError(str(error)) from error
        overrides = settings.get("overrides")
        if "background" in settings or (isinstance(overrides, dict) and set(overrides) & {"theme", "background", "motion"}):
            raise self.api.HarnessError("Background and appearance overrides require exact appearance asset references")
        check_mode(settings.get("mode"))
        if "captions" in settings and type(settings["captions"]) is not bool:
            raise self.api.HarnessError("captions require a boolean value")
        if settings.get("captions"):
            raise self.api.HarnessError("Captions require exact Theme and Background assets")
        if settings.get("ratio") not in (None, "16:9", "9:16", "source"):
            raise self.api.HarnessError("Video lines only support 16:9 and 9:16")
        if settings.get("ratio") not in (None, *self.api.RATIOS):
            raise self.api.HarnessError("Unknown ratio")
        if settings.get("theme"):
            theme = self.get("theme", settings["theme"])
            if settings.get("ratio") and settings["ratio"] not in theme["ratios"]:
                raise self.api.HarnessError("Theme does not support the requested ratio")
            return theme
        return {}


def png_has_alpha(data: bytes) -> bool:
    """True for a PNG whose colour type carries alpha or that declares a tRNS transparency chunk."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return False
    if data[25] in (4, 6):
        return True
    position = 8
    while position + 8 <= len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        kind = data[position + 4:position + 8]
        if kind == b"tRNS":
            return True
        if kind in (b"IDAT", b"IEND"):
            return False
        position += 12 + length
    return False


def input_path(api: Any, directory: Path, name: str) -> Path:
    state_path = directory / "variant.yaml"
    if state_path.is_file():
        refs = api.read_json(state_path).get("shared_inputs", {})
        if not isinstance(refs, dict):
            raise api.HarnessError("shared_inputs must be an object")
        if name in refs:
            work = directory.parent.parent.resolve()
            if not isinstance(refs[name], str):
                raise api.HarnessError("Invalid shared input path")
            candidate = work / refs[name]
            path = candidate.resolve()
            if not path.is_relative_to(work) or any(p.is_symlink() for p in (candidate, *candidate.parents) if p.is_relative_to(work)):
                raise api.HarnessError("Shared input escapes Work")
            return path
    return directory / name
