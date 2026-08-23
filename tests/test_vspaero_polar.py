from pathlib import Path

from openair.aero.vspaero_backend import (
    _parse_history_convergence,
    _parse_polar,
)


def test_parse_polar_cltot(tmp_path: Path):
    p = tmp_path / "wing.polar"
    p.write_text(
        "Surface Integration Forces\n"
        "      Beta             Mach             AoA             CLo             CLi            CLtot              CDo              CDi             CDtot            CMytot\n"
        "  0.000000000000   0.149482524715   3.000000000000  -0.0001   0.0068   0.006694136006   0.000175   0.004148   0.004324   -0.001428\n"
    )
    parsed = _parse_polar(p)
    assert abs(parsed["CLtot"] - 0.006694136006) < 1e-12
    assert abs(parsed["Mach"] - 0.149482524715) < 1e-12
    assert abs(parsed["CDtot"] - 0.004324) < 1e-12


def test_parse_history_requires_completed_stable_wake(tmp_path: Path):
    path = tmp_path / "wing.history"

    def row(iteration: int, cl: float, cm: float, l2: float) -> str:
        values = [0.0] * 52
        values[0] = float(iteration)
        values[6] = cl
        values[22] = cm
        values[-3] = l2
        values[-2] = -0.5
        values[-1] = float(iteration)
        return " ".join(str(value) for value in values)

    path.write_text(
        "\n".join(
            [
                row(1, 0.45, -0.08, -0.2),
                row(2, 0.50, -0.10, -0.8),
                row(3, 0.501, -0.1005, -1.3),
                row(4, 0.5005, -0.1002, -1.6),
            ]
        ),
        encoding="utf-8",
    )
    converged = _parse_history_convergence(path, 4)
    assert converged["converged"], converged

    incomplete = _parse_history_convergence(path, 5)
    assert not incomplete["converged"]
    assert not incomplete["criteria"]["iterations_complete"]

    path.write_text(
        "\n".join(
            [
                row(1, 0.45, -0.08, -0.2),
                row(2, 0.50, -0.10, -0.8),
                row(3, 0.501, -0.1005, -1.3),
                row(4, 0.5005, -0.1002, -2.5),
            ]
        ),
        encoding="utf-8",
    )
    early = _parse_history_convergence(path, 5)
    assert early["converged"], early
    assert early["criteria"]["early_residual_convergence"]
