# Third-party inventory

Status: verified source-only dependency declarations, 2026-11-02; binary/transitive release review pending.
No external runtime packages or binary assets are bundled in this candidate. Swift Foundation/XCTest and Apple SDKs are platform build dependencies, not redistributed. Python uses the installed standard library (PSF terms); Actions use checkout (MIT), pinned to 11d5960a326750d5838078e36cf38b85af677262 in CI, fetched by CI rather than vendored. Swift 6 build-container/base-system distribution notices remain a release review item.

EXTRACTION.json records internal source commits and hashes. Source ownership/contributor grant review remains a release gate; the new license does not override third-party rights. Excluded: Pyodide/MPL, CheerpJ/custom, Linux/SeaBIOS GPL/LGPL guests, PDFium wheels, NumPy/cryptography/Torch/Pillow extras, models, fonts, SDK binaries and mascot art. Embedded CPython under PSF terms is a proposed permissive Python path, not included here.
