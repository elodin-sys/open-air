# NACA four-digit polar provenance

`polar_points.csv` is a normalized transcription of public wind-tunnel
curves. The columns `x,y` mean angle/CL for `alpha_cl`, angle/Cm(c/4) for
`alpha_cm`, and CL/CD for `cl_cd`.

- NACA 2412 and 4412 are from NACA Report 824, figures 136 and 141. The
  committed values come from Gregory P. D. Siemens' 1994 public-domain
  digitization, mirrored at optiflow commit
  `64a2f26647aaa9a5ab8bdf58ba14dced7814dc8c`.
- NACA 0012 is **not one of the digitized TR-824 figure files** (the archive
  index goes from NACA 0009 to 1408). Its Re=6 million CL and CD curves are
  the NASA Turbulence Modeling Resource digitization of Abbott and von
  Doenhoff. It is retained in this case because the implementation plan
  requires a symmetric four-digit anchor, but the source distinction is
  explicit rather than attributing nonexistent TR-824 figure data.

Derived observations use:

- least-squares CL-alpha fits over `-0.5 <= CL <= 1.0` (NACA 0012 uses
  `-0.8 <= CL <= 0.8`);
- the median Cm(c/4) over `-4 <= alpha <= 8 deg`;
- linear interpolation of the CL-CD curve at CL=0; and
- the largest measured CL on the clean increasing-alpha curve.

The original NACA report is a work of the U.S. Government. The Siemens
digitization declares itself public domain. NASA's 0012 files state that
their digitization is approximate because of the source plot quality.
