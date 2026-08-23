"""Low-order 2-D section evaluator and explicit applicability checks."""

from __future__ import annotations

import math
import re

from openair.aero.drag_buildup import section_profile_cd0
from openair.mission.balance import thin_airfoil_props

NACA4_PATTERN = re.compile(r"^\d{4}$")
MIN_ATTACHED_FLOW_REYNOLDS = 500_000.0
DEFAULT_CL_MAX_ASSUMPTION = 1.2


class SectionDomainError(ValueError):
    """Raised when the conceptual section model cannot represent a request."""


def require_naca4(airfoil: str) -> str:
    """Return a canonical four-digit code or raise an actionable refusal."""
    code = str(airfoil).strip()
    if not NACA4_PATTERN.fullmatch(code):
        raise SectionDomainError(
            f"airfoil {airfoil!r} is unsupported: the conceptual section model "
            "accepts only four-digit NACA codes such as '2412'; provide a "
            "four-digit equivalent or an experimental polar adapter"
        )
    return code


def section_domain(airfoil: str, reynolds: float) -> dict[str, object]:
    """Describe whether the model is inside its declared section envelope."""
    code = require_naca4(airfoil)
    reasons: list[str] = []
    if reynolds < MIN_ATTACHED_FLOW_REYNOLDS:
        reasons.append(
            f"Re={reynolds:.0f} is below {MIN_ATTACHED_FLOW_REYNOLDS:.0f}; "
            "laminar-separation bubbles and transition are not modeled"
        )
    return {
        "airfoil": code,
        "reynolds": float(reynolds),
        "supported": not reasons,
        "reasons": reasons,
    }


def evaluate_naca4_section(
    airfoil: str,
    reynolds: float,
    *,
    cl_max_assumption: float = DEFAULT_CL_MAX_ASSUMPTION,
) -> tuple[dict[str, float], dict[str, object]]:
    """Evaluate the section approximations currently used by the design tool.

    The evaluator deliberately exposes assumptions rather than fitting the
    truth cases: thin-airfoil lift/moment, a smooth fully turbulent
    skin-friction drag estimate, and the mission-level plain-wing CLmax.
    """
    domain = section_domain(airfoil, reynolds)
    code = str(domain["airfoil"])
    props = thin_airfoil_props(code)
    thickness = int(code[2:]) / 100.0
    values = {
        "cl_alpha_per_deg": 2.0 * math.pi * math.pi / 180.0,
        "alpha_l0_deg": props["alpha_l0_deg"],
        "cm_ac": props["cm_ac"],
        "cd0": section_profile_cd0(reynolds, thickness),
        "cl_max": float(cl_max_assumption),
        "domain_flagged": 0.0 if domain["supported"] else 1.0,
    }
    return values, domain


__all__ = [
    "DEFAULT_CL_MAX_ASSUMPTION",
    "MIN_ATTACHED_FLOW_REYNOLDS",
    "SectionDomainError",
    "evaluate_naca4_section",
    "require_naca4",
    "section_domain",
]
