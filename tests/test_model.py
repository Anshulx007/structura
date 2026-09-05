"""Model behaviour: id allocation, cascading deletes, geometry, hashing."""

from __future__ import annotations

import math

import pytest

from structura.core import examples
from structura.core.model import AnalysisType, Structure, Support


def test_ids_are_never_reused_after_deletion() -> None:
    """Results are keyed by id: a recycled id would attach old forces to new geometry."""
    s = Structure()
    first = s.add_node(0.0, 0.0)
    second = s.add_node(1.0, 0.0)
    s.delete_node(second.id)
    third = s.add_node(2.0, 0.0)

    assert third.id != second.id
    assert third.id > second.id > first.id


def test_deleting_a_node_cascades_to_members_supports_and_loads() -> None:
    s = examples.t2_triangular_truss()
    apex = max(s.nodes, key=lambda nid: s.nodes[nid].y)
    base = min(s.nodes)

    assert s.members_at_node(apex)
    assert base in s.supports

    s.delete_node(apex)
    assert apex not in s.nodes
    assert not s.members_at_node(apex)
    assert all(load.node_id != apex for load in s.active_load_case.nodal)

    s.delete_node(base)
    assert base not in s.supports
    assert all(base not in m.nodes for m in s.members.values())


def test_deleting_a_member_drops_its_span_loads() -> None:
    s = examples.b2_ss_udl()
    member_id = next(iter(s.members))
    assert s.active_load_case.loads_on_member(member_id)

    s.delete_member(member_id)
    assert not s.active_load_case.loads_on_member(member_id)


def test_member_geometry_matches_conventions() -> None:
    """Local x runs i to j; the angle is atan2(dy, dx) in degrees (conventions §4)."""
    s = Structure()
    a = s.add_node(1.0, 1.0)
    b = s.add_node(4.0, 5.0)
    m = s.add_member(a.id, b.id)

    geo = s.member_geometry(m.id)
    assert geo.length == pytest.approx(5.0)
    assert geo.cos == pytest.approx(0.6)
    assert geo.sin == pytest.approx(0.8)
    assert geo.angle_deg == pytest.approx(math.degrees(math.atan2(4.0, 3.0)))


def test_reversing_a_member_reverses_its_local_axes() -> None:
    s = Structure()
    a = s.add_node(0.0, 0.0)
    b = s.add_node(3.0, 0.0)
    forward = s.add_member(a.id, b.id)
    backward = s.add_member(b.id, a.id)

    assert s.member_geometry(forward.id).cos == pytest.approx(1.0)
    assert s.member_geometry(backward.id).cos == pytest.approx(-1.0)


def test_split_member_inserts_a_joint_and_preserves_total_length() -> None:
    """The truss-mode answer to a mid-span point load."""
    s = examples.t2_triangular_truss()
    bottom = s.find_member(*sorted(s.nodes)[:2])
    assert bottom is not None
    original_length = s.member_length(bottom.id)

    new_node, first, second = s.split_member(bottom.id, 0.25)

    assert bottom.id not in s.members
    assert s.member_length(first.id) == pytest.approx(0.25 * original_length)
    assert s.member_length(second.id) == pytest.approx(0.75 * original_length)
    assert s.node_degree(new_node.id) == 2


def test_split_member_rejects_endpoints() -> None:
    s = examples.t2_triangular_truss()
    member_id = next(iter(s.members))
    for t in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="strictly inside"):
            s.split_member(member_id, t)


def test_support_classification_round_trips() -> None:
    from structura.core.model import SupportType

    assert Support.pin(1).type is SupportType.PIN
    assert Support.roller_x(1).type is SupportType.ROLLER_X
    assert Support.roller_y(1).type is SupportType.ROLLER_Y
    assert Support.fixed(1).type is SupportType.FIXED
    assert Support(1, ux=False, uy=False, rz=True).type is SupportType.CUSTOM
    assert Support(1).is_free


def test_setting_a_free_support_removes_it() -> None:
    s = examples.t2_triangular_truss()
    node_id = min(s.nodes)
    assert node_id in s.supports

    s.set_support(Support(node_id))
    assert node_id not in s.supports


def test_total_restraints_counts_reaction_components() -> None:
    s = examples.t2_triangular_truss()
    assert s.total_restraints == 3  # pin (2) + roller (1)

    s = examples.b7_fixed_fixed_udl()
    assert s.total_restraints == 6


def test_content_hash_tracks_analysis_relevant_changes() -> None:
    """This hash is what stops stale results being displayed as current."""
    s = examples.t2_triangular_truss()
    baseline = s.content_hash()

    assert s.content_hash() == baseline, "hash must be stable across calls"

    s.name = "Renamed"
    assert s.content_hash() == baseline, "the project name does not change the answer"

    node_id = max(s.nodes, key=lambda nid: s.nodes[nid].y)
    s.move_node(node_id, s.nodes[node_id].x, s.nodes[node_id].y + 0.5)
    assert s.content_hash() != baseline, "moving a node must invalidate results"


def test_content_hash_changes_with_section_properties() -> None:
    s = examples.t5_bars_in_series()
    baseline = s.content_hash()
    section = s.sections[next(iter(s.sections))]
    section.area *= 2.0
    assert s.content_hash() != baseline


def test_duplicate_member_detection_ignores_direction() -> None:
    s = Structure()
    a = s.add_node(0.0, 0.0)
    b = s.add_node(1.0, 0.0)
    first = s.add_member(a.id, b.id)
    second = s.add_member(b.id, a.id)

    assert s.duplicate_members() == [(first.id, second.id)]


def test_node_at_finds_within_merge_tolerance() -> None:
    s = Structure()
    node = s.add_node(2.0, 3.0)

    assert s.node_at(2.0, 3.0) is node
    assert s.node_at(2.0 + 1e-6, 3.0) is node
    assert s.node_at(2.1, 3.0) is None


def test_unstable_truss_nodes_flags_dangling_and_collinear_joints() -> None:
    """A cheap pre-check for friendly messages — the null-space test remains authoritative."""
    assert not examples.t2_triangular_truss().unstable_truss_nodes()

    dangling = examples.e4_single_member_node()
    assert dangling.unstable_truss_nodes(), "a one-member joint must be flagged"

    collinear = examples.e5_collinear_members()
    flagged = collinear.unstable_truss_nodes()
    middle = sorted(collinear.nodes)[1]
    assert middle in flagged, "the unsupported collinear joint must be named"


def test_default_material_and_section_are_created_automatically() -> None:
    s = Structure()
    assert s.materials and s.sections and s.load_cases
    member_defaults = s.add_node(0.0, 0.0), s.add_node(1.0, 0.0)
    member = s.add_member(member_defaults[0].id, member_defaults[1].id)
    assert member.material_id == s.default_material_id
    assert member.section_id == s.default_section_id


def test_add_member_rejects_unknown_nodes() -> None:
    s = Structure()
    node = s.add_node(0.0, 0.0)
    with pytest.raises(KeyError):
        s.add_member(node.id, 999)


def test_analysis_type_is_a_model_level_property() -> None:
    assert examples.t2_triangular_truss().analysis_type is AnalysisType.TRUSS
    assert examples.b6_propped_cantilever().analysis_type is AnalysisType.FRAME


def test_bounds_and_characteristic_length() -> None:
    s = examples.t2_triangular_truss()
    assert s.bounds() == (0.0, 0.0, 6.0, 4.0)
    assert s.characteristic_length() == pytest.approx(math.hypot(6.0, 4.0))

    empty = Structure()
    assert empty.characteristic_length() >= 1.0
