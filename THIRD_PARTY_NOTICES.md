# Third-Party Notices

Magic Video Harness depends on the third-party components below. Versions,
licenses and hashes are taken from the manifests, lock files and license files
listed for each entry. Where a component is installed
by the locked host runtime rather than redistributed in this repository, that is
stated explicitly.

## GSAP (GreenSock Animation Platform)

- Version: `gsap` 3.14.2, including the `CustomEase` and `MotionPathPlugin`
  plugins.
- Not present in this repository or in any design card. GSAP is installed by the
  locked host npm tree (`windows-npm.lock.json`, `windows-runtime.lock.json`)
  into `runtime/npm/node_modules/gsap` during host runtime preparation and is only reached through
  the host runtime.
- License: Standard "No Charge" GSAP License. This is not Apache-2.0 and not
  MIT. Terms: https://gsap.com/community/standard-license/
- The Standard license limits use inside competing visual animation builders.
  Confirm the distributed product form with GreenSock before public promotion.
- The license notice previously carried the source copies: "GSAP 3.14.2,
  Copyright 2025 GreenSock / Webflow."

## HyperFrames

- Version: `hyperframes` 0.8.150 (CLI/runtime, installed by the locked host npm
  tree).
- License: Apache License 2.0. The repository `LICENSE` is the Apache-2.0 text
  and there is no separate upstream `NOTICE` in the local lock data.
- This project is based on HyperFrames (a HeyGen product) and does not claim
  endorsement or affiliation.

## Source Han Sans

- Component: `.studio/fonts/source-han-sans/SourceHanSansCN-{Regular,Bold}.otf`.
- License: SIL Open Font License 1.1. Full text:
  `.studio/fonts/source-han-sans/LICENSE.txt`.
- Copyright 2014-2025 Adobe, with Reserved Font Name "Source". Sources and
  per-file hashes: `.studio/fonts/manifest.json`.

## jsfxr

- Components: `.studio/sfx/vendor/jsfxr/` (jsfxr 1.4.1) and the `jsfxr` 1.4.1
  dependency declared in `.studio/sfx/package.json` / `package-lock.json`.
- License: The Unlicense. Full text:
  `.studio/sfx/vendor/jsfxr/UNLICENSE`. Source and per-file hashes:
  `.studio/sfx/vendor/manifest.json`.

## `.studio/parser` toolchain

Declared in `.studio/parser/package.json` / `package-lock.json`; installed on the
host and not redistributed in this repository:

- `acorn` 8.15.0 - MIT
- `esbuild` 0.28.2, including the `@esbuild/*` platform packages - MIT
- `playwright-core` 1.63.0 - Apache-2.0

## `.studio/sfx` toolchain

Declared in `.studio/sfx/package.json` / `package-lock.json`:

- `jsfxr` 1.4.1 - The Unlicense (see above)

## Locked host npm runtime tree

`windows-npm.lock.json` pins 210 packages installed into `runtime/npm`. The lock
records a license for every entry. They are dominated by permissive licenses
(MIT, Apache-2.0, BSD-3-Clause, ISC, 0BSD, BlueOak-1.0.0, CC0-1.0). The
non-permissive or dual entries are:

- `gsap` 3.14.2 - Standard "No Charge" GSAP License (see above).
- `@img/sharp-libvips-*` 1.3.3 - LGPL-3.0-or-later (native libvips shipped with
  `sharp`).
- `@img/sharp-*` 0.35.4 - Apache-2.0, or Apache-2.0 AND LGPL-3.0-or-later.

## Notes

- Package notices and full license texts in the installed dependency tree remain
  authoritative; this document is an inventory, not a substitute for those texts.
- The complete per-package license list is `windows-npm.lock.json`.
