# Structura

2D structural analysis and drawing application — interactive truss / beam / frame modelling
with matrix stiffness analysis, member force recovery and SFD/BMD generation.

## Layering

```
structura/core   pure Python + NumPy/SciPy. ZERO GUI imports.
structura/gui    PySide6 front end. Imports core; core never imports it.
```

That boundary is enforced by `tests/test_architecture.py`, which imports the core in a
subprocess with every GUI toolkit poisoned, and separately walks the core's AST looking for a
banned import. It is the reason the solver can be validated against textbook answers without
a window ever opening.

## Read this first

**[`docs/conventions.md`](docs/conventions.md)** is a contract, not documentation. Axes, DOF
ordering, sign conventions and units are fixed there, and every formula and test asserts
against it. Do not copy sign conventions from elsewhere into this codebase.

Short version: +X right, +Y up, CCW positive; DOF order `(ux, uy, rz)`; **axial force is
tension-positive**, **bending moment is sagging-positive**; the solver only ever sees SI base
units (N, m, Pa, rad).

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Scaffolding, conventions contract | done |
| 1 | Core model, validation, `.stru` file I/O | done |
| 2 | Truss solver, diagnostics, CLI | done |
| 3 | Drawing canvas (PySide6) | done |
| 4 | Supports, loads, interactive truss analysis | next |
| 5 | Frame element, span loads, analytic diagrams | |
| 6 | SFD/BMD in the GUI | |
| 7 | Visualization polish | |
| 8 | Export and PDF reporting | |

## Install

Core and tests need only NumPy, SciPy and pytest:

```bash
pip install -e .
```

The GUI and reporting phases add their own dependencies:

```bash
pip install -e ".[gui,report,dev]"
```

PySide6 is pinned below 6.9. Anaconda ships `msvcp140.dll` 14.42 next to `python.exe`, and
because Windows searches the executable's own directory first it shadows both the system copy
and the newer one PySide6 bundles; Qt 6.9+ then fails to load with WinError 127. If Qt cannot
start, `python -m structura.gui.app` explains this rather than printing a traceback.

## Run the app

```bash
python -m structura.gui.app
```

Draw with **N** (joint) and **M** (member), select with **S**. Wheel zooms, middle-drag or
space-drag pans, **Ctrl+0** fits. Shift constrains to 15 degree steps and snaps the length to
the grid. File > Open example loads any of the validation structures.

## Run the checks

```bash
python -m pytest
```

```bash
python -m mypy
```

## Validation cases

`structura/core/examples.py` holds the textbook structures the whole test suite is built on,
with their closed-form answers recorded in the docstrings — T1–T5 trusses, B1–B8 beams,
F1–F3 frames, and E1–E5 deliberately unstable models that diagnostics must reject by name.
They live in the package rather than in `tests/` so the test suite, the CLI and the GUI's
example menu all use the same definitions.

```python
from structura.core import examples, io

s = examples.b6_propped_cantilever()   # R_B = 3wL/8, M_A = -wL^2/8, M_max = 9wL^2/128
io.save(s, "beam.stru")
```

## File format

`.stru` is pretty-printed JSON in **SI base units**, with a `schema_version` and a migration
hook. The `display_units` block is a UI preference and carries no numerical meaning.

Analysis results are deliberately not stored in the project file. When written, they go to a
`.res.json` sidecar carrying the model hash they were computed from, so stale results are
detectable instead of silently trusted.
