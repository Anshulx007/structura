"""Units and geometry helpers.

Unit mix-ups are the quietest way to be wrong by a factor of 1000, so these conversions get
explicit round-trip and known-value coverage.
"""

from __future__ import annotations

import math

import pytest

from structura.core import geometry
from structura.core.units import DEFAULT, SI, UnitSystem


def test_si_system_is_the_identity() -> None:
    for value in (0.0, 1.0, -12345.678):
        assert SI.force_to_si(value) == value
        assert SI.length_to_si(value) == value
        assert SI.moment_to_si(value) == value
        assert SI.stress_to_si(value) == value
        assert SI.modulus_to_si(value) == value


def test_default_display_units() -> None:
    assert DEFAULT.force_to_si(10.0) == pytest.approx(10_000.0)
    assert DEFAULT.length_to_si(6.0) == pytest.approx(6.0)
    assert DEFAULT.modulus_to_si(200.0) == pytest.approx(2.0e11), "E reads in GPa"
    assert DEFAULT.stress_to_si(250.0) == pytest.approx(2.5e8), "member stress reads in MPa"


def test_modulus_and_stress_are_separate_units() -> None:
    """Same dimension, but 200 GPa and 250 MPa are how each is actually read.

    Sharing one field forces either E to display as 200000 MPa or a member stress as
    0.00025 GPa, and both are unreadable where they appear.
    """
    assert DEFAULT.modulus != DEFAULT.stress
    assert DEFAULT.modulus_from_si(2.0e11) == pytest.approx(200.0)
    assert DEFAULT.stress_from_si(2.5e8) == pytest.approx(250.0)


def test_unknown_modulus_unit_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown modulus"):
        UnitSystem(modulus="bar")


def test_moment_and_distributed_units_derive_from_force_and_length() -> None:
    """Derived units cannot disagree with their bases, which is the point of deriving them."""
    system = UnitSystem(length="mm", force="kN")
    assert system.moment_factor == pytest.approx(1.0e3 * 1.0e-3)
    assert system.distributed_factor == pytest.approx(1.0e3 / 1.0e-3)
    assert system.moment_unit == "kN.mm"
    assert system.distributed_unit == "kN/mm"


@pytest.mark.parametrize("length", ["m", "mm", "cm", "ft", "in"])
@pytest.mark.parametrize("force", ["N", "kN", "MN", "kgf", "lbf", "kip"])
def test_conversions_round_trip(length: str, force: str) -> None:
    system = UnitSystem(length=length, force=force)
    for value in (1.0, -42.5, 1.0e-6, 1.0e9):
        assert system.force_from_si(system.force_to_si(value)) == pytest.approx(value)
        assert system.length_from_si(system.length_to_si(value)) == pytest.approx(value)
        assert system.moment_from_si(system.moment_to_si(value)) == pytest.approx(value)
        assert system.distributed_from_si(
            system.distributed_to_si(value)
        ) == pytest.approx(value)


def test_known_conversion_values() -> None:
    assert UnitSystem(force="kip").force_to_si(1.0) == pytest.approx(4448.2216, rel=1e-6)
    assert UnitSystem(length="ft").length_to_si(1.0) == pytest.approx(0.3048)
    assert UnitSystem(stress="MPa").stress_to_si(1.0) == pytest.approx(1.0e6)
    assert UnitSystem(stress="N/mm2").stress_to_si(250.0) == pytest.approx(2.5e8)


def test_unknown_units_are_rejected_at_construction() -> None:
    for kwargs in ({"length": "furlong"}, {"force": "stone"}, {"stress": "bar"}):
        with pytest.raises(ValueError, match="Unknown"):
            UnitSystem(**kwargs)  # type: ignore[arg-type]


def test_unit_system_dict_round_trip() -> None:
    system = UnitSystem(length="mm", force="N", stress="MPa")
    assert UnitSystem.from_dict(system.to_dict()) == system


def test_formatting_uses_display_units() -> None:
    assert DEFAULT.format_force(12_500.0, decimals=2) == "12.50 kN"
    assert DEFAULT.format_moment(45_000.0, decimals=1) == "45.0 kN.m"
    assert DEFAULT.format_length(6.0, decimals=1) == "6.0 m"


# ---------------------------------------------------------------- geometry


def test_direction_cosines_of_a_3_4_5_triangle() -> None:
    length, c, s = geometry.direction_cosines(0.0, 0.0, 3.0, 4.0)
    assert (length, c, s) == pytest.approx((5.0, 0.6, 0.8))


def test_direction_cosines_reject_degenerate_segments() -> None:
    with pytest.raises(ValueError, match="Degenerate"):
        geometry.direction_cosines(1.0, 1.0, 1.0, 1.0)


@pytest.mark.parametrize(
    ("dx", "dy", "expected"),
    [(1.0, 0.0, 0.0), (0.0, 1.0, 90.0), (-1.0, 0.0, 180.0), (0.0, -1.0, -90.0), (1.0, 1.0, 45.0)],
)
def test_angle_degrees_follows_atan2(dx: float, dy: float, expected: float) -> None:
    assert geometry.angle_deg(0.0, 0.0, dx, dy) == pytest.approx(expected)


def test_rotate_point_is_counter_clockwise_positive() -> None:
    x, y = geometry.rotate_point(1.0, 0.0, math.pi / 2)
    assert (x, y) == pytest.approx((0.0, 1.0), abs=1e-12)


def test_project_point_on_segment_clamps_to_the_ends() -> None:
    t, qx, qy, distance = geometry.project_point_on_segment(2.0, 1.0, 0.0, 0.0, 4.0, 0.0)
    assert (t, qx, qy, distance) == pytest.approx((0.5, 2.0, 0.0, 1.0))

    t, qx, _, _ = geometry.project_point_on_segment(-5.0, 0.0, 0.0, 0.0, 4.0, 0.0)
    assert (t, qx) == pytest.approx((0.0, 0.0))

    t, qx, _, _ = geometry.project_point_on_segment(99.0, 0.0, 0.0, 0.0, 4.0, 0.0)
    assert (t, qx) == pytest.approx((1.0, 4.0))


def test_points_coincide_uses_the_joint_tolerance() -> None:
    assert geometry.points_coincide(0.0, 0.0, 0.0005, 0.0)
    assert not geometry.points_coincide(0.0, 0.0, 0.002, 0.0)


def test_collinearity_detection() -> None:
    assert geometry.is_collinear(0.0, 0.0, 1.0, 1.0, 2.0, 2.0)
    assert not geometry.is_collinear(0.0, 0.0, 1.0, 1.0, 2.0, 2.5)
