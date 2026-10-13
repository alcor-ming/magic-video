---
name: hyperframes-production-workflow
description: Route the current HyperFrames Work to its stage and load only the necessary contracts.
---

# HyperFrames Work Router

## Locate

Keep the production session cwd at the authorized installation root and read its `AGENTS.md`. Discover this Skill from `.agents/skills/` or read this file explicitly. Native sessions use this root's `work.cmd`; WSL production sessions use `./work-wsl.sh` and verify root identity and invocation with `doctor`. Development sessions use isolated fixtures and never read production Current or configuration. Recovery and output contracts: `docs/PRD/production-session-interface.md`. Foreground creation locates `work current`, then `work list` if unset. Background jobs explicitly bind `--work <id>` and, for production, `--variant <id>`.

Work owns one content goal; peer Variants own their independent production and delivery. A Work may have no Variant while content is prepared. Read `WORK.md`, then the explicitly selected, valid current or sole Variant's `variant.yaml`; never choose `main` from multiple candidates. Resolve Script/Research through `shared_inputs`. Use the selected Variant's frozen mode (`explainer`, `showcase`, `math` or `english`) and appearance. Resume its actual stage in `.studio/workflow.md`. Card production is removed; history may be viewed or explicitly adopted into a supported Variant.

Resolve the selected Variant's live card before Draft, or `variant.yaml.design_snapshot` and `design_files` after Draft. Design cards own their `plan_template`, `brief`, `subjects`, `stages`, `thresholds`, `critic_checks`, `defaults`, `assets` and `exemptions`; do not replace an adopted snapshot with latest `.studio/lines.yaml`. Design identity, account, voice and execution model are independent. New Variants carry `design_live` and read the live card until Draft submission. Older Variants keep their existing frozen or mode/spec contracts until explicitly reselected. `talking_head` remains a Template; report retired or unknown Work types without running retired tools.

Before Script work on a production Work, read its series rules with `work series rules show <series>` (the series id and path are in `work status` `series_rules`); the rules file is `works/<series>/AGENTS.md`, but always read and write it through the CLI by series id, never by guessing from a Work's parent folder. After review, write back only established reusable lessons with `work series rules put <series> --file -` (Markdown on stdin; never leave request or draft files in the WorkStore root) (`work series rules delete <series>` retires them). Retire an unused series with `work series delete <series>`; it refuses while any Work still belongs to it — never delete control-plane files directly. Read effective workflow gates with `work workflow show --json`. Script, Plan and Draft have independent `workflow.human_confirmation` switches, default on; workflow values resolve from series through Work to Variant (Plan/Draft only). Account and design cannot disable a gate. `workflow advance` confirms the exact input hash; changed input needs a new confirmation. `work settings show --json` reports appearance/critic settings, not a second approval authority. Draft review defaults on and is advisory; when enabled, use `critic round` and its evidence/prompt, then record the actual verdict. Missing image-capable review is unverified, never a text-only pass. Review does not block registration or continuation.

After successful official Finalize, the target Variant remains active and editable. Archive is explicit; reopen an archived Variant with `work reopen <Work-ID> --variant-id <Variant-ID>`. Preserve sibling lifecycle, frozen deliveries and append-only aggregate exports. Work aggregation, park/resume, history and storage rules live in `.studio/workflow.md`, not Current.

For asset selection, use `work component list --design <selected-card>` and `component interface <card>/<asset>` to read what the selected card's Variants can use; `usable_by` states the cards allowed to install or bind each row. When an asset binding fails, run the read-only `work --work <id> component trace --account <id>` and report its source/frozen statuses; a missing or changed source with an intact frozen copy is not Work damage. Declare cross-card references on the selected card; localize before editing borrowed content. Card and material-card authoring uses the `hyperframes-design-authoring` skill. Built-in cards are read-only, user cards are editable, and material cards are excluded from design choice. Draft snapshots preserve card files and referenced assets; status/preview report changes. Explicit `variant design-update` preserves project copies and reports assets requiring reinstallation, without accepting a Draft.

## Stage Loading

| Stage | Load only as needed |
|---|---|
| Create, switch, accept, Finalize, archive | Root `AGENTS.md`; `.studio/workflow.md` governance and actual CLI help |
| Content preparation | Script, relevant Research and source/alignment evidence; `.studio/spec/creative.md` |
| Plan | Current Plan, selected Research, selected card `stages.plan` (legacy: `.studio/spec/visual-design.md`), applicable `.studio/recipes/` structural difference and selected asset data |
| Draft | Current Plan and affected sources, selected card or Draft snapshot `stages.draft` (legacy: `.studio/spec/visual-design.md` and `.studio/spec/hyperframes.md`) for implementation and QA |
| Selected assets / helpers | Selected interface card; `.studio/spec/runtime-interfaces.md`; `.studio/spec/hyperframes-assets.md` only for asset wiring |
| Final delivery | Accepted version and provenance; `.studio/workflow.md` Final delivery; `.studio/spec/hyperframes-final.md`; actual CLI help |
| Research registration | `.studio/spec/hyperframes-research.md` |
| Content retrospective | Explicit Work/Variant/publication; `.studio/workflow.md` 内容复盘; `CONTENT_RETRO.template.md`. Use `content link/import/open/check/summary`; Write only `retro/content/` (including import originals) and `content-summary/`. No Work source, Plan, Current or acceptance edits; no network or video export. |
| Visual retrospective | User-designated Work/Variant/Draft; `.studio/workflow.md` 画面复盘与样片记忆; `VISUAL_RETRO.template.md`. Write only retro, sample-library, known-defects and retro-summary; no source, Plan, Current or acceptance changes. User confirms memories in conversation. |
