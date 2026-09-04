"""Coordinate mapping, adaptive grid and snapping.

These modules live under ``structura.gui`` but contain no Qt: they are the arithmetic that
decides where a click lands. Keeping them importable without a toolkit means the behaviour
users actually notice can be tested without a window.
"""

from __future__ import annotations

import math

import pytest

from structura.core import examples
from structura.gui.scene import coords
from structura.gui.scene.grid import MAJOR_EVERY, choose_spacing, grid_lines, snap_value
from structura.gui.scene.snapping import SnapKind, SnapSettings, snap_point

# ---------------------------------------------------------------- coordinates


def test_y_is_flipped_and_x_is_not() -> None:
    """Model +Y is up, scene +Y is down. This is the only sign flip in the program."""
    assert coords.to_scene(6.0, 4.0) == (600.0, -400.0)
    assert coords.to_scene_x(-2.5) == -250.0
    assert coords.to_scene_y(-3.0) == 300.0


@pytest.mark.parametrize(
    ("x", "y"), [(0.0, 0.0), (6.0, 4.0), (-12.5, 3.25), (1e-4, -1e-4), (1e4, 1e4)]
)
def test_coordinate_round_trip_is_exact(x: float, y: float) -> None:
    assert coords.to_model(*coords.to_scene(x, y)) == pytest.approx((x, y))


def test_lengths_convert_without_a_sign_flip() -> None:
    """A length is not a coordinate: it must never pick up the y flip."""
    assert coords.scene_length(2.5) == 250.0
    assert coords.model_length(250.0) == 2.5


# ---------------------------------------------------------------- grid


@pytest.mark.parametrize("view_scale", [0.01, 0.05, 0.1, 0.37, 1.0, 2.0, 13.0, 100.0])
def test_grid_stays_readable_at_every_zoom(view_scale: float) -> None:
    """The whole point of an adaptive grid: never a smear, never a single line."""
    spacing = choose_spacing(view_scale)
    on_screen = spacing.minor_scene * view_scale

    assert on_screen >= 12.0, "grid lines must not be closer than the readability limit"
    assert on_screen < 12.0 * 10, "nor should they be absurdly far apart"


@pytest.mark.parametrize("view_scale", [0.01, 0.1, 1.0, 10.0, 100.0])
def test_grid_steps_are_round_numbers(view_scale: float) -> None:
    """1-2-5 sequence, so the step is always a number an engineer would choose."""
    minor = choose_spacing(view_scale).minor_metres
    mantissa = minor / (10.0 ** math.floor(math.log10(minor)))

    assert mantissa == pytest.approx(1.0) or mantissa == pytest.approx(
        2.0
    ) or mantissa == pytest.approx(5.0), f"unexpected grid step {minor}"


def test_major_lines_are_a_multiple_of_minor() -> None:
    spacing = choose_spacing(1.0)
    assert spacing.major_metres == pytest.approx(spacing.minor_metres * MAJOR_EVERY)


@pytest.mark.parametrize("bad_scale", [0.0, -1.0, float("nan"), float("inf")])
def test_degenerate_view_scale_falls_back_instead_of_dividing_by_zero(bad_scale: float) -> None:
    """A collapsed or not-yet-shown view must not crash drawBackground."""
    spacing = choose_spacing(bad_scale)
    assert spacing.minor_metres > 0.0


def test_grid_label_switches_to_millimetres_when_small() -> None:
    assert choose_spacing(1.0).label().endswith("mm")
    assert choose_spacing(0.01).label().endswith("m")


def test_grid_lines_cover_the_range() -> None:
    assert grid_lines(-1.0, 1.0, 0.5) == pytest.approx([-1.0, -0.5, 0.0, 0.5, 1.0])
    assert grid_lines(0.1, 0.9, 0.5) == pytest.approx([0.5])


def test_grid_lines_refuses_a_pathological_count() -> None:
    """Protects the paint loop from a runaway transform rather than freezing the UI."""
    assert grid_lines(-1e9, 1e9, 1e-6) == []
    assert grid_lines(0.0, 1.0, 0.0) == []


def test_snap_value_rounds_to_the_step() -> None:
    assert snap_value(1.24, 0.5) == pytest.approx(1.0)
    assert snap_value(1.26, 0.5) == pytest.approx(1.5)
    assert snap_value(1.26, 0.0) == 1.26


# ---------------------------------------------------------------- snapping


def test_existing_node_beats_everything() -> None:
    """Silently creating a duplicate joint that looks connected is the worst failure here."""
    s = examples.t2_triangular_truss()
    result = snap_point(s, 0.03, -0.02, tolerance=0.1, grid_step=0.5)

    assert result.kind is SnapKind.NODE
    assert result.node_id == 1
    assert (result.x, result.y) == (0.0, 0.0), "must land exactly on the joint, not near it"


def test_point_on_a_member_is_found() -> None:
    s = examples.t2_triangular_truss()
    result = snap_point(s, 3.0, 0.02, tolerance=0.1, grid_step=0.5)

    assert result.kind is SnapKind.MEMBER
    assert result.member_id == 3
    assert result.y == pytest.approx(0.0)


def test_node_snap_wins_over_member_snap_near_a_joint() -> None:
    """Near a joint both snaps are in range; the joint must win.

    A member hit there would place a new node a few millimetres from the existing one -
    visually identical, structurally a disconnected duplicate.
    """
    s = examples.t2_triangular_truss()
    result = snap_point(s, 0.02, 0.0, tolerance=0.1, grid_step=0.5)

    assert result.kind is SnapKind.NODE
    assert result.node_id == 1

    # With node snapping off the same point legitimately snaps onto the member.
    without_nodes = snap_point(
        s, 0.02, 0.0, tolerance=0.1, grid_step=0.5, settings=SnapSettings(to_nodes=False)
    )
    assert without_nodes.kind is SnapKind.MEMBER


def test_exact_member_endpoint_is_not_reported_as_a_member_hit() -> None:
    """t == 0 or t == 1 is a joint, not a span position."""
    s = examples.t2_triangular_truss()
    result = snap_point(
        s, 0.0, 0.0, tolerance=0.1, grid_step=100.0, settings=SnapSettings(to_nodes=False)
    )
    assert result.kind is not SnapKind.MEMBER


def test_grid_snap_in_open_space() -> None:
    s = examples.t2_triangular_truss()
    result = snap_point(s, 1.23, 2.77, tolerance=0.05, grid_step=0.5)

    assert result.kind is SnapKind.GRID
    assert (result.x, result.y) == pytest.approx((1.0, 3.0))


def test_angle_constraint_gives_a_clean_angle_and_length() -> None:
    """Shift-drag should produce a drawable member, not merely a tidy direction."""
    s = examples.t2_triangular_truss()
    result = snap_point(
        s, 2.1, 0.4, tolerance=0.001, grid_step=0.5,
        anchor=(0.0, 0.0), constrain_angle=True,
    )

    assert result.kind is SnapKind.ANGLE
    length = math.hypot(result.x, result.y)
    angle = math.degrees(math.atan2(result.y, result.x))
    assert length == pytest.approx(2.0), "length snapped to the grid"
    assert angle == pytest.approx(15.0), "direction snapped to 15 degrees"


@pytest.mark.parametrize("target_deg", [0.0, 15.0, 30.0, 45.0, 60.0, 90.0, 180.0, -45.0])
def test_common_angles_are_all_reachable(target_deg: float) -> None:
    s = examples.t2_triangular_truss()
    radians = math.radians(target_deg)
    probe_x, probe_y = 3.0 * math.cos(radians), 3.0 * math.sin(radians)

    result = snap_point(
        s, probe_x, probe_y, tolerance=0.001, grid_step=0.5,
        anchor=(0.0, 0.0), constrain_angle=True,
    )
    got = math.degrees(math.atan2(result.y, result.x))
    assert math.isclose(got, target_deg, abs_tol=1e-6) or math.isclose(
        abs(got - target_deg), 360.0, abs_tol=1e-6
    )


def test_snapping_can_be_turned_off_entirely() -> None:
    s = examples.t2_triangular_truss()
    off = SnapSettings(to_nodes=False, to_members=False, to_grid=False)
    result = snap_point(s, 1.234, 5.678, tolerance=0.5, grid_step=0.5, settings=off)

    assert result.kind is SnapKind.FREE
    assert (result.x, result.y) == (1.234, 5.678)


def test_tolerance_is_respected() -> None:
    s = examples.t2_triangular_truss()
    far = snap_point(s, 0.4, 0.0, tolerance=0.1, grid_step=100.0)
    assert far.kind is not SnapKind.NODE


def test_nearest_node_wins_when_two_are_close() -> None:
    s = examples.t2_triangular_truss()
    apex = s.nodes[3]
    result = snap_point(s, apex.x - 0.01, apex.y, tolerance=5.0, grid_step=0.5)

    assert result.node_id == 3, "the closest joint, not merely the first found"


def test_snap_describe_is_ascii() -> None:
    """Snap text reaches the status bar and the console, which is cp1252."""
    s = examples.t2_triangular_truss()
    for probe in [(0.0, 0.0), (3.0, 0.0), (1.2, 2.7)]:
        text = snap_point(s, *probe, tolerance=0.1, grid_step=0.5).describe()
        assert all(ord(c) < 128 for c in text)
