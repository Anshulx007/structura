"""PySide6 front end.

Imports ``structura.core``; the core never imports this package. That direction is enforced
by ``tests/test_architecture.py``, which loads the core in a subprocess with every GUI toolkit
poisoned and separately walks the core's AST for banned imports.

Nothing here performs arithmetic on forces. Everything the user sees comes from the core.
"""
