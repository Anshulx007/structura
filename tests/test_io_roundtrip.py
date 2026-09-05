"""File format: round-trip fidelity, schema rejection, atomic save."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from structura.core import examples, io
from structura.core.io import SchemaError
from structura.core.model import AnalysisType, Structure, Support

ALL_EXAMPLES = sorted(examples.EXAMPLES)


@pytest.mark.parametrize("key", ALL_EXAMPLES)
def test_round_trip_preserves_the_analysis_relevant_model(key: str) -> None:
    """Every example must survive save and load with an identical content hash."""
    original = examples.build(key)
    restored = io.loads(io.dumps(original))

    assert restored.content_hash() == original.content_hash()
    assert restored.analysis_type is original.analysis_type
    assert len(restored.nodes) == len(original.nodes)
    assert len(restored.members) == len(original.members)
    assert len(restored.supports) == len(original.supports)


@pytest.mark.parametrize("key", ALL_EXAMPLES)
def test_round_trip_is_idempotent(key: str) -> None:
    """Saving a loaded file must reproduce the same bytes — otherwise diffs are noise."""
    once = io.dumps(examples.build(key))
    twice = io.dumps(io.loads(once))
    assert once == twice


def test_round_trip_preserves_load_values_and_directions() -> None:
    original = examples.f3_inclined_member()
    restored = io.loads(io.dumps(original))

    before = original.active_load_case.member_dist[0]
    after = restored.active_load_case.member_dist[0]
    assert after.w1 == before.w1
    assert after.w2 == before.w2
    assert after.direction is before.direction, "load direction must survive the round trip"


def test_round_trip_preserves_material_and_section_properties() -> None:
    original = examples.t5_bars_in_series(area_ratio=3.0)
    restored = io.loads(io.dumps(original))

    for key, section in original.sections.items():
        assert restored.sections[key].area == pytest.approx(section.area)
        assert restored.sections[key].inertia == pytest.approx(section.inertia)
    for key, material in original.materials.items():
        assert pytest.approx(material.E) == restored.materials[key].E


def test_ids_do_not_collide_with_loaded_ones() -> None:
    """After loading, newly created objects must not reuse an id already in the file."""
    restored = io.loads(io.dumps(examples.t2_triangular_truss()))
    existing = set(restored.nodes)

    fresh = restored.add_node(9.0, 9.0)
    assert fresh.id not in existing


def test_save_and_load_from_disk(tmp_path: Path) -> None:
    original = examples.b6_propped_cantilever()
    target = io.save(original, tmp_path / "beam")

    assert target.name == "beam.stru", "a missing suffix should be supplied"
    assert target.exists()
    assert io.load(target).content_hash() == original.content_hash()


def test_saved_file_is_readable_json_in_si_units(tmp_path: Path) -> None:
    """The file stores SI base units; display_units is a UI preference only."""
    structure = examples.b2_ss_udl(span=6.0, w_kn_per_m=10.0)
    target = io.save(structure, tmp_path / "udl.stru")
    data = json.loads(target.read_text(encoding="utf-8"))

    assert data["schema_version"] == io.CURRENT_VERSION
    assert data["display_units"]["force"] == "kN"
    assert data["load_cases"][0]["member"][0]["w1"] == pytest.approx(-10_000.0), (
        "10 kN/m must be stored as -10000 N/m"
    )


def test_serialisation_failure_leaves_the_existing_file_untouched(tmp_path: Path) -> None:
    """Atomic save, part 1: the document is built before anything on disk is disturbed."""
    target = tmp_path / "project.stru"
    io.save(examples.t2_triangular_truss(), target)
    good = target.read_text(encoding="utf-8")

    broken = examples.t2_triangular_truss()
    broken.name = object()  # type: ignore[assignment]

    with pytest.raises(TypeError):
        io.save(broken, target)

    assert target.read_text(encoding="utf-8") == good
    assert not list(tmp_path.glob(".*.tmp")), "no temporary file may be left behind"


def test_interrupted_write_leaves_the_existing_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomic save, part 2: a failure during the swap must not destroy the previous version."""
    target = tmp_path / "project.stru"
    io.save(examples.t2_triangular_truss(), target)
    good = target.read_text(encoding="utf-8")

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr("structura.core.io.project_io.os.replace", explode)

    with pytest.raises(OSError, match="simulated disk failure"):
        io.save(examples.b6_propped_cantilever(), target)

    assert target.read_text(encoding="utf-8") == good, "the original must survive"
    assert not list(tmp_path.glob(".*.tmp")), "the temporary file must be cleaned up"


# ---------------------------------------------------------------- schema rejection


def _minimal_document() -> dict[str, object]:
    return {
        "schema_version": io.CURRENT_VERSION,
        "nodes": [{"id": 1, "x": 0.0, "y": 0.0}, {"id": 2, "x": 1.0, "y": 0.0}],
        "members": [{"id": 1, "i": 1, "j": 2, "material": 1, "section": 1}],
    }


def test_valid_minimal_document_loads() -> None:
    structure = io.loads(json.dumps(_minimal_document()))
    assert len(structure.nodes) == 2
    assert len(structure.members) == 1


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.pop("nodes"), "missing the required top-level key 'nodes'"),
        (lambda d: d.pop("schema_version"), "missing the required top-level key"),
        (lambda d: d.update(schema_version="99.0"), "Unsupported schema version"),
        (lambda d: d["members"][0].pop("j"), "missing the required key 'j'"),
        (lambda d: d["members"][0].update(j=99), "references node 99"),
        (lambda d: d["members"][0].update(j=1), "starts and ends at the same node"),
        (lambda d: d["nodes"].append({"id": 1, "x": 5.0, "y": 5.0}), "Duplicate node id 1"),
        (lambda d: d.update(nodes={}), "'nodes' must be a list"),
        (lambda d: d.update(supports=[{"node": 42}]), "references node 42"),
    ],
)
def test_malformed_documents_are_rejected_with_a_useful_message(
    mutate: object, expected: str
) -> None:
    document = _minimal_document()
    mutate(document)  # type: ignore[operator]
    with pytest.raises(SchemaError, match=expected):
        io.loads(json.dumps(document))


def test_invalid_json_names_the_line() -> None:
    with pytest.raises(SchemaError, match="not valid JSON"):
        io.loads("{ this is not json")


def test_missing_file_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="not found"):
        io.load(tmp_path / "absent.stru")


def test_dangling_load_reference_is_rejected() -> None:
    document = _minimal_document()
    document["load_cases"] = [
        {"id": 1, "name": "LC1", "nodal": [], "member": [{"type": "udl", "member": 77, "w1": -1.0}]}
    ]
    with pytest.raises(SchemaError, match="load on member 77"):
        io.loads(json.dumps(document))


def test_unknown_member_load_type_is_rejected() -> None:
    document = _minimal_document()
    document["load_cases"] = [
        {"id": 1, "name": "LC1", "nodal": [], "member": [{"type": "wat", "member": 1, "w1": -1.0}]}
    ]
    with pytest.raises(ValueError, match="Unknown member load type"):
        io.loads(json.dumps(document))


def test_result_sidecar_path_is_derived_from_the_project_path(tmp_path: Path) -> None:
    assert io.result_path_for(tmp_path / "frame.stru").name == "frame.res.json"


def test_analysis_type_survives_the_round_trip() -> None:
    for structure in (examples.t2_triangular_truss(), examples.b6_propped_cantilever()):
        assert io.loads(io.dumps(structure)).analysis_type is structure.analysis_type


def test_custom_support_pattern_round_trips() -> None:
    s = Structure(analysis_type=AnalysisType.FRAME)
    node = s.add_node(0.0, 0.0)
    other = s.add_node(1.0, 0.0)
    s.add_member(node.id, other.id)
    s.set_support(Support(node.id, ux=False, uy=True, rz=True))

    restored = io.loads(io.dumps(s))
    assert restored.supports[node.id].restraints == (False, True, True)
