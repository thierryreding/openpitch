# 0001: License: GPL-3.0-or-later

- Status: accepted
- Date: 2026-11-08

## Context
OpenPitch is a public, open-source project that will not be monetized. Amateur clubs should
not have to pay large sums for video analysis. Commercial use is fine, but anyone who
changes and distributes the software should have to contribute back: no proprietary forks.

The dependency landscape matters too:
- Ultralytics YOLO (code and pretrained weights) is AGPL-3.0. GPL-2.0-only is not
  compatible with AGPL-3.0. GPL-3.0 is: GPLv3 section 13 and AGPLv3 section 13 explicitly
  allow combining them, and the AGPL terms then apply to the combined work.
- PySide6 is LGPL. That works with any license, but installers need to keep it dynamically
  linked.

## Decision
License the project as GPL-3.0-or-later. Every source file carries
`SPDX-License-Identifier: GPL-3.0-or-later`.

## Consequences
- AGPL-3.0 dependencies (Ultralytics) can be used. They stay optional and isolated behind
  the detector backend (see 0007), so they can be replaced.
- The GPL still allows selling copies and hosting. It does not stop hosted services
  without source (the AGPL would), but an AGPL component pulls its terms into the combined
  work.
- New dependencies, the ffmpeg build bundled in PyAV wheels, model weights and training
  datasets all need a license check before they are adopted or bundled.
