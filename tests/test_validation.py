"""Model validation: well-formedness errors the user must see before analysis."""

from __future__ import annotations

import pytest

from structura.core import examples
from structura.core.model import (
    AnalysisType,
    MemberDistLoad,
    MemberPointLoad,
    Structure,
    Support,
)
from structura.core.validation import assert_valid, errors_only, validate_model


def codes(structure: Structure) -> set[str]:
    return {issue.code for issue in validate_model(structure)}


@pytest.mark.parametrize("key", sorted(examples.EXAMPLES))
def test_every_example_is_well_formed(key: str) -> None:
    """Even the intentionally unstable E-cases must be well *formed* — instability is a
    structural property, decided numerically, not a malformed model."""
    structure = examples.build(key)
    assert errors_only(validate_model(structure)) == []


def test_zero_length_member_is_an_error() -> None:
    s = Structure()
    a = s.add_node(1.0, 1.0)
    b = s.add_node(1.0, 1.0)
    s.add_member(a.id, b.id)

    assert "ZERO_LENGTH_MEMBER" in codes(s)
    with pytest.raises(ValueError, match="ZERO_LENGTH_MEMBER"):
        assert_valid(s)


def test_duplicate_member_is_an_error() -> None:
    s = Structure()
    a = s.add_node(0.0, 0.0)
    b = s.add_node(3.0, 0.0)
    s.add_member(a.id, b.id)
    s.add_member(b.id, a.id)

    assert "DUPLICATE_MEMBER" in codes(s)


def test_dangling_member_node_is_an_error() -> None:
    s = examples.t2_triangular_truss()
    member = next(iter(s.members.values()))
    member.node_j = 999

    assert "DANGLING_MEMBER_NODE" in codes(s)


def test_missing_section_reference_is_an_error() -> None:
    s = examples.t2_triangular_truss()
    next(iter(s.members.values())).section_id = 404

    assert "MISSING_SECTION" in codes(s)


def test_dangling_support_is_an_error() -> None:
    s = examples.t2_triangular_truss()
    s.supports[999] = Support.pin(999)

    assert "DANGLING_SUPPORT" in codes(s)


def test_orphan_node_is_only_informational() -> None:
    """Drawing a joint before its members is normal — it must not block anything."""
    s = examples.t2_triangular_truss()
    s.add_node(10.0, 10.0)

    assert "ORPHAN_NODE" in codes(s)
    assert errors_only(validate_model(s)) == []


def test_coincident_nodes_warn_but_do_not_block() -> None:
    s = examples.t2_triangular_truss()
    existing = s.nodes[min(s.nodes)]
    twin = s.add_node(existing.x, existing.y)
    other = s.add_node(existing.x + 1.0, existing.y + 1.0)
    s.add_member(twin.id, other.id)

    assert "COINCIDENT_NODES" in codes(s)
    assert errors_only(validate_model(s)) == []


def test_load_beyond_the_member_end_is_an_error() -> None:
    """This is how shortening a member catches an invalidated load instead of misplacing it."""
    s = examples.b2_ss_udl(span=6.0)
    member_id = next(iter(s.members))
    s.active_load_case.member_point.append(MemberPointLoad(member_id, a=9.0, fy=-1000.0))

    assert "LOAD_OUTSIDE_MEMBER" in codes(s)


def test_shortening_a_member_invalidates_a_previously_valid_load() -> None:
    s = examples.b2_ss_udl(span=6.0)
    member_id = next(iter(s.members))
    s.active_load_case.member_point.append(MemberPointLoad(member_id, a=5.0, fy=-1000.0))
    assert errors_only(validate_model(s)) == []

    far_node = max(s.nodes, key=lambda nid: s.nodes[nid].x)
    s.move_node(far_node, 3.0, 0.0)

    assert "LOAD_OUTSIDE_MEMBER" in codes(s)


def test_empty_distributed_load_span_is_an_error() -> None:
    s = examples.b2_ss_udl(span=6.0)
    member_id = next(iter(s.members))
    s.active_load_case.member_dist.append(
        MemberDistLoad(member_id, w1=-1000.0, w2=-1000.0, a=3.0, b=2.0)
    )

    assert "EMPTY_LOAD_SPAN" in codes(s)


def test_dangling_nodal_load_is_an_error() -> None:
    s = examples.t2_triangular_truss()
    s.active_load_case.nodal[0].node_id = 999

    assert "DANGLING_NODAL_LOAD" in codes(s)


def test_dangling_combination_reference_is_an_error() -> None:
    from structura.core.model import LoadCombination

    s = examples.t2_triangular_truss()
    s.add_combination(LoadCombination(1, "C1", {77: 1.5}))

    assert "DANGLING_COMBINATION" in codes(s)


def test_validation_reports_every_problem_not_just_the_first() -> None:
    """The GUI shows a list, so validation must not stop at the first failure."""
    s = Structure(analysis_type=AnalysisType.FRAME)
    a = s.add_node(0.0, 0.0)
    b = s.add_node(0.0, 0.0)
    c = s.add_node(5.0, 0.0)
    s.add_member(a.id, b.id)  # zero length
    s.add_member(a.id, c.id)
    s.add_member(c.id, a.id)  # duplicate
    s.supports[999] = Support.pin(999)  # dangling

    found = codes(s)
    assert {"ZERO_LENGTH_MEMBER", "DUPLICATE_MEMBER", "DANGLING_SUPPORT"} <= found


def test_diagnostics_carry_the_ids_needed_to_select_the_offending_item() -> None:
    """Clicking a message must be able to zoom to the problem — that needs ids on it."""
    s = Structure()
    a = s.add_node(2.0, 2.0)
    b = s.add_node(2.0, 2.0)
    member = s.add_member(a.id, b.id)

    issue = next(i for i in validate_model(s) if i.code == "ZERO_LENGTH_MEMBER")
    assert issue.member_ids == [member.id]
    assert set(issue.node_ids) == {a.id, b.id}
    assert issue.hint


def test_assert_valid_passes_for_a_clean_model() -> None:
    assert_valid(examples.t2_triangular_truss())
    assert_valid(examples.b6_propped_cantilever())
