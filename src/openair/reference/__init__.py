"""Reference 3D models (scans or CAD meshes) as measured design input.

A reference model is a triangle mesh of an existing aircraft. The ingest
aligns it into the open-air frame, measures schema-ready geometry with
explicit tolerances, renders orthographic silhouettes, and records
provenance. The compare step scores the OpenVSP artifact against the
reference. Reference models are design input, never validation truth.
"""

from openair.reference.ingest import ingest_reference, load_reference_mesh
from openair.reference.compare import compare_reference, reference_dir_for_outdir

__all__ = [
    "compare_reference",
    "ingest_reference",
    "load_reference_mesh",
    "reference_dir_for_outdir",
]
