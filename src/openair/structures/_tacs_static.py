"""Run inside the micromamba `tacs` env. Args: bdf outjson load t E nu rho ys"""

from __future__ import annotations

import json
import sys

from mpi4py import MPI
from tacs import constitutive, elements, functions, pyTACS


def main() -> None:
    bdf, outjson, load_n, t, E, nu, rho, ys = sys.argv[1:9]
    load_n = float(load_n)
    t = float(t)
    E = float(E)
    nu = float(nu)
    rho = float(rho)
    ys = float(ys)

    comm = MPI.COMM_WORLD

    def elem_cb(dvNum, compID, compDescript, elemDescripts, specialDVs, **kwargs):
        prop = constitutive.MaterialProperties(rho=rho, E=E, nu=nu, ys=ys)
        con = constitutive.IsoShellConstitutive(prop, t=t, tNum=0)
        elems = []
        for d in elemDescripts:
            if "QUAD" in d or "quad" in d.lower():
                elems.append(elements.Quad4Shell(None, con))
            else:
                elems.append(elements.Tri3Shell(None, con))
        return elems, [t], None

    fea = pyTACS(bdf, comm)
    fea.initialize(elem_cb)
    problem = fea.createStaticProblem("maneuver")
    # Uniform -z load totaling load_n / 2 (one wing)
    nnodes = fea.getNumOwnedNodes()
    import numpy as np

    F = np.zeros(nnodes * 6)
    fz = -(load_n / 2.0) / max(nnodes, 1)
    F[2::6] = fz
    problem.addLoadToNodes(
        np.arange(nnodes), F.reshape(nnodes, 6), nastranOrdering=False
    )
    problem.addFunction("mass", functions.StructuralMass)
    problem.addFunction("ks_vm", functions.KSFailure, safetyFactor=1.5, ksWeight=80.0)
    problem.solve()
    funcs = {}
    problem.evalFunctions(funcs)
    out = {k: float(np.ravel(v)[0]) for k, v in funcs.items()}
    out["ok"] = True
    out["nnodes"] = int(nnodes)
    try:
        modal = fea.createModalProblem("modal", sigma=0.0, numEigs=6)
        modal.solve()
        eigenvalues = []
        frequencies = []
        for index in range(modal.getNumEigs()):
            eigenvalue, _states = modal.getVariables(index)
            eigenvalue = float(np.real(eigenvalue))
            if eigenvalue > 0.0:
                eigenvalues.append(eigenvalue)
                frequencies.append(float(np.sqrt(eigenvalue) / (2.0 * np.pi)))
        out["modal"] = {
            "ok": bool(frequencies),
            "eigenvalues_rad2_s2": eigenvalues,
            "frequencies_hz": frequencies,
            "boundary_condition": "cantilever root SPC",
            "model": "uniform-property TACS shell wingbox",
        }
    except Exception as exc:
        out["modal"] = {"ok": False, "reason": str(exc)}
    with open(outjson, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)


if __name__ == "__main__":
    main()
