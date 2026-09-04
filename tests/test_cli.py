"""The headless CLI — the standing proof that the engine needs no GUI.

These run the real entry point, so they also guard the output encoding: the CLI must print
plain ASCII, because a Windows console in cp1252 mangles anything else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from structura.core import io
from structura.core.cli import main


def test_solve_an_example_by_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["solve", "T2"]) == 0

    out = capsys.readouterr().out
    assert "SUPPORT REACTIONS" in out
    assert "MEMBER FORCES" in out
    assert "10.0000" in out, "the 10 kN reactions must appear"
    assert "-12.5000" in out, "the 12.5 kN rafter compression must appear"
    assert "7.5000" in out, "the 7.5 kN tie tension must appear"
    assert "EQUILIBRIUM CHECK: PASSED" in out


@pytest.mark.parametrize(
    ("argv", "stream"),
    [
        (["solve", "T2"], "out"),
        (["solve", "E5"], "err"),
        (["solve", "E2"], "err"),
        (["check", "T2"], "out"),
        (["list"], "out"),
    ],
)
def test_output_is_pure_ascii(
    argv: list[str], stream: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A degree sign or em dash here becomes a '?' on a cp1252 console.

    The failure paths matter most: diagnostics are the text a user reads when something has
    gone wrong, and that is the worst moment for the message to be mangled.
    """
    main(argv)
    captured = capsys.readouterr()
    text = captured.out if stream == "out" else captured.err
    offending = {c for c in text if ord(c) > 127}
    assert not offending, f"non-ASCII characters in CLI output: {offending}"


def test_solve_a_file_from_disk(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from structura.core import examples

    target = io.save(examples.t1_two_bar_truss(), tmp_path / "t1.stru")
    assert main(["solve", str(target)]) == 0

    out = capsys.readouterr().out
    assert "6.2500" in out, "both bars carry 6.25 kN tension"
    assert "2 in tension" in out


def test_unstable_model_exits_nonzero_with_a_named_joint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["solve", "E5"]) == 2

    err = capsys.readouterr().err
    assert "ANALYSIS FAILED" in err
    assert "MECHANISM" in err
    assert "node 2" in err, "the diagnostic must name the offending joint"


def test_check_validates_without_solving(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "T2"]) == 0
    assert "No problems found" in capsys.readouterr().out


def test_list_shows_every_example(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0

    out = capsys.readouterr().out
    for key in ("T1", "T2", "B6", "F1", "E5"):
        assert key in out


def test_example_writes_a_project_file(tmp_path: Path) -> None:
    target = tmp_path / "b6.stru"
    assert main(["example", "B6", "--out", str(target)]) == 0

    assert target.exists()
    assert io.load(target).name.startswith("B6")


def test_unknown_example_key_exits_with_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["example", "ZZ"]) == 1
    assert "Unknown example" in capsys.readouterr().err


def test_missing_file_exits_with_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["solve", str(tmp_path / "nope.stru")]) == 1
    assert "not found" in capsys.readouterr().err


def test_frame_model_reports_the_missing_element_clearly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Frame analysis arrives in phase 5; until then the CLI must say so, not crash."""
    with pytest.raises(NotImplementedError, match="phase 5"):
        main(["solve", "B6"])
