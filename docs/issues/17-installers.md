---
title: Coach installers and code signing
labels: decision-needed,packaging
---

- Tooling: PyInstaller vs pyside6-deploy/Nuitka vs Briefcase.
- Code signing: macOS notarization needs a paid Apple developer account. Unsigned Windows installers trigger SmartScreen warnings.
- PySide6 is LGPL: keep it dynamically linked in the bundles.
- Build in CI on Windows/macOS/Linux runners. The coach build is Studio without the gpu extra.
