"""Headless command-line interface.

This exists before the GUI does, deliberately. It is the standing proof that the analysis
engine has no GUI dependency, and it stays working through every later phase.

    python -m structura.core.cli solve model.stru
    python -m structura.core.cli example T2 --solve
    python -m structura.core.cli list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import examples, io
from .analysis import AnalysisError, AnalysisResult, solve
from .model import Structure
from .units import UnitSystem
from .validation import describe, validate_model


def _load_structure(source: str) -> Structure:
    """Accept either a project file path or an example key such as ``T2``."""
    key = source.upper()
    if key in examples.EXAMPLES:
        return examples.build(key)
    return io.load(source)


def _print_results(structure: Structure, result: AnalysisResult) -> None:
    units = structure.units
    print(f"\n{'=' * 68}")
    print(f"  {structure.name}  -  load case '{result.load_case_name}'")
    print(f"{'=' * 68}")

    _print_reactions(structure, result, units)
    _print_members(result, units)
    _print_checks(result)


def _print_reactions(structure: Structure, result: AnalysisResult, units: UnitSystem) -> None:
    print(f"\nSUPPORT REACTIONS  [{units.force}, {units.moment_unit}]")
    print(f"  {'Node':>6} {'Type':>10} {'Rx':>14} {'Ry':>14} {'Mz':>14}")
    print(f"  {'-' * 62}")
    for node_id in sorted(result.reactions):
        reaction = result.reactions[node_id]
        support = structure.supports[node_id]
        moment = (
            f"{units.moment_from_si(reaction.mz):14.4f}" if reaction.has_moment else f"{'-':>14}"
        )
        print(
            f"  {node_id:>6} {support.type.value:>10} "
            f"{units.force_from_si(reaction.fx):14.4f} "
            f"{units.force_from_si(reaction.fy):14.4f} {moment}"
        )


def _print_members(result: AnalysisResult, units: UnitSystem) -> None:
    print(f"\nMEMBER FORCES  [{units.force}]")
    print(
        f"  {'Mem':>5} {'i':>4} {'j':>4} {'Length':>10} {'Angle':>10} "
        f"{'Axial':>14}  State"
    )
    print(f"  {'-' * 68}")
    for member_id in sorted(result.members):
        m = result.members[member_id]
        print(
            f"  {member_id:>5} {m.node_i:>4} {m.node_j:>4} "
            f"{units.length_from_si(m.length):10.4f} {m.angle_deg:8.2f}  "
            f"{units.force_from_si(m.axial):14.4f}  {m.state_label}"
        )

    tension = len(result.tension_members())
    compression = len(result.compression_members())
    zero = len(result.zero_force_members())
    print(f"\n  {tension} in tension, {compression} in compression, {zero} zero-force")


def _print_checks(result: AnalysisResult) -> None:
    if result.equilibrium is not None:
        status = "PASSED" if result.equilibrium.passed else "FAILED"
        print(f"\nEQUILIBRIUM CHECK: {status}")
        print(f"  {result.equilibrium.summary()}")

    warnings = [d for d in result.diagnostics if not d.is_error]
    if warnings:
        print("\nNOTES")
        for diagnostic in warnings:
            print(f"  {diagnostic}")


def _command_solve(args: argparse.Namespace) -> int:
    structure = _load_structure(args.model)
    try:
        result = solve(structure)
    except AnalysisError as error:
        print(f"\nANALYSIS FAILED\n{error.detail()}", file=sys.stderr)
        return 2
    _print_results(structure, result)
    if args.save is not None:
        io.save(structure, args.save)
        print(f"\nModel written to {Path(args.save).resolve()}")
    return 0


def _command_check(args: argparse.Namespace) -> int:
    structure = _load_structure(args.model)
    issues = validate_model(structure)
    print(describe(issues))
    return 1 if any(issue.is_error for issue in issues) else 0


def _command_list(_args: argparse.Namespace) -> int:
    print("Available validation examples:\n")
    for key in sorted(examples.EXAMPLES):
        title, _builder = examples.EXAMPLES[key]
        print(f"  {key:<4} {title}")
    return 0


def _command_example(args: argparse.Namespace) -> int:
    structure = examples.build(args.key)
    if args.out is not None:
        target = io.save(structure, args.out)
        print(f"Wrote {target}")
    if args.solve:
        return _command_solve(argparse.Namespace(model=args.key, save=None))
    if args.out is None:
        print(io.dumps(structure))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="structura",
        description="Headless 2D structural analysis (truss / beam / frame).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    solve_parser = subparsers.add_parser("solve", help="analyse a model and print results")
    solve_parser.add_argument("model", help="path to a .stru file, or an example key like T2")
    solve_parser.add_argument("--save", help="also write the model to this path")
    solve_parser.set_defaults(func=_command_solve)

    check_parser = subparsers.add_parser("check", help="validate a model without solving it")
    check_parser.add_argument("model", help="path to a .stru file, or an example key")
    check_parser.set_defaults(func=_command_check)

    list_parser = subparsers.add_parser("list", help="list the built-in validation examples")
    list_parser.set_defaults(func=_command_list)

    example_parser = subparsers.add_parser("example", help="emit or solve a built-in example")
    example_parser.add_argument("key", help="example key, e.g. T2 or B6")
    example_parser.add_argument("--out", help="write the example to this .stru path")
    example_parser.add_argument("--solve", action="store_true", help="analyse it as well")
    example_parser.set_defaults(func=_command_example)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        exit_code: int = args.func(args)
    except (io.SchemaError, KeyError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
