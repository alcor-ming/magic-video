from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from test_work_cli import REPO
import appearance
import asset_contract
import asset_store
import component_harness


def motion_payload():
    slots = {
        "reveal": {"effect": "short-rise", "duration": 0.4, "easing": "ease-out", "opacity_from": 0, "opacity_to": 1, "y": 16, "hide_before": True},
        "exit": {"effect": "fade-out", "duration": 0.3, "easing": "linear", "opacity_from": 1, "opacity_to": 0},
        "emphasis": {"effect": "focus-restore", "duration": 0.2, "restore_duration": 0.2, "easing": "ease-in-out", "color_token": "colors.accent", "outline_width": 3},
        "transition": {"effect": "crossfade", "duration": 0.5, "easing": "linear"},
    }
    reduced = deepcopy(slots)
    reduced["reveal"].update(y=0, duration=0)
    reduced["emphasis"].update(duration=0, restore_duration=0)
    reduced["transition"].update(effect="cut", duration=0)
    return {"capability_version": 2, "slots": slots, "reduced_motion": reduced}


class MotionContractTest(unittest.TestCase):
    def test_v3_effects_and_strict_fields(self):
        metadata = {"kind": "motion", "contract_version": 3, "parameters": {}}
        payload = motion_payload()
        payload["capability_version"] = 3
        payload["slots"]["emphasis"] = {"effect": "pulse", "duration": .5, "easing": "spring"}
        payload["reduced_motion"]["emphasis"] = {"effect": "pulse", "duration": 0, "easing": "linear"}
        for slot, effects in {"reveal": ("pop", "stamp", "wipe", "glitch-in"),
                              "emphasis": ("pulse", "shake", "wobble", "glow"),
                              "exit": ("pop-out", "wipe-out", "glitch-out"),
                              "transition": ("wipe", "push", "glitch-cut")}.items():
            for effect in effects:
                changed = deepcopy(payload)
                preset = {"effect": effect, "duration": .5, "easing": "back-out", "hold_fps": 12}
                if slot in {"reveal", "exit"}:
                    preset.update(opacity_from=0 if slot == "reveal" else 1, opacity_to=1 if slot == "reveal" else 0)
                    changed["reduced_motion"][slot] = {"effect": "fade" if slot == "reveal" else "fade-out",
                        "duration": .1, "easing": "linear", "opacity_from": preset["opacity_from"], "opacity_to": preset["opacity_to"]}
                elif slot == "emphasis":
                    changed["reduced_motion"][slot] = {"effect": effect, "duration": 0, "easing": "linear"}
                    if effect == "glow":
                        preset["color_token"] = changed["reduced_motion"][slot]["color_token"] = "colors.accent"
                changed["slots"][slot] = preset
                with self.subTest(slot=slot, effect=effect):
                    asset_contract.validate_declaration(changed, metadata, Path("."))
                with self.assertRaises(component_harness.ComponentError):
                    asset_contract.validate_declaration(changed, {**metadata, "contract_version": 2}, Path("."))
        for change in (lambda p: p["slots"]["reveal"].update(hold_fps=True),
                       lambda p: p["slots"]["reveal"].update(hold_fps=0),
                       lambda p: p["slots"]["reveal"].update(hold_fps=12.5),
                       lambda p: p["slots"]["emphasis"].update(restore_duration=0),
                       lambda p: p["reduced_motion"]["exit"].update(effect="wipe-out"),
                       lambda p: p["reduced_motion"]["reveal"].update(hold_fps=12),
                       lambda p: p["slots"]["emphasis"].update(scale=float("inf"))):
            changed = deepcopy(payload)
            change(changed)
            with self.assertRaises(component_harness.ComponentError):
                asset_contract.validate_declaration(changed, metadata, Path("."))

    def test_color_resolution_checks_both_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payloads = {"theme": {"tokens": {"colors": {"accent": "#ff2200"}}},
                        "background": {"renderer": "transparent", "parameters": {}}, "motion": motion_payload()}
            closure = []
            for kind, payload in payloads.items():
                (root / f"{kind}.json").write_text(json.dumps(payload))
                closure.append({"ref": kind, "kind": kind, "path": root, "metadata": {
                    "kind": kind, "contract_version": 2 if kind == "motion" else 1,
                    "entry": f"{kind}.json", "parameters": {}}})
            selections = {"theme": {"ref": "theme"}, "background": {"ref": "background"},
                          "motion": {slot: {"asset": {"ref": "motion"}, "entry": slot} for slot in appearance.SLOTS}}
            appearance._resolve_parameters(closure, selections, "16:9", [])
            for group in ("slots", "reduced_motion"):
                payload = motion_payload()
                payload[group]["emphasis"]["color_token"] = "colors.missing"
                (root / "motion.json").write_text(json.dumps(payload))
                with self.subTest(group=group), self.assertRaisesRegex(appearance.AppearanceError, "unresolved"):
                    appearance._resolve_parameters(closure, selections, "16:9", [])
            closure[-1]["metadata"]["contract_version"] = 1
            (root / "motion.json").write_text(json.dumps({"slots": {"exit": {"duration": 0.2, "easing": "linear"}}, "reduced_motion": {}}))
            selections["motion"] = {"reveal": {"asset": {"ref": "motion"}, "entry": "exit"}}
            appearance._resolve_parameters(closure, selections, "16:9", [])

    def test_versions_fields_and_ranges(self):
        metadata = {"kind": "motion", "contract_version": 2, "parameters": {}}
        payload = motion_payload()
        asset_contract.validate_declaration(payload, metadata, Path("."))
        invalid = [
            lambda p: p.update(capability_version=True),
            lambda p: p["slots"]["reveal"].update(opacity_from=-0.1),
            lambda p: p["slots"]["exit"].update(opacity_to=1),
            lambda p: p["slots"]["reveal"].update(scale=-1),
            lambda p: p["slots"]["reveal"].update(stagger=0),
            lambda p: p["slots"]["reveal"].update(hide_before=0),
            lambda p: p["slots"]["reveal"].update(easing="power2.out"),
            lambda p: p["slots"]["emphasis"].update(restore_duration=float("nan")),
            lambda p: p["slots"]["emphasis"].update(color_token="#ff0000"),
            lambda p: p["slots"]["transition"].update(effect="cut"),
            lambda p: p["reduced_motion"].pop("exit"),
            lambda p: p["reduced_motion"]["reveal"].update(y=1),
            lambda p: p["reduced_motion"]["reveal"].update(duration=0.5),
            lambda p: p["reduced_motion"]["exit"].update(duration=0.4),
            lambda p: p["reduced_motion"]["emphasis"].update(duration=1),
            lambda p: p["reduced_motion"]["transition"].update(effect="crossfade"),
        ]
        for change in invalid:
            changed = deepcopy(payload)
            change(changed)
            with self.subTest(payload=changed), self.assertRaises(component_harness.ComponentError):
                asset_contract.validate_declaration(changed, metadata, Path("."))
        for path in ("slots.reveal.effect", "slots.emphasis.color_token", "capability_version"):
            changed = {**metadata, "parameters": {path: {"type": "string", "default": "x"}}}
            with self.assertRaises(component_harness.ComponentError):
                asset_contract.validate_declaration(payload, changed, Path("."))
        with self.assertRaises(component_harness.ComponentError):
            asset_contract.validate_declaration(payload, {**metadata, "contract_version": 1}, Path("."))
        asset_contract.validate_declaration({"slots": {"reveal": {"duration": 1, "easing": "power2.out", "stagger": 0}}, "reduced_motion": {}}, {**metadata, "contract_version": 1}, Path("."))
        for kind, version in (("theme", 2), ("background", 2), ("motion", 4), ("motion", True)):
            with self.subTest(kind=kind, version=version), self.assertRaisesRegex(component_harness.ComponentError, "contract_version"):
                asset_contract._schema2(Path("."), {"kind": kind, "contract_version": version, "parameters": {}, "compatibility": {}})

    def test_real_pack_resolve_materialize_and_offline_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            harness, store, project = (root / name for name in ("harness", "store", "project"))
            harness.mkdir()
            project.mkdir()
            shutil.copyfile(REPO / "windows-runtime.lock.json", harness / "windows-runtime.lock.json")
            with mock.patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": str(store), "HYPERFRAMES_AI_ROOT": str(harness)}):
                account, legacy = {}, {}
                for kind, payload in (("theme", {"tokens": {"colors": {"accent": "#ff2200"}}}), ("background", {"renderer": "transparent", "parameters": {}}), ("motion", motion_payload())):
                    source = root / kind
                    source.mkdir()
                    metadata = {"schema_version": 2, "id": f"test-{kind}", "kind": kind, "version": 1, "contract_version": 2 if kind == "motion" else 1, "parameters": {}, "compatibility": {}, "entry": "entry.json"}
                    if kind == "motion":
                        metadata["parameters"] = {"slots.reveal.duration": {"type": "number", "default": 0.4}, "slots.reveal.hide_before": {"type": "boolean", "default": True}}
                    (source / "asset.json").write_text(json.dumps(metadata))
                    (source / "entry.json").write_text(json.dumps(payload))
                    candidate = asset_store.pack_source(store, source)
                    asset_store.accept_component(store, candidate["component_ref"], candidate["package_sha256"], "Isolated Motion contract test", runtime_root=harness)
                    ref = {"ref": candidate["component_ref"], "kind": kind, "package_sha256": candidate["package_sha256"]}
                    if kind == "motion":
                        legacy = {slot: {"asset": ref, "entry": slot} for slot in appearance.SLOTS}
                    else:
                        account[kind] = ref
                overrides = {"parameters": {"motion": {"reveal": {"slots.reveal.duration": 0, "slots.reveal.hide_before": False}}}}
                for retired in ({**account, "motion": legacy}, account):
                    with self.assertRaisesRegex(appearance.AppearanceError, "Account-level Motion is retired"):
                        appearance.resolve(harness, retired, {} if "motion" in retired else {"motion": legacy})
                # 旧 Work 的冻结锁里已有的四槽动作：只经 legacy_motion 原样带入。
                lock = appearance.resolve(harness, account, overrides, legacy_motion=legacy)
                self.assertEqual((2, 2, 1), tuple(lock[key] for key in ("schema_version", "contract_version", "resolver_version")))
                self.assertEqual(0, lock["parameters"]["motion"]["reveal"]["slots.reveal.duration"])
                self.assertIs(False, lock["parameters"]["motion"]["reveal"]["slots.reveal.hide_before"])
                with self.assertRaisesRegex(appearance.AppearanceError, "selected slot"):
                    appearance.resolve(harness, account, {}, legacy_motion={**legacy, "reveal": {**legacy["reveal"], "entry": "exit"}})
                with self.assertRaisesRegex(appearance.AppearanceError, "Unknown appearance parameter"):
                    appearance.resolve(harness, account, {"parameters": {"motion": {"reveal": {"slots.reveal.unknown": 1}}}}, legacy_motion=legacy)
                disabled = appearance.resolve(harness, account, {"motion": dict.fromkeys(appearance.SLOTS)})
                self.assertEqual(1, disabled["schema_version"])
                appearance.materialize(harness, project, lock)
                original_files = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
                def accepted(name, kind, payload, capability):
                    source = root / name
                    source.mkdir()
                    (source / "asset.json").write_text(json.dumps({"schema_version": 2, "id": name, "version": 1,
                        "kind": kind, "entry": "entry.json", "contract_version": capability, "parameters": {}, "compatibility": {}}))
                    (source / "entry.json").write_text(json.dumps(payload))
                    candidate = asset_store.pack_source(store, source)
                    asset_store.accept_component(store, candidate["component_ref"], candidate["package_sha256"], "Isolated v3 overlay test", runtime_root=harness)
                    return {"ref": candidate["component_ref"], "kind": kind, "package_sha256": candidate["package_sha256"]}
                v3 = motion_payload()
                v3["capability_version"] = 3
                v3["slots"]["emphasis"] = {"effect": "pulse", "duration": .5, "easing": "spring"}
                v3["reduced_motion"]["emphasis"] = {"effect": "pulse", "duration": 0, "easing": "linear"}
                motion3 = accepted("motion3", "motion", v3, 3)
                theme2 = accepted("theme2", "theme", {"tokens": {"colors": {"accent": "#116633"}}}, 1)
                background2 = accepted("background2", "background", {"renderer": "solid", "parameters": {"color": "#ffffff"}}, 1)
                overlay = {"background": background2}
                legacy3 = {**legacy, "emphasis": {"asset": motion3, "entry": "emphasis"}}
                accounts = (account, {**account, "theme": theme2})
                locks = [appearance.resolve(harness, item, overlay, legacy_motion=legacy3) for item in accounts]
                self.assertEqual([item["theme"] for item in accounts], [item["selection"]["theme"] for item in locks])
                self.assertEqual(locks[0]["selection"]["motion"], locks[1]["selection"]["motion"])
                for mixed in locks:
                    self.assertEqual((3, 3), (mixed["schema_version"], mixed["contract_version"]))
                    self.assertEqual(background2, mixed["selection"]["background"])
                    self.assertEqual(legacy["reveal"], mixed["selection"]["motion"]["reveal"])
                full = appearance.resolve(harness, account, {**overlay, "theme": theme2}, legacy_motion=legacy3)
                self.assertEqual(theme2, full["selection"]["theme"])
                new_project = root / "project-v3"
                new_project.mkdir()
                appearance.materialize(harness, new_project, locks[0])
                appearance.verify(new_project, locks[0])
                self.assertEqual(original_files, {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()})
                downgraded = {**lock, "schema_version": 1, "contract_version": 1}
                downgraded["sha256"] = appearance.digest({key: value for key, value in downgraded.items() if key != "sha256"})
                with self.assertRaisesRegex(appearance.AppearanceError, "capability"):
                    appearance.materialize(harness, project, downgraded)
                shutil.rmtree(store)
                appearance.verify(project, lock)
                (project / "appearance-lock.json").write_text(json.dumps(downgraded))
                with self.assertRaisesRegex(appearance.AppearanceError, "capability"):
                    appearance.verify(project, downgraded)


if __name__ == "__main__":
    unittest.main()
