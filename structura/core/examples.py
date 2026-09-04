"""Textbook validation structures with known closed-form answers.

These are the models the plan's validation suite is built on. They live in the package rather
than in ``tests/`` so the CLI, the test suite and (later) the GUI's "Open example" menu all
use exactly the same definitions — a discrepancy between what is tested and what ships is
then impossible.

Each builder returns a ``Structure`` in SI base units. The expected results are recorded in
the docstrings and asserted in ``tests/``; the closed-form values themselves are documented in
``docs/conventions.md`` terms (tension-positive axial, sagging-positive moment).
"""

from __future__ import annotations

from collections.abc import Callable

from .model import AnalysisType, Structure, Support

# Convenience magnitudes so the numbers below read like a textbook.
KN = 1.0e3


# ---------------------------------------------------------------- trusses


def t1_two_bar_truss(load_kn: float = 10.0) -> Structure:
    """T1 — symmetric two-bar truss hanging a load.

    A(0, 0) pin, B(3, 0) pin, C(1.5, -2) carrying ``load_kn`` downward.
    Each member has length 2.5 m and sin(theta) = 0.8.

    Expected: both members carry ``0.625 * P`` in **tension**
    (6.25 kN for the default 10 kN load).
    """
    s = Structure(name="T1 two-bar truss", analysis_type=AnalysisType.TRUSS)
    a = s.add_node(0.0, 0.0, "A")
    b = s.add_node(3.0, 0.0, "B")
    c = s.add_node(1.5, -2.0, "C")
    s.add_member(a.id, c.id)
    s.add_member(b.id, c.id)
    s.set_support(Support.pin(a.id))
    s.set_support(Support.pin(b.id))
    s.add_nodal_load(c.id, fy=-load_kn * KN)
    return s


def t2_triangular_truss(load_kn: float = 20.0) -> Structure:
    """T2 — the canonical simply supported triangular truss.

    A(0, 0) pin, B(6, 0) roller, C(3, 4) carrying ``load_kn`` downward.

    Expected for the default 20 kN load:
      * reactions R_A = R_B = 10 kN upward, no horizontal reaction;
      * members AC and BC: 12.5 kN **compression**;
      * member AB: 7.5 kN **tension**.

    Every one of those is reproducible by hand with the method of joints, which is why this
    is the primary Phase-2 gate.
    """
    s = Structure(name="T2 triangular truss", analysis_type=AnalysisType.TRUSS)
    a = s.add_node(0.0, 0.0, "A")
    b = s.add_node(6.0, 0.0, "B")
    c = s.add_node(3.0, 4.0, "C")
    s.add_member(a.id, c.id)
    s.add_member(b.id, c.id)
    s.add_member(a.id, b.id)
    s.set_support(Support.pin(a.id))
    s.set_support(Support.roller_x(b.id))
    s.add_nodal_load(c.id, fy=-load_kn * KN)
    return s


def t3_zero_force_member(load_kn: float = 20.0) -> Structure:
    """T3 — T2 plus an unloaded member forming a T-joint.

    A vertical member is added from the midpoint of the bottom chord up to a new node. With
    no load at the free joint the added members must come out at (numerically) zero force.
    """
    s = Structure(name="T3 zero-force member", analysis_type=AnalysisType.TRUSS)
    a = s.add_node(0.0, 0.0, "A")
    b = s.add_node(6.0, 0.0, "B")
    c = s.add_node(3.0, 4.0, "C")
    d = s.add_node(3.0, 0.0, "D")
    s.add_member(a.id, c.id)
    s.add_member(b.id, c.id)
    s.add_member(a.id, d.id)
    s.add_member(d.id, b.id)
    s.add_member(d.id, c.id)  # the zero-force member
    s.set_support(Support.pin(a.id))
    s.set_support(Support.roller_x(b.id))
    s.add_nodal_load(c.id, fy=-load_kn * KN)
    return s


def t5_bars_in_series(load_kn: float = 30.0, area_ratio: float = 1.0) -> Structure:
    """T5 — two axial bars in series between two pins (one degree indeterminate).

    A(0, 0) pin, B(1, 0), C(3, 0) pin, with a horizontal load ``P`` applied at B. Bar AB is
    1 m long, bar BC is 2 m, so their axial stiffnesses are in the ratio 2:1.

    B carries a roller restraining ``uy`` only: without it the two collinear members would
    leave B free to swing vertically, which is exactly the E5 mechanism.

    Expected with equal areas: **AB = 2P/3 tension**, **BC = P/3 compression**, reactions
    -2P/3 and -P/3. With ``area_ratio = r`` on AB the split becomes ``r/(r + 0.5)`` and
    ``0.5/(r + 0.5)`` — the point of the test being that for an *indeterminate* structure the
    section properties change the member forces, while for a determinate one they cannot.
    """
    s = Structure(name="T5 bars in series", analysis_type=AnalysisType.TRUSS)
    stiff = s.new_section("Stiff", area=1.0e-3 * area_ratio, inertia=1.0e-6)
    a = s.add_node(0.0, 0.0, "A")
    b = s.add_node(1.0, 0.0, "B")
    c = s.add_node(3.0, 0.0, "C")
    s.add_member(a.id, b.id, section_id=stiff.id)
    s.add_member(b.id, c.id)
    s.set_support(Support.pin(a.id))
    s.set_support(Support.pin(c.id))
    s.set_support(Support.roller_x(b.id))
    s.add_nodal_load(b.id, fx=load_kn * KN)
    return s


# ---------------------------------------------------------------- beams


def _simple_beam(name: str, span: float, divisions: int = 2) -> tuple[Structure, list[int]]:
    """Helper: a horizontal frame-mode beam of ``span`` split into ``divisions`` members."""
    s = Structure(name=name, analysis_type=AnalysisType.FRAME)
    node_ids = [s.add_node(span * i / divisions, 0.0).id for i in range(divisions + 1)]
    for i in range(divisions):
        s.add_member(node_ids[i], node_ids[i + 1])
    return s, node_ids


def b1_ss_point_load(span: float = 6.0, load_kn: float = 20.0) -> Structure:
    """B1 — simply supported beam with a central point load.

    Expected: R = P/2 at each support; shear steps from +P/2 to -P/2 at midspan;
    **M_max = P*L/4** (sagging) at midspan.
    """
    s, ids = _simple_beam("B1 SS central point load", span, divisions=2)
    s.set_support(Support.pin(ids[0]))
    s.set_support(Support.roller_x(ids[-1]))
    s.add_nodal_load(ids[1], fy=-load_kn * KN)
    return s


def b2_ss_udl(span: float = 6.0, w_kn_per_m: float = 10.0) -> Structure:
    """B2 — simply supported beam with a full-span UDL.

    Expected: R = wL/2 at each support; shear linear through zero at midspan;
    **M_max = w*L^2/8** (sagging) at midspan, parabolic.
    """
    s, ids = _simple_beam("B2 SS UDL", span, divisions=1)
    s.set_support(Support.pin(ids[0]))
    s.set_support(Support.roller_x(ids[-1]))
    member_id = next(iter(s.members))
    s.add_distributed_load(member_id, -w_kn_per_m * KN)
    return s


def b3_cantilever_point_load(span: float = 4.0, load_kn: float = 15.0) -> Structure:
    """B3 — cantilever fixed at the left end with a point load at the free end.

    Expected: vertical reaction P, reaction moment +P*L (CCW);
    shear constant at P; **bending moment -P*L (hogging) at the fixed end**, zero at the tip.
    """
    s, ids = _simple_beam("B3 cantilever end load", span, divisions=1)
    s.set_support(Support.fixed(ids[0]))
    s.add_nodal_load(ids[-1], fy=-load_kn * KN)
    return s


def b4_cantilever_udl(span: float = 4.0, w_kn_per_m: float = 10.0) -> Structure:
    """B4 — cantilever with a full-span UDL.

    Expected: vertical reaction wL; **bending moment -w*L^2/2 (hogging) at the fixed end**.
    """
    s, ids = _simple_beam("B4 cantilever UDL", span, divisions=1)
    s.set_support(Support.fixed(ids[0]))
    member_id = next(iter(s.members))
    s.add_distributed_load(member_id, -w_kn_per_m * KN)
    return s


def b5_ss_applied_moment(span: float = 6.0, moment_knm: float = 30.0) -> Structure:
    """B5 — simply supported beam with a CCW moment applied at midspan.

    Expected: R = M0/L up at the left, down at the right; the BMD rises to +M0/2, **steps
    down by M0** at midspan to -M0/2, then returns to zero. Conventions §6, check 3.
    """
    s, ids = _simple_beam("B5 SS applied moment", span, divisions=2)
    s.set_support(Support.pin(ids[0]))
    s.set_support(Support.roller_x(ids[-1]))
    s.add_nodal_load(ids[1], mz=moment_knm * KN)
    return s


def b6_propped_cantilever(span: float = 8.0, w_kn_per_m: float = 12.0) -> Structure:
    """B6 — propped cantilever with a full-span UDL. One degree indeterminate.

    Fixed at A (x = 0), roller at B (x = L). Expected:
      * R_B = **3wL/8**, R_A = **5wL/8**;
      * M_A = **-wL^2/8** (hogging);
      * M_max = **9wL^2/128** sagging, at **x = 5L/8**;
      * point of contraflexure at **x = L/4**.

    The richest single beam test in the suite: it exercises indeterminacy, fixed-end forces,
    diagram extrema and root-finding all at once.
    """
    s, ids = _simple_beam("B6 propped cantilever UDL", span, divisions=1)
    s.set_support(Support.fixed(ids[0]))
    s.set_support(Support.roller_x(ids[-1]))
    member_id = next(iter(s.members))
    s.add_distributed_load(member_id, -w_kn_per_m * KN)
    return s


def b7_fixed_fixed_udl(span: float = 8.0, w_kn_per_m: float = 12.0) -> Structure:
    """B7 — both ends encastre, full-span UDL. Three degrees indeterminate.

    Expected: R = wL/2 each; **end moments -wL^2/12** (hogging);
    **midspan moment +wL^2/24** (sagging).
    """
    s, ids = _simple_beam("B7 fixed-fixed UDL", span, divisions=1)
    s.set_support(Support.fixed(ids[0]))
    s.set_support(Support.fixed(ids[-1]))
    member_id = next(iter(s.members))
    s.add_distributed_load(member_id, -w_kn_per_m * KN)
    return s


def b8_two_span_continuous(span: float = 6.0, w_kn_per_m: float = 10.0) -> Structure:
    """B8 — two equal spans, UDL over both. One degree indeterminate.

    Expected: **M_B = -wL^2/8** over the middle support;
    R_A = R_C = **3wL/8**, R_B = **10wL/8**. Reactions sum to 2wL.
    """
    s = Structure(name="B8 two-span continuous", analysis_type=AnalysisType.FRAME)
    a = s.add_node(0.0, 0.0, "A")
    b = s.add_node(span, 0.0, "B")
    c = s.add_node(2 * span, 0.0, "C")
    m1 = s.add_member(a.id, b.id)
    m2 = s.add_member(b.id, c.id)
    s.set_support(Support.pin(a.id))
    s.set_support(Support.roller_x(b.id))
    s.set_support(Support.roller_x(c.id))
    s.add_distributed_load(m1.id, -w_kn_per_m * KN)
    s.add_distributed_load(m2.id, -w_kn_per_m * KN)
    return s


# ---------------------------------------------------------------- frames


def f1_portal_frame(
    height: float = 4.0, span: float = 6.0, load_kn: float = 20.0
) -> Structure:
    """F1 — symmetric two-hinged portal frame with a horizontal load at beam level.

    Expected: both bases share the horizontal load equally, H_A = H_B = **H/2**, and the
    vertical reactions form the resisting couple, V = **H*h/L** (down at the windward base,
    up at the leeward one). The horizontal split follows from symmetry alone, so it holds
    whatever the column stiffness is — a good test that does not depend on E, A or I.
    """
    s = Structure(name="F1 two-hinged portal frame", analysis_type=AnalysisType.FRAME)
    base_left = s.add_node(0.0, 0.0, "A")
    base_right = s.add_node(span, 0.0, "B")
    top_left = s.add_node(0.0, height, "C")
    top_right = s.add_node(span, height, "D")
    s.add_member(base_left.id, top_left.id)
    s.add_member(top_left.id, top_right.id)
    s.add_member(base_right.id, top_right.id)
    s.set_support(Support.pin(base_left.id))
    s.set_support(Support.pin(base_right.id))
    s.add_nodal_load(top_left.id, fx=load_kn * KN)
    return s


def f2_portal_frame_udl(
    height: float = 4.0, span: float = 6.0, w_kn_per_m: float = 10.0
) -> Structure:
    """F2 — the same portal frame carrying a UDL on the beam.

    Expected: symmetric response — equal vertical reactions of wL/2, equal and opposite
    horizontal reactions, and negligible sway.
    """
    s = f1_portal_frame(height, span, load_kn=0.0)
    s.name = "F2 portal frame with beam UDL"
    s.active_load_case.nodal.clear()
    beam_id = sorted(s.members)[1]
    s.add_distributed_load(beam_id, -w_kn_per_m * KN)
    return s


def f3_inclined_member(rise: float = 3.0, run: float = 4.0, w_kn_per_m: float = 10.0) -> Structure:
    """F3 — a single inclined cantilever carrying a projected gravity UDL.

    Exists specifically to catch ``LoadDirection`` mistakes: on a horizontal member all three
    vertical variants coincide, so no beam case can detect them. With
    ``GLOBAL_Y_PROJECTED`` the total applied load must equal ``w * run``, not ``w * length``.
    """
    s = Structure(name="F3 inclined member", analysis_type=AnalysisType.FRAME)
    base = s.add_node(0.0, 0.0)
    tip = s.add_node(run, rise)
    member = s.add_member(base.id, tip.id)
    s.set_support(Support.fixed(base.id))
    s.add_distributed_load(member.id, -w_kn_per_m * KN)
    return s


# ---------------------------------------------------------------- unstable cases


def e1_no_supports() -> Structure:
    """E1 — a truss with no supports at all. Expect three rigid-body modes."""
    s = t2_triangular_truss()
    s.name = "E1 no supports"
    s.supports.clear()
    return s


def e2_parallel_rollers() -> Structure:
    """E2 — three vertical rollers. Reaction count is 3, but nothing resists horizontal load.

    The classic case that a ``m + r = 2j`` determinacy check passes and reality fails.
    """
    s = t3_zero_force_member()
    s.name = "E2 parallel rollers"
    s.supports.clear()
    for node_id in sorted(s.nodes)[:3]:
        s.set_support(Support.roller_x(node_id))
    return s


def e4_single_member_node() -> Structure:
    """E4 — an unsupported truss joint with only one member attached.

    The free joint can swing perpendicular to its single member. Diagnostics must name that
    node, not merely report a singular matrix.
    """
    s = t2_triangular_truss()
    s.name = "E4 single-member joint"
    apex = max(s.nodes, key=lambda nid: s.nodes[nid].y)
    dangling = s.add_node(4.5, 6.0)
    s.add_member(apex, dangling.id)
    return s


def e5_collinear_members() -> Structure:
    """E5 — an unsupported truss joint where both members lie on one line.

    Statically the joint is free to move perpendicular to that line, so the structure is a
    mechanism despite every joint having two members.
    """
    s = Structure(name="E5 collinear joint", analysis_type=AnalysisType.TRUSS)
    a = s.add_node(0.0, 0.0)
    b = s.add_node(3.0, 0.0)
    c = s.add_node(6.0, 0.0)
    s.add_member(a.id, b.id)
    s.add_member(b.id, c.id)
    s.set_support(Support.pin(a.id))
    s.set_support(Support.pin(c.id))
    s.add_nodal_load(b.id, fy=-10.0 * KN)
    return s


EXAMPLES: dict[str, tuple[str, Callable[[], Structure]]] = {
    "T1": ("Two-bar truss", t1_two_bar_truss),
    "T2": ("Triangular truss", t2_triangular_truss),
    "T3": ("Truss with a zero-force member", t3_zero_force_member),
    "T5": ("Bars in series (indeterminate)", t5_bars_in_series),
    "B1": ("SS beam, central point load", b1_ss_point_load),
    "B2": ("SS beam, UDL", b2_ss_udl),
    "B3": ("Cantilever, end point load", b3_cantilever_point_load),
    "B4": ("Cantilever, UDL", b4_cantilever_udl),
    "B5": ("SS beam, applied moment", b5_ss_applied_moment),
    "B6": ("Propped cantilever, UDL", b6_propped_cantilever),
    "B7": ("Fixed-fixed beam, UDL", b7_fixed_fixed_udl),
    "B8": ("Two-span continuous beam, UDL", b8_two_span_continuous),
    "F1": ("Two-hinged portal frame, sway load", f1_portal_frame),
    "F2": ("Portal frame, beam UDL", f2_portal_frame_udl),
    "F3": ("Inclined member, projected UDL", f3_inclined_member),
    "E1": ("Unstable: no supports", e1_no_supports),
    "E2": ("Unstable: parallel rollers", e2_parallel_rollers),
    "E4": ("Unstable: single-member joint", e4_single_member_node),
    "E5": ("Unstable: collinear joint", e5_collinear_members),
}
"""Registry of every example, for the CLI and the GUI's example menu."""


def build(key: str) -> Structure:
    """Build an example by its key, e.g. ``build("T2")``."""
    try:
        _, builder = EXAMPLES[key.upper()]
    except KeyError:
        raise KeyError(
            f"Unknown example {key!r}. Available: {', '.join(sorted(EXAMPLES))}"
        ) from None
    return builder()
