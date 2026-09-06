# Telescope Simulator — Gaussian Beam Propagation Tool

An interactive desktop tool that models a Gaussian optical beam propagating through a
chain of real (thick, curved) lenses, aimed at students/postdocs in an optics lab as a
lightweight alternative to full optical-design software (Zemax, etc.). This document is
a guide for whoever (human or AI) picks up development next: why the tool is shaped the
way it is, the physics it implements, how the code is organized, and the traps we
already found and fixed.

Current version: **v2.0** (see `TODO.md` for the active worklist).

## Quick start

```
.venv\Scripts\python.exe main.py        # Windows, using the project's venv
```

Dependencies: `numpy`, `pytest`, `PySide6`, `pyqtgraph` (see `requirements.txt`). Run the
physics/unit tests with:

```
.venv\Scripts\python.exe -m pytest telescope_simulator/tests -q
```

## Packaging standalone builds

For handing the tool to someone without a Python/PySide6 setup. Both
platforms share one PyInstaller spec, `packaging/telescope_simulator.spec`
(gated by `sys.platform` where the two builds genuinely differ), so there's
one source of truth instead of near-duplicate config per OS.

`PyInstaller` lives in a separate `requirements-build.txt` (not
`requirements.txt`) on both platforms since it's only needed to produce a
build, not to run/develop/test the app.

### Windows (.exe)

Builds a `--onedir` distribution (a folder of `TelescopeSimulator.exe` +
dependencies, not a single-file exe -- faster startup and more reliable
Qt-plugin loading than `--onefile`):

```
.venv\Scripts\pip.exe install -r requirements-build.txt
.venv\Scripts\pyinstaller.exe packaging\telescope_simulator.spec --noconfirm
```

Output lands in `dist\TelescopeSimulator\`; zip that whole folder to hand it
to someone.

Notes:
- The Windows file-properties version resource (Product Name, File Version,
  Company Name) is generated *inside* `packaging/telescope_simulator.spec`
  from `telescope_simulator/version.py`'s constants — bump `version.py` for
  a release and the packaged .exe's properties follow automatically, no
  second copy to keep in sync.
- No custom icon is set by default. To add one, drop a `.ico` file at
  `packaging/icon.ico` and rebuild — the spec picks it up automatically,
  no spec edits needed.
- The produced .exe is unsigned, so Windows SmartScreen may warn on first
  run for anyone who downloads it from outside this machine — expected for
  an internal lab tool, not a build bug.

### macOS (.dmg)

**Must be run on an actual Mac** — PyInstaller does not cross-compile, so
this cannot be built from the Windows dev machine, and there's no CI set up
for it in this repo. Targets Apple Silicon (arm64) only, matching every Mac
sold since ~2020.

```
chmod +x packaging/build_macos.sh
./packaging/build_macos.sh
```

(assumes a Python 3 environment with the repo's dependencies installable —
e.g. an activated venv on the Mac; this is a separate environment from the
Windows `.venv` above, not something that carries over). The script installs
`requirements.txt` + `requirements-build.txt`, runs the same spec file
(which adds a macOS-only `BUNDLE()` step to produce a proper `.app`), then
wraps it into `dist/TelescopeSimulator-<version>-arm64.dmg` via `hdiutil`
(built into macOS, no extra dependency) — plain drag-to-Applications layout,
no custom background/branding.

Notes:
- No custom icon is set by default. To add one, drop an `.icns` file at
  `packaging/icon.icns` and rebuild.
- The app is unsigned and not notarized, so macOS Gatekeeper will refuse to
  open it with an "unidentified developer" warning for anyone who downloads
  it (the quarantine attribute macOS attaches on download) — right-click →
  Open bypasses it once, or `xattr -cr TelescopeSimulator.app` clears the
  flag. This is macOS's equivalent of the Windows SmartScreen note above,
  not a build bug. Proper notarization needs an Apple Developer account
  ($99/yr) and is out of scope for now.

## Thought process / why it's shaped this way

The brief was: draw the beam and the optics in an interactive x-z plane, let the user
drag optics around, and expose beam parameters in a tabbed side panel — but keep it a
*foundation* that grows incrementally (v0 → v0.2 → …), not a one-shot build. That pushed
three decisions early on:

- **Physics core is a standalone package with no GUI dependency.** `physics/` only
  imports `numpy` and the plain-dataclass `model/`. It's unit-tested against known
  closed-form results *before* any GUI code was written, and every GUI feature since has
  reused it rather than duplicating formulas (see "Reuse, don't re-derive" below).
- **Every v1 physics simplification is a deliberate, documented scope cut, not an
  oversight.** Single wavelength, no dispersion, ambient index fixed at 1.0 (air), tilt
  is cosmetic only (no induced astigmatism), no aperture clipping. These are stated in
  the Config tab's on-screen note and repeated here so nobody "fixes" them by accident
  without realizing the simplification was intentional and load-bearing for the rest of
  the design (e.g. the single-q-parameter-per-segment model in `physics/system.py`
  depends on there being no astigmatism).
- **The GUI shares mutable model objects instead of copying/diffing them.** `Optic` and
  `InputBeamSpec` instances are held by reference by *both* the Optics/Beam tabs and the
  canvas (`PlotView`). Edit a field anywhere and every other view of that same object
  already sees the new value — no synchronization code needed for the data itself, only
  for "please repaint" notifications. This is why the Qt signals in this codebase mostly
  carry *ids*, not *values* (`opticPropertyChanged(optic_id)`, not
  `opticPropertyChanged(optic)`). This was the single biggest design lever for keeping
  the GUI code small; see "Signal conventions" below before changing it.

## The physics

### Complex beam parameter

A Gaussian beam's transverse profile at any point along its axis is fully described by
the complex beam parameter

```
1/q(z) = 1/R(z) - i * lambda0 / (n * pi * w(z)^2)
```

where `lambda0` is vacuum wavelength, `n` the local refractive index, `R(z)` the
wavefront radius of curvature, and `w(z)` the 1/e² intensity radius. Equivalently,
within one homogeneous medium,

```
q(z) = (z - z_waist) + i * zR,        zR = pi * n * w0^2 / lambda0
```

`GaussianBeam` (`physics/beam.py`) is a small value object wrapping `(z_ref, q_ref,
wavelength_nm, n)`. Its `w(z)`/`radius_of_curvature(z)` methods use the second form
above and are valid *anywhere within the same medium* as `z_ref` — not just at a single
point — which is what lets `plot_view.py` sample a smooth curve across an entire air gap
or lens interior from one `GaussianBeam` instance. `w()`/`q_at()` are written with plain
numpy arithmetic so they vectorize over a numpy array of `z` values for free; don't
"optimize" them into scalar-only code.

`GaussianBeam.from_measurement(z_ref, w_ref, wavelength_nm, n, r_ref)` back-calculates
`z_waist`/`w0` from a beam measured *anywhere*, not just at its waist (`r_ref=None`
means flat wavefront, i.e. `z_ref` *is* the waist). This exists because real lab beams
are usually measured at whatever plane a power meter happens to sit at, not at the
waist.

### ABCD ray-transfer matrices

`physics/matrices.py` implements the standard Kogelnik/Siegman generalized ABCD law.
**Convention**: the ray vector is `(y, theta)` with `theta = dy/dz` the *physical* slope
(not a "reduced angle" `n*theta`, which is the other common convention in textbooks —
don't mix the two). Consequences of this choice:

- Free-space propagation over distance `d` is `[[1, d], [0, 1]]` **regardless of
  medium** — no `/n` factor, because `theta` is already the true slope. This surprises
  people who've seen the reduced-angle convention; it's correct here because of the
  matching interface convention below.
- Refraction at a spherical interface, index `n1 -> n2`, radius `R`:
  `[[1, 0], [(n1-n2)/(n2*R), n1/n2]]`. Sign convention: **`R` is positive if the center
  of curvature lies on the +z side of the vertex.** `R = inf` (flat) collapses this to
  `[[1, 0], [0, n1/n2]]`.
- A thick lens is `interface(n_lens->air, R2) @ propagation(thickness) @
  interface(air->n_lens, R1)` (matrix product, rightmost applied first) —
  `matrices.thick_lens(...)`.
- The generalized ABCD law: `q_out = (A*q_in + B) / (C*q_in + D)` at every element,
  chained in z-order (`physics/beam.transform_q`).

**Non-obvious, reusable fact**: for *any* two-surface system with the same index on both
sides (a lens in air), the full system matrix's `C` element equals `-1/EFL` exactly,
independent of thickness — you don't need separate thin-lens vs. thick-lens formulas.
`optics_tab.py`'s effective-focal-length readout computes it as `f = -1/thick_lens(...)[1,0]`
by reusing the *exact same* tested function used for beam propagation, rather than
re-deriving a thick-lens lensmaker formula. **Prefer this pattern**: if you need a new
derived optical quantity, check whether it's already sitting inside the ABCD matrix
before writing new algebra — back focal length (`optics_tab.py`'s BFL readout) is the
same matrix's `-A/C`, no separate formula needed either.

**UI-level R2 sign flip, physics core unaffected**: `Optic.r1`/`Optic.r2` (the model,
save format, and everything in `physics/`) always use the convention above — center of
curvature on the +z side of the vertex is positive — which means the *same* numeric sign
means convex for a front surface but concave for a back surface. Users found this
confusing (R2 in a saved project doesn't read as "convex/concave" the way R1 does), so
`optics_tab.py`'s **Back ROC (R2) spinbox displays and accepts the negated value** —
positive always reads as convex, negative as concave, for both R1 and R2, from the form.
The flip happens only at that one widget's read/write boundary
(`_load_optic_into_form`/`_on_form_value_changed`); `Optic.r2`, `to_dict`/`from_dict`,
`describe_shape()`, `thick_lens()`, and `OpticItem`'s rendering all still use the
original physics-space value, so existing saved project files (e.g. `test_config.json`)
load with unchanged meaning. If you add another place that reads/writes `r2` for
display, remember to flip it there too, or route it through `optics_tab.py` instead of
touching `Optic.r2` directly.

### Validation strategy

The physics is tested against independent closed-form results, not just "does it run":

- `test_matrices.py`: the thick-lens matrix reduces to the thin-lens matrix
  `[[1,0],[-1/f,1]]` with `1/f = (n-1)(1/R1 - 1/R2)` as thickness → 0; a flat-flat
  window of thickness `t`, index `n` is *exactly* (not just in a limit) equivalent to
  propagation over the "reduced thickness" `t/n`; biconcave defaults are confirmed
  diverging.
- `test_beam.py`: `w(z)` matches the textbook formula
  `w0*sqrt(1+(z/zR)^2)`; a beam built analytically from a known waist, then re-measured
  off-waist and fed back through `from_measurement`, recovers the same waist to float
  precision.
- `test_system.py`: a full `OpticalSystem` propagation through a single lens is checked
  against Self (1983), *"Focusing of spherical Gaussian beams,"* Applied Optics 22,
  658 — an independent literature formula, not a self-consistency check against our own
  code.

If you add new physics, add a test that checks it against an *independently derivable*
result (a known limit, a textbook formula, a symmetry argument) — checking a formula
against itself just re-confirms you can transcribe your own algebra correctly.

### Real ray tracing / spherical aberration (v2.0)

`physics/raytrace.py`, `physics/zernike.py`, and `physics/diffraction.py` add an optional
(Config tab, off by default) *geometric* ray-tracing model alongside the Gaussian/ABCD one
above -- real Snell's-law refraction through the same optics, for understanding spherical
aberration, which a paraxial Gaussian beam model cannot represent at all. See "Round 9"
under "Lessons learned" for the full reasoning; the short version:

- The app is strictly axis-aligned with no tilt/decenter (v1.2), so the whole problem is
  rotationally symmetric about z. A ray's optical path length depends only on its pupil
  radius, never azimuth, so a single 2D **meridional ray fan** (`physics/raytrace.py`)
  fully characterizes the system — no 3D skew-ray tracing needed. This one fact is why the
  new engine is a few hundred lines instead of a full lens-design tool.
- Only the rotationally-symmetric ("m=0") Zernike terms — piston, defocus, primary/
  secondary/tertiary spherical aberration — can ever be non-zero; every other standard term
  (coma, astigmatism, trefoil, ...) is *exactly* zero by the symmetry argument, not just
  small. `physics/zernike.py` fits only those terms, directly against the real (rho, OPD)
  samples (pooling both the +rho and -rho branches of the fan) — it deliberately does not
  fabricate synthetic azimuth samples to "fill out" a full 2D fit; see that module's
  docstring for why an earlier draft of this idea was rejected during implementation.
- **The wavefront is referenced to a sphere centred on the target point, not to the target
  plane.** `wavefront_at()` originally reported the optical path difference measured at the
  target *plane*, referenced to the axial ray there. That quantity is easy to compute, and
  it is exactly right at best focus — where every ray is at `r = 0` and the two references
  coincide — which is precisely what made the difference so easy to miss. Away from focus
  they differ by a defocus term in the ratio (distance to target)/(distance to focus), and
  it is the sphere-referenced one that is the pupil phase a Fraunhofer propagation needs.
  A PSF built on the plane-referenced OPD came out steadily too wide with defocus — a factor
  of two by ten Rayleigh ranges out, while still drawing a perfectly plausible pattern the
  whole way. The conversion is `W = OPD_plane + n*(xi^2 - (r - xi)^2)/(2L)` for a ray leaving
  the exit plane at height `xi` and landing at `r` a distance `L` downstream: the first term
  removes the pupil-to-plane path the OPD picked up, the second adds the Fresnel kernel's own
  quadratic. Both vanish at focus. A target at or in front of the exit plane has no such
  reference sphere, so the plane-referenced OPD is reported there instead (nothing diffracts
  from it — `psf_radial_profile` refuses that case outright).
- **"RMS wavefront error" is the wavefront, not the fit residual.** `ZernikeFitResult.rms_mm`
  is the area-weighted RMS of the fitted wavefront over the pupil with piston removed —
  computed from the coefficients via the orthonormal (Noll) rescaling `sqrt(n+1)`, which is
  both cheaper than integrating and independent of how the fan happens to be sampled (the
  samples are uniform in radius, so averaging them directly would weight the pupil centre
  far too heavily). It briefly held the *fit residual* instead, which meant a system with 25
  waves peak-to-valley advertised an RMS of 1e-8 waves: five m=0 terms describe a smooth
  traced wavefront almost exactly, so the residual is always tiny and always looks perfect.
  The residual is still reported, under its own name, as the diagnostic it actually is.
- Total internal reflection stops a ray at the TIR surface (no reflected-path modeling —
  that would make this a non-sequential tracer, a much bigger undertaking). A ray whose
  surface intersection falls outside that optic's clear aperture is vignetted and stops at
  that optic's z, per spec — this is the *first* place aperture clipping appears anywhere
  in this app; the Gaussian/ABCD model still never clips, unchanged.
- **Surfaces in contact** (`SURFACE_CONTACT_TOL_MM`) — a cemented doublet, or any composite
  group laid out with zero spacing — need two things that a sequential tracer does not get
  for free. First, the ray is then *already sitting on* the surface it is about to meet,
  because the previous element's back surface and this one's front surface are the same
  sphere: the intersection parameter comes out at exactly `0`, and a `t > 1e-9` "forward
  only" filter discards it, stopping every ray in the fan — the axial one included — at the
  joint. Nothing there needs protecting against re-finding the surface just left; the trace
  is strictly sequential (front, back, next front) and never asks for the same surface
  twice, so the filter is `t >= 0` (with a picometre of slack for float noise). Second, a
  zero gap is a cemented joint, not an infinitesimally thin sliver of air, so the back
  surface refracts straight into the next glass. Snell's law composes — `n1 sin1 =
  n_air sin_air = n2 sin2` — so the ray direction is identical either way and this changes
  nothing in the ordinary case; what it removes is the detour's ability to
  total-internally-reflect. A 1.85-index element at 44° on the joint is well past the 32.7°
  critical angle for glass-to-air and nowhere near the 76.7° for glass-to-glass, so routing
  it through the ambient index stopped it dead at a surface that does not physically exist.
  The ABCD model has always composed this correctly (`interface(nA,1,R)·interface(1,nB,R)`
  is algebraically `interface(nA,nB,R)`) and has no TIR to get wrong, which is why the two
  models disagreed here and only the ray tracer was visibly broken.
- `physics/diffraction.py`'s PSF is a plain zero-padded `numpy.fft.fft2` of the aberrated,
  rotationally-symmetric pupil, propagated from the fan's **exit plane** (the last optic's
  back vertex, `RayFanResult.exit_plane_z`) over the ray bundle's measured half-width there
  (`WavefrontSample.exit_pupil_radius_mm`) — *not* from the input beam's `z_ref` over the
  fan's launched half-width, which is a plane upstream of every optic and gets the f-number,
  and so the reported Airy null, several times wrong. The approximation that remains is that
  the fitted `W(rho)`, parameterized by *launch* height, is evaluated as if `rho` were the
  exit-pupil coordinate; the two differ only by pupil distortion, which is small for the
  on-axis systems this app models. Still not a rigorous multi-plane Fresnel propagation —
  flagged here so it isn't mistaken for one.
- **The pupil carries the input beam's own Gaussian illumination** (`gaussian_w_norm`), not
  uniform amplitude. `trace_fan` deliberately runs the fan out past the useful beam — 2.5 w
  by default — so that the wavefront is sampled to where there is still light to speak of.
  Treating that whole disk as *filled* is therefore a 2.5x-too-wide aperture: it reported a
  spot roughly half its true width, with textbook Airy rings that a clean Gaussian beam
  simply does not have. Rings do appear once an aperture actually cuts into the beam, which
  is the physically right behaviour and now comes out of the same code path. Note the factor
  of two: `I = |E|^2`, so a 1/e^2 *intensity* radius `w` is `exp(-(rho/w)^2)` in amplitude.
  Because an apodized pupil has no null to quote, `PSFResult` reports a `core_radius_mm`
  measured off the computed profile (where it first falls to 1/e^2 of its peak) alongside the
  hard-aperture `airy_first_null_mm` kept as a reference figure.
- **The azimuthal average reports each annulus at its mean pixel radius**, not at its integer
  bin index. Binning by `rint(hypot(...))` puts pixels 1.0 and 1.414 pixels from the centre
  into the same annulus, whose mean radius is 1.21 — so labelling that bin "1" reports a value
  sampled further out than it claims. On something as sharply peaked as a PSF core that is a
  several-percent error that grows toward the centre, and it draws as a too-tall, too-narrow
  spike sitting on the axis with a ripple beside it. The centre bin holds exactly one pixel,
  so it keeps radius 0 and the true peak; the radius array is simply no longer uniformly
  spaced.
- The FFT's pupil phase has to satisfy Nyquist: past a phase step of pi between neighbouring
  pupil samples the pattern *wraps around silently* and a badly defocused system comes back
  looking near-diffraction-limited again. `psf_radial_profile` therefore treats its
  `grid_size` as a minimum, refining the pupil grid as the wavefront steepens, and raising
  `ValueError` rather than plotting an aliased profile once even `MAX_GRID_SIZE` can't
  sample it. The *padded* size is held fixed (`MAX_PADDED_SIZE`), so refinement is paid for
  out of the zero-padding rather than the FFT, and the cost stays flat (~80 ms) at every
  refinement level instead of reaching ~600 ms — which matters because this sits behind a
  drag. That is the physically right trade too, not a reluctant one: a steeper wavefront
  makes a broader pattern, which needs the image plane sampled over a wider span, not more
  finely. A PSF that can't be computed
  blanks only its own plot — the Zernike terms and wavefront plot beside it are still valid,
  so the Ray Tracing tab keeps showing them.
- `physics/irradiance.py` adds the *other* transverse profile: the geometric irradiance —
  what you would actually see on a card held at the target. Each ray of a dense fan carries
  the power of the annulus it stands for (the input beam's Gaussian irradiance at its launch
  height times `|rho|`), which is accumulated into radial bins and divided by each bin's
  **annulus area**, not its width. A ray is not a point, so each one is spread over the
  ray tube it stands for — the target-plane interval reaching halfway to its neighbours on
  each side — with its power distributed across that tube **in proportion to radius**. That
  weighting is not a smoothing choice, it is what `dP/dr = I(rho) * rho * drho/dr` does:
  only the `rho` factor varies appreciably across one tube, and near the axis it varies a
  lot (the tube at `rho = 2*drho` spans radii differing by 50%). Because tubes tile the
  radius axis exactly, this is the honest piecewise reconstruction of `dP/dr` rather than a
  filter over it — no gaps, no invented energy, narrowing to nothing where rays crowd at a
  caustic, and **exact for a uniformly illuminated fan at any ray count**. It is also
  erf-free and several times cheaper than the Gaussian kernel it replaced. The tube is
  mirrored about `r = 0` (radius is a folded coordinate, so a tube near the axis has part of
  itself on the far side) and normalized per ray, which makes energy conservation structural
  rather than approximate. What comes out is **irradiance
  `I(x, 0)`** — power per unit area, what a card shows — returned as a full slice from `-x`
  through `0` to `+x`, mirrored (exact, by the same rotational symmetry the whole engine
  rests on). It is deliberately *not* the radial power distribution `2*pi*r*I(r)`: the two
  differ by exactly that factor, and the second is zero on axis and peaks in a ring even for
  an ordinary Gaussian spot, so confusing them does not look like a scaling error, it looks
  like a doughnut. Dividing each bin by its annulus area rather than its width is the single
  step that separates them. The two profiles are complementary and neither subsumes
  the other: the diffraction PSF is right at and near best focus, where geometric optics
  predicts an impossible point; this one is right in the defocused/aberrated regime, where
  the visible spot is orders of magnitude larger than the diffraction limit and its shape is
  set purely by where the rays land. The tab shows both, and says so when the geometric spot
  has shrunk below the diffraction core and stopped being the meaningful one.
- **The axial ray is the one place the `|rho|` weight is wrong.** Every other ray shares its
  annulus with its mirror-image partner at `-rho`, so each carries half of
  `I * 2*pi*rho*drho` — proportional to `I * |rho|`. The axial ray has no partner: it stands
  for the central *disc* of radius `drho/2`, whose power is `I * pi * (drho/2)^2`, i.e.
  `I * drho/4` in the same units, **not zero**. "A zero-radius annulus carries no power" is
  true and is the wrong statement about it. Left at zero, that disc is simply missing and the
  innermost bin comes out low by roughly `(drho/2 / bin width)^2` — a dimple sitting exactly
  on the axis of every spot, which is where the eye goes first.
- **The three models are cross-checked against each other**, not only each against its own
  closed form (`tests/test_model_agreement.py`). The Gaussian/ABCD model, the geometric ray
  fan, and the ray-trace -> Zernike -> FFT chain share almost no code, so on a slow, clean
  system they have to land on the same physical number, and both of the errors above showed
  up there as several-tens-of-percent disagreements while every module's own tests still
  passed. The one place they legitimately differ is near focus, where a ray cone grows
  linearly and a real beam grows as `sqrt(1 + (z/zR)^2)` — that gap is asserted too, rather
  than papered over, because asserting agreement there would be asserting a bug into place.
- The Zernike fit and the PSF are both normalized by the radius the *surviving* rays cover,
  never by the fan's launched half-width. With a stop cutting the bundle down, normalizing
  by what was launched fits the polynomial over (say) `rho_norm` in `[0, 0.3]` and then
  extrapolates it out to `1.0` — describing an aperture the light never filled.
- `SystemConfig.ambient_index` (Config tab -> **General properties**, default `1.0`) feeds
  *both* this model and the
  original Gaussian/ABCD one (`physics.system.OpticalSystem`'s `ambient_index` constructor
  argument, defaulting to `1.0` so every pre-v2.0 caller/test is unaffected) — the two
  models stay physically consistent about what medium the system sits in.

## Architecture

```
telescope_simulator/
  physics/        # no GUI/model imports beyond model/ dataclasses; pure numpy
    matrices.py   # ABCD matrix builders
    beam.py       # GaussianBeam value object, transform_q()
    system.py     # OpticalSystem: chains beam + sorted optics -> SystemResult
    optimize.py   # golden-section search for the "optimise lens for
                   # flatness"/"...for focus" Beam-tab buttons; reuses
                   # OpticalSystem.propagate(), never re-derives it
    fit.py        # 2D Nelder-Mead fit of input-beam (z_waist, w0) to
                   # measured data points, for the Fit-to-data tab; reuses
                   # OpticalSystem.propagate() + segment_covering()
    raytrace.py   # v2.0: real (Snell's-law) geometric ray tracing, one
                   # meridional fan; RayFanResult/wavefront_at()
    zernike.py    # v2.0: m=0-only Zernike fit of the wavefront error map
    diffraction.py  # v2.0: FFT-based diffraction PSF from the fitted wavefront
    irradiance.py   # v2.0: geometric "what's on the card" transverse intensity,
                   # the PSF's counterpart away from best focus
  model/          # plain dataclasses + JSON (de)serialization, no physics, no Qt
    optics.py     # Optic, OpticKind, make_default_optic() presets
    beam_spec.py  # InputBeamSpec
    config.py     # SystemConfig (display/view settings, saved per-project)
    fit_data.py   # FitDataPoint (one Fit-to-data table row)
    project.py    # Project (beam + optics + config + fit_data_points),
                   # save()/load(), demo project
  gui/            # PySide6 + pyqtgraph
    main_window.py    # QMainWindow; the *only* place that wires tabs <-> plot_view
    plot_view.py      # interactive x-z canvas (pg.PlotWidget subclass)
    optic_item.py     # one draggable pg.GraphicsObject per Optic (true lens sag shape)
    lens_geometry.py  # build_lens_polygon(optic): the sag-shape polygon math, shared by
                       # optic_item.py's canvas rendering and the Add-optic dialog's preview
    widget_utils.py   # mm_spin()/wrap_row() shared by optics_tab.py and the dialog below
    color_utils.py    # wavelength -> RGB approximation
    mm_axis.py        # custom pg.AxisItem: um/mm/m/km unit-aware tick labels
    theme.py          # light/dark Qt palette + pyqtgraph background switching
    app_settings.py   # tiny app-level prefs file (currently just dark_mode), NOT
                       # part of Project — deliberately independent of any saved file
    dialogs/
      add_optic_dialog.py  # "Add optic" popup (single optic / composite group modes),
                            # live construction-diagram preview, edge/center-thickness
                            # coupling -- the first QDialog in this codebase
    tabs/
      beam_tab.py      # input beam form + input/output/target characteristics panels
      optics_tab.py    # optics list (one row per optic or composite group),
                        # property form / group summary, EFL readout
      config_tab.py    # view/aspect/annotation/ray-tracing/dark-mode/about settings
      fit_data_tab.py  # measured (z, diameter) table + "fit input beam" button
      raytrace_tab.py  # v2.0: the fan's ray count and last-recompute timing, plus
                        # Zernike/wavefront analysis and both transverse profiles
                        # (geometric + diffraction) at a pinned target, shown once
                        # the Config tab's ray-tracing model is enabled
  tests/          # pytest; physics + a few pure-function GUI utilities (color_utils)
version.py        # hardcoded APP_VERSION/APP_BUILD_DATE/APP_AUTHOR/APP_ORGANISATION,
                   # shown in the Config tab's About section; bump by hand each release
```

`main.py` is the only entry point (`QApplication` + `MainWindow`).

### Signal conventions

`main_window.py` is the *only* place that connects one widget's signal to another
widget's slot. Tabs and `PlotView` never talk to each other directly — this keeps any
one file (e.g. `optics_tab.py`) understandable without having to know who else is
listening. When adding a new interaction, wire it through `MainWindow._wire_signals()`,
not by reaching into another widget from inside a tab.

Because model objects are shared by reference (see above), most signals are
notifications, not data carriers:

- `opticPropertyChanged(optic_id: int)` / `opticsListChanged()` — "re-sync your view of
  the optics list/an optic's fields", not "here are the new values".
- `opticMoved(optic_id, z, x)` / `opticSelected(optic_id)` — canvas → tabs, so the
  Optics tab's form can mirror a drag or a canvas click without the canvas needing to
  know anything about form widgets.
- `targetChanged(TargetInfo)` is the one exception that *does* carry a payload
  (`plot_view.TargetInfo`: z, the governing `GaussianBeam`, a segment label, and
  pinned/tracking state) — there's no shared mutable object to point at for "whatever
  the mouse is currently hovering", so it has to be pushed.

If a change to one field should trigger a *lot* of downstream recomputation (e.g. a
config change touching both the view range and the beam curve), prefer emitting the
existing coarse-grained signal and letting the receiver re-derive everything from the
shared `Project`, rather than growing a signal's parameter list.

### GUI implementation notes

- **Optic rendering** (`optic_item.py`) draws the *true* spherical sag of each surface
  (`z = R - sign(R)*sqrt(R^2 - x^2)`, vertex-relative, clamped to the clear aperture) as
  a filled polygon — not a schematic lens icon. This is what makes plano/bi-convex/
  concave all "just work" from `R1`/`R2` alone with no per-kind special-casing in the
  renderer.
- **Dragging** uses pyqtgraph's scene-level `mouseClickEvent`/`mouseDragEvent`
  convention (the same one `pg.ROI` uses), *not* standard Qt
  `QGraphicsItem.mousePressEvent`. This is what makes an item's own drag handling take
  priority over the `ViewBox`'s built-in pan gesture. Drag deltas are computed via
  `ViewBox.mapSceneToView` on the *fixed* scene press-position, not via the item's own
  local coordinates — computing it the other way creates a feedback loop once the item's
  own transform starts moving mid-drag (we hit this exact class of bug once; don't
  reintroduce it).
- **Click/drag vs. background clicks**: the target-location pin feature
  (`plot_view._on_scene_mouse_clicked`) has to distinguish "user clicked an optic" from
  "user clicked empty plot space" using `ev.isAccepted()` — an `OpticItem` (or the pin
  marker itself) accepts the event in its own handler, so the background handler must
  check for that and bail out rather than also firing.
- **Axis units** (`mm_axis.py`): pyqtgraph's built-in auto-SI-prefix feature naively
  prepends a metric prefix onto whatever unit string you gave it (`"mm"` → `"kmm"` when
  zoomed out), because it doesn't know `"mm"` is already non-base. `MMAxisItem`
  disables that (`autoSIPrefix = False`) and does its own unit-aware conversion instead
  — all data stays in mm internally, only tick-label formatting changes.
- **Dark mode** is intentionally *not* part of `SystemConfig`/`Project` — it lives in
  `app_settings.py`, a tiny separate JSON file in the user's home directory, so opening
  a colleague's saved project file never flips your theme.

## Known limitations (intentional, not bugs)

Documented in-app (Config tab) and repeated here so they aren't "discovered" and
half-fixed without addressing the whole thing:

- Single wavelength, no dispersion (constant refractive index per optic, no glass
  catalog).
- Ambient index configurable (Config tab, default `1.0` = air) as of v2.0, but still a
  single value applied uniformly everywhere between/around all optics — not a per-region
  medium.
- Strictly axis-aligned as of v1.2 — there is no transverse offset or tilt anywhere in
  the model (`InputBeamSpec.x_offset` and `Optic.x`/`angle_deg` were removed outright,
  not just hidden). There is intentionally only one `q` per segment (not separate
  tangential/sagittal), consistent with normal-incidence propagation. The v2.0
  ray-tracing model leans on this same fact for its rotational-symmetry simplification
  (see "Real ray tracing / spherical aberration (v2.0)" above) — reintroducing tilt would
  require generalizing *both* the Gaussian model (see below) *and* the ray tracer to a
  full 3D treatment.
- The Gaussian/ABCD model has no aperture clipping/vignetting — its beam envelope is
  drawn regardless of whether it exceeds an optic's clear aperture. The v2.0 ray-tracing
  model *does* clip (a ray outside the clear aperture is vignetted) — this is a
  deliberate difference between the two models, not an inconsistency to "fix".
- Positions are global-coordinate: an `Optic.z` is its **front-surface vertex**
  position, not "distance from the previous element."
- The v2.0 ray-tracing model only ever reports total internal reflection as a ray
  stop point — it does not trace the reflected path onward.
- The beam envelope and ray fan are drawn all the way to the canvas edges, in both
  directions, and re-extend on every pan/zoom. That is not the model running further —
  each segment's `GaussianBeam` and each `RaySegment`'s line are analytic and exact
  outside the range a particular `propagate()` bounded them to, exactly as
  `physics.system.segment_covering` and `RaySegment.opl_at` already rely on. "Reset view"
  still frames the *physical* extent (`PlotView._plotted_z_range`), not the drawn one, so
  panning can't make the default view creep outward.
- A radius of curvature of `0` in either editor means **flat** (stored as `float('inf')`),
  and the field stays editable while the Flat box is ticked. `physics/matrices.py` and
  `physics/raytrace.py` still reject a stored `r == 0.0` outright — the GUI translates 0
  into infinity at the point of entry, so those guards remain as defense against a
  hand-edited project file, not as the user-facing rule.
- The Ray Tracing tab's transverse-intensity plot defaults its x range to 1.5x the largest
  optic's diameter and holds it there, rather than auto-ranging to the data. That is so the
  spot can be seen growing and shrinking as the target moves; the cost is that a spot far
  smaller than the aperture is a narrow feature in a wide frame until you zoom in. The
  diffraction PSF, whose scale is set by the wavelength rather than by any optic, frames its
  own core instead (`PSFResult.display_radius_mm`) — the computed profile extends far past
  the visible range in both plots.
- The geometric profile and the diffraction PSF disagree by a few percent within a couple of
  Rayleigh ranges of focus, and that is correct, not a defect: a ray cone grows linearly with
  distance while a real beam grows as `sqrt(1 + (z/zR)^2)`. Each plot carries a caption
  saying which regime it is the answer in.

If tilt-induced astigmatism is ever reintroduced, expect it to require carrying two `q`
parameters per segment instead of one — a genuinely bigger change than it sounds, not a
one-line tweak, since `BeamSegment`/`SystemResult` and every consumer of `.w(z)`
currently assume a single scalar beam radius. The same change would also force the v2.0
ray tracer from a 2D meridional fan to a full 3D skew-ray tracer.

## Lessons learned (read before touching signal-heavy code)

A real bug found during development is a good case study for two things to keep in mind
in this codebase:

**Symptom**: toggling a ROC's "Flat" checkbox off in the Optics tab, then setting a new
radius, occasionally left the on-screen lens shape rendering a stale/doubled outline
that didn't match the form's values.

**Root cause**: unchecking "Flat" left the underlying spin box momentarily at `0.0`
before the user typed a real value. `_on_form_value_changed()` wrote that `0.0` straight
into the shared `Optic.r2`, then called the effective-focal-length calculation, which
divided by `r2` and raised `ZeroDivisionError` — *before* reaching the line that emits
`opticPropertyChanged`. PySide6 swallows exceptions raised inside a Qt slot (prints a
traceback, does not crash the app, does not roll back partial state), so execution
silently continued with the canvas never told to re-sync: the model object had the new
(invalid) radius, but the on-screen `OpticItem` kept whatever polygon it had before.

**Fixes applied** (`physics/matrices.interface`, `gui/tabs/optics_tab.py`):
1. `interface()` now raises a clear `ValueError` on `radius == 0` instead of an opaque
   `ZeroDivisionError` — fail loudly and specifically, at the source.
2. Unchecking a "Flat" checkbox now defaults the spin box to a sane non-zero value
   instead of leaving `0.0` — the invalid transient state is prevented, not just
   handled.
3. The EFL display computation is now wrapped in `try/except` so a display-only failure
   can **never again** prevent the critical `opticPropertyChanged` signal from firing.
   This is the general lesson: in a codebase built around "notify, then let the
   receiver re-sync," a side-effect-free display update must never sit *before* the
   notification in the same code path, or an unrelated failure in the display logic
   silently breaks state synchronization elsewhere. New read-only/derived-display code
   added to a property-change handler should go *after* the signal emit, or be wrapped
   defensively, not before it.

Also worth knowing: this exact glitch could **not** be reproduced pixel-for-pixel via
`QT_QPA_PLATFORM=offscreen` smoke tests — the offscreen platform does full repaints
without the real Windows backing-store's partial/dirty-region compositing, so it doesn't
reproduce that class of visual artifact even when the underlying state-desync bug is
present and confirmed. Offscreen smoke tests are good for catching crashes, wiring
errors, and state desyncs (as this one shows — the desync itself *was* verified
offscreen once we knew what to check for), but don't treat "looks fine in an offscreen
grab" as proof a rendering glitch is fixed; get the reporting user to confirm on a real
display too. As defense in depth, `PlotView.refresh()` now also forces a full
`viewport().update()` rather than relying on Qt's dirty-region tracking, to reduce the
chance of any *other* not-yet-found partial-update artifact.

### Round 2: stale kind label, a second 0-radius entry point, drag repaint artifact

Manual testing after v0.2 turned up three more issues; the first two have a confirmed
root cause and fix, the third is best-effort/unconfirmed.

**Stale shape label**: `Optic.kind` (`model/optics.py`) is a write-once creation preset
consumed only by `make_default_optic()` when a new optic is added — nothing ever
recomputes it from a hand-edited `r1`/`r2`, and the Optics tab's kind combo box only
ever affects the *next* "Add", never the selected optic. So an optic created as
"Plano-Concave 2" and then hand-edited to a different shape keeps displaying its
original (now wrong) kind, with no UI indication anything is stale. Fixed by adding
`model.optics.describe_shape(r1, r2)`, a pure function deriving the *current* shape name
straight from live R1/R2 using the same sign convention as `_KIND_DEFAULTS`, displayed
as a new read-only "Shape (from R1/R2)" row in the Optics tab (same pattern as the EFL
label) — `kind` itself is intentionally left alone as a creation-time preset field, not
"fixed" to auto-update, since nothing else in the codebase needs it to track live
geometry.

**A second way to write `r1`/`r2 = 0.0`**: the original fix only repaired the spin box
when its "Flat" checkbox was *toggled*. Typing `0` directly into an enabled ROC spin box
(Flat left unchecked) bypassed that repair entirely, silently writing a literal `0.0`
into the shared `Optic` — no crash (the `ValueError`/try-except from the original fix
still catches it downstream), but `OpticalSystem.propagate()` then raises on that optic,
and `PlotView.refresh()` silently returns on `ValueError`, freezing the beam curve with
no visible error. Fixed by moving the same "if unchecked and value is exactly 0.0, snap
to 100.0" repair into `_on_form_value_changed()` itself, so it applies regardless of
which widget's signal triggered the call — not just the checkbox's `toggled` signal.

**Drag-triggered doubled/offset outline**: a user reported (with a screenshot) a lens
rendering with what looked like a stale outline offset from its fill, appearing after
dragging the lens on the canvas. Two independent code reviews found no live logic defect
that could cause it: `OpticItem.paint()` draws fill and outline from the same polygon in
one `drawPolygon()` call (they cannot desync from each other within one item), and
`PlotView` never creates a second `OpticItem` for one optic id. The one drag-specific
thing found: `_on_item_dragged()` called the *full* `sync_from_optic()` — including
`prepareGeometryChange()` and a polygon rebuild — on every mouse-move, even though a
drag only changes position, never shape. `OpticItem` now has a separate
`set_position(z, x)` (plain `setPos()`, no geometry invalidation) used for drag moves;
`sync_from_optic()` (full rebuild) is reserved for actual property edits. `PlotView.refresh()`
also now calls `self.scene().update()` alongside `self.viewport().update()`, and
`OpticItem` explicitly sets `CacheMode.NoCache`, as further defense in depth. **This
was not pixel-confirmed live** (per the offscreen caveat above) — if the doubled outline
recurs after this change, the drag-specific rebuild wasn't the (or the only) cause;
check `theme.py`'s dark-mode palette switching and `PlotView`'s aspect-lock/`ViewBox`
interaction next, and get a real-display repro with exact steps before further changes.

### Round 3: ten items from a real user worklist (`TODO.md`)

Unlike rounds 1-2 (bugs inferred from a screenshot before `TODO.md` had content), this
batch came from an actual written worklist. A few are worth calling out because the fix
wasn't just "make the obviously-wrong thing work":

- **Config tab needed a manual "Reset View" click to see its own effect.** Every
  Config-tab field already wrote into `SystemConfig` and triggered `PlotView.refresh()`
  live — but `refresh()` only redraws the beam curve; it never re-applies the *view
  range* (`PlotView.apply_default_view()`), which only ran at project load or an
  explicit "Reset View" click. This affected two TODO items at once (view-range fields,
  and beam-curve padding fields, since padding changes `_plotted_z_range`'s auto extent)
  because both are downstream of the same missing call. Fixed with a new
  `ConfigTab.viewRangeChanged` signal, emitted only by the fields that define the
  plotted range (View box + the three padding spins) — deliberately *not* by every
  Config field, so toggling e.g. "show waist markers" doesn't fight a user's manual
  pan/zoom.
- **`InputBeamSpec.x_offset` was completely dead** — stored, saved/loaded, editable in
  the Beam tab, and never read by anything downstream. The physics only ever tracks a
  scalar radius `w(z)`, never a real transverse position (this is also why an `Optic`'s
  own decenter is rendering-only), so `x_offset` is applied the same way: a constant
  shift added to the plotted beam envelope/waist markers/target marker at render time in
  `PlotView.refresh()`, not fed into `physics/`.
- **ROC sign convention**: see the "UI-level R2 sign flip" note under "ABCD ray-transfer
  matrices" above — the physics/save-format convention didn't change, only what
  `optics_tab.py`'s R2 spinbox displays.
- **New-optic dropdown**: reduced from five `OpticKind` entries to two friendly presets
  ("Flat plate" → `PLANO_PLANO`, "Singlet lens" → `PLANO_CONVEX`) via a small
  `_ADD_PRESETS` list in `optics_tab.py`. `OpticKind` itself is untouched (still used by
  `describe_shape()`, save/load, and old project files with other kind values) — only
  the "Add" combo's choices changed, consistent with "kind is just a starting shape,
  everything stays editable after."

### Round 4 (v0.3): thinner outline, "optimise lens for flatness"/"...for focus"

**Bulky selection outline**: `OpticItem.SELECTED_PEN.setWidth(1)` set a *non-cosmetic*
1mm-wide pen — Qt scales a non-cosmetic pen's width by the painter's current transform,
so at this app's typical zoom (tens of mm spanning a wide viewport) that 1mm stroke
rendered as many device pixels wide, while `GLASS_PEN.setWidth(0)` stayed thin because
Qt special-cases width 0 as an always-cosmetic hairline. Fixed by calling
`SELECTED_PEN.setCosmetic(True)` too (with `setWidthF(1.5)` for a small, deliberate,
zoom-independent bump over the hairline default). Lesson: any `QPen` used inside a
zoomable/scaled `QGraphicsItem` should be explicitly cosmetic unless you specifically
want its width to be a real length in data-space units.

**"Optimise lens for flatness"/"optimise lens for focus"**: two buttons in the Beam
tab's "Beam at target location" box, both moving *the optic immediately before the
target location* (last optic in z-order whose back vertex is at or before the target
z — this one filter also naturally excludes an optic the target sits inside, since its
back vertex would then be *after* the target). "Flatness" minimizes the divergence
half-angle of the beam segment covering the target; "focus" minimizes the distance
between that segment's next waist and the target z. Both share one dependency-free
golden-section search (`physics/optimize.golden_section_minimize`) over a feasible
z-interval bounded by the neighboring optic *and* the target z itself (so the lens
being optimized can never end up straddling or past the point it's supposed to be
"before") — clamping to that boundary and reporting `OptimizeResult.clamped=True`
rather than crossing it, per the feature's "fail safely, never crash" requirement.

Two design choices worth knowing if you touch this:
- **Both buttons require a *pinned* target**, not just hover-tracking. `PlotView`
  only re-derives a pinned target's beam after a move (see `refresh()`'s
  `_pinned`/`_pinned_z` block) — a hover-only target would leave the panel visibly
  stale immediately after a click, since nothing re-runs on mouse-move once the click
  handler returns. `MainWindow._current_target` is only set from a `TargetInfo` with
  `pinned=True`; everything else (button enable/disable, the click handlers) reads
  that, not `PlotView`'s live hover state.
- **`MainWindow` owns the optimize-trigger logic, not `BeamTab`.** `BeamTab` only
  exposes `optimizeFlatnessRequested`/`optimizeFocusRequested`/`targetPrecisionChanged`
  signals and `set_optimize_enabled()`/`target_precision_mm()` — it never gets a
  reference to `PlotView` or the optics list, per the signal-mediation convention
  above. A successful move calls **both** `optics_tab.update_optic_position()` *and*
  `plot_view.refresh_optic()` — the union of what a canvas drag and an Optics-tab edit
  each do individually — since this change originates in neither of those views.

### Round 5 (v1.0): stale-target eligibility desync, ambiguous clamp snap

A code review of the optimize feature (Round 4) turned up three issues, caught before
any user report:

**Optimize buttons could act on a target the user had just unpinned.** `PlotView._unpin()`
(called both when the user clicks the pin marker to clear it, and internally by
`set_project()` whenever the Optics tab adds/removes an optic) only cleared the visual
marker — it never emitted `targetChanged`. `MainWindow._current_target` is written solely
from that signal (see Round 4's note above), so it kept holding the stale pinned
`TargetInfo` after an unpin, leaving "Optimise for flatness/focus" enabled and able to run
against a target location the user believed was cleared. Fixed by having `PlotView` track
the last-emitted pinned `TargetInfo` (`self._pinned_info`) and re-emit it with
`pinned=False` from `_unpin()` whenever a pin is actually being cleared, so
`MainWindow.on_target_changed` sees the transition and resets `_current_target` /
re-evaluates button eligibility the same way it already does for every other target
change.

**Boundary-clamp snap picked the wrong bound when the feasible interval was narrower than
the search precision.** `_optimize()` (`physics/optimize.py`) decides whether the search
landed at a boundary by checking `abs(best_z - bound) <= precision_mm` independently for
each bound; with tightly packed optics the feasible interval can be smaller than
`2 * precision_mm`, so both checks come back true and the old `if near_lower: ... elif
near_upper:` always snapped to the lower bound regardless of which side the search
actually converged toward. Fixed by comparing the two distances directly and snapping to
whichever bound is actually closer when both register as "near" — same `clamped=True`
reporting, correct bound.

**Duplicate sort.** `_optimize()` re-sorted `optics` by `z` even though
`find_governing_optic()` (called two lines above) had just done the same sort internally.
`GoverningOptic` now carries the `sorted_optics` list it already computed, so `_optimize()`
reuses it instead of sorting twice.

### Round 6 (v1.1): axis-label render bug, "Fit to data" tab, About section

**Axis labels invisible until a unit-band zoom.** `MMAxisItem._set_unit()`
(`gui/mm_axis.py`) only called `setLabel()` when the unit string changed. The
construction-time call (`__init__` → `_set_unit("mm")`) happens before the
widget has real on-screen geometry (all of `MainWindow.__init__` runs before
`main.py` calls `window.show()`), and since the initial view range keeps the
same "mm" unit, nothing forced a relabel/layout pass afterward — until a zoom
crossed a `_UNIT_BANDS` threshold and the unit string finally changed. Fixed
by always calling `setLabel()` in `_set_unit()` regardless of whether the
unit changed, plus a new `PlotView.showEvent()` override that forces one more
`apply_default_view()` once the widget is actually shown.

**"Fit to data" tab** (`gui/tabs/fit_data_tab.py`, `model/fit_data.py`,
`physics/fit.py`): a table of measured (z, beam diameter) points that fits
the *input* beam's `(z_waist, w0)` to best match the data, drawing small
circle markers + index labels on the canvas for every complete row
(`PlotView.set_fit_data_points()`, always shown when data exists, same
precedent as the target-pin marker — not gated behind a Config-tab toggle
like waist markers). Two design points worth knowing if you touch this:

- **The fit is a full-system fit, not a bare single-segment fit.** A
  measured point can sit anywhere along the beam path, including after
  optics, so each trial candidate re-propagates through the *entire*
  `OpticalSystem` (same optics list, trial input beam) and reads off the
  predicted radius via `physics/system.segment_covering()` before comparing
  to the measurement. `_segment_covering` was promoted from a private
  helper in `physics/optimize.py` to a shared, public function in
  `physics/system.py` for exactly this reuse.
- **A 2D Nelder-Mead simplex, not the existing 1D golden-section search.**
  The first implementation tried to stay consistent with
  `physics/optimize.py`'s reuse-tested-code style by alternating
  coordinate descent — two calls to `golden_section_minimize` per outer
  iteration, one per parameter. It produced a *wrong* answer on a real
  through-a-lens test case: golden-section search assumes its bracket is
  unimodal, but a wide bracket for the trial `z_waist` can straddle an
  optic's position, beyond which `propagate()` raises (an infeasible input
  beam) — the objective has a hard wall/plateau there, not a single dip,
  which breaks the search in ways that are easy to miss without an
  independent-formula test catching it. `physics/fit.py` instead implements
  a small, dependency-free 2D Nelder-Mead simplex directly (no bracket
  needed, tolerates the inf-penalty wall via ordinary float comparisons),
  run from several seeds spread across the data's z-range with a few
  shrinking-simplex restarts each (a single run can still stall along a
  narrow, correlated `(z_waist, w0)` ridge) — multi-start was needed even
  with Nelder-Mead, since this landscape can have more than one good local
  minimum when the data's z-span is small relative to the beam's Rayleigh
  range (a near-collimated beam barely curves over the sampled range, so
  `(z_waist, w0)` is only weakly identifiable from the data alone).
- **Fixed while testing this**: `segment_covering()` only had a fallback for
  `z` past the *last* segment (trailing padding); it had no equivalent for
  `z` before the *first* segment's start. This never came up for
  `physics/optimize.py`'s use (target `z` is always within or past the
  existing system), but a fit trial's candidate `z_waist` can end up
  positioned *after* some measurement point during the search, at which
  point that point's `z` falls before the trial's own first segment. Fixed
  by falling back to the first segment in that case — the same precedent
  `PlotView._sample_result`'s leading-padding region already uses (a
  `GaussianBeam` is valid for any `z` within its own homogeneous medium, not
  just within whatever `[z_start, z_end]` window one particular
  `propagate()` call happened to bound it to).

**Config tab "About" section**: version/build-date/author/organisation are
hardcoded, manually-updated constants in the new `version.py` — there's no
build system in this repo to derive them from, and the user preferred that
over a git-derived runtime lookup (which would break if ever run from a copy
without `.git`). Bump `version.py` by hand each release, the same way
`README.md`'s and `TODO.md`'s "Current version" lines already are.

### Round 7 (v1.2): axis-aligned-only, Add-optic dialog, hover overlay, composite lenses

**Axis-aligned only.** `InputBeamSpec.x_offset` and `Optic.x`/`angle_deg`/`lock_x`/
`lock_angle` were removed outright, not just hidden — every optic and the beam now sit
on the z-axis. This simplified more than it broke: `OpticItem.sync_from_optic()` no
longer needs `setRotation()`, drag deltas collapse from `(dz, dx)` to just `dz`, and
`PlotView.refresh()`'s beam-curve/waist-marker/axis-line rendering all collapsed from
"shift by `x_offset`" to "no shift" (the beam is always centered on `x=0`). The signal
chain (`OpticItem.sigDragged`, `PlotView.opticMoved`, `OpticsTab.update_optic_position`)
lost its `x` parameter entirely rather than always passing `0.0` — a real removal, not a
stub.

**Add-optic dialog, and where its geometry math lives.** The old kind-preset dropdown
(`_ADD_PRESETS`) is gone; `gui/dialogs/add_optic_dialog.py`'s `AddOpticDialog` is the
first `QDialog` in this codebase. Its live construction-diagram preview reuses
`gui/lens_geometry.py`'s `build_lens_polygon()` — extracted from what used to be
`OpticItem._build_polygon()`'s private `_surface_z()` — so the dialog's preview and the
main canvas draw the *exact* same sag geometry, not two copies that could drift. The
edge/center-thickness coupling (`model/optics.py`'s `surface_sag`/
`edge_thickness_from_center`/`center_thickness_from_edge`) lives in the model layer, not
the dialog, since it's pure geometry with no Qt dependency — `edge = center +
sag(r2, half_diameter) - sag(r1, half_diameter)`, with `sag() == 0` for a flat surface
per the confirmed "flat contributes no sag" rule, and the inverse (solving for center
given edge) needs no iteration since it's linear in the thickness term.

**Composite lenses are two new `Optic` fields, not a new data model.** The instinct
might be a `CompositeLens` wrapper class holding a list of `Optic`s — but that would have
required teaching `physics/system.py`, `Project`'s (de)serialization, and `PlotView`'s
per-id `OpticItem` rendering all to understand a second element type. Instead,
`Optic.group_id`/`group_name` just tag several ordinary `Optic` instances (the group's id
is simply its first member's own `id` — no new counter needed) as one rigid unit; a
composite is physically nothing more than N real optics at consecutive `z` with real air
gaps, which `OpticalSystem.propagate()` already handles with zero changes. The only
places that needed to learn about grouping at all: `model.optics.group_key()` (an
optic's own id if standalone, else its group's id — used everywhere a UI needs to key on
"this optic or its group"), `OpticsTab` (one list row per group, via `group_key`, with a
read-only summary + "Edit..." that reopens the dialog instead of an inline form),
and `PlotView._on_item_dragged` (shifts every same-`group_key` sibling by the same delta
so a drag can't desync a group's internal spacing).

**Known gap, not addressed this round**: the "optimise lens for flatness/focus" buttons
(`physics/optimize.py`, wired through `MainWindow._run_optimize`) move a single governing
optic's `z` directly and don't know about `group_id` — if the governing optic happens to
be a composite member, optimizing it will desync that group's spacing rather than moving
the whole group. This wasn't part of the v1.2 ask; flagged in `main_window.py` and here
so it isn't "discovered" and silently worked around later without addressing the whole
thing, consistent with how this file has always documented known gaps (see Round 3's
intro).

### Round 8 (v1.2 fix round): a beam_tab crash that looked like a composite-lens bug

A user report — "MAJOR ERROR: moving the composite lens does not impact the beam model"
— could not be reproduced directly: dragging a composite (via both direct method calls
and a fully simulated real mouse press/move/release on curved elements) correctly moved
every member and re-propagated the beam every time. The actual cause, found from an
attached traceback, was **in `beam_tab.py`, not the composite-lens code at all**:
unchecking "Collimated" leaves `r_ref_spin` at its default `0.0`; `_on_changed()` writes
`beam.r_ref = 0.0` and calls `_update_input_characteristics()`, which calls
`GaussianBeam.from_measurement(..., r_ref=0.0, ...)` — `physics/beam.py` divided by
`r_ref` unguarded, raising `ZeroDivisionError`, and this happened *before*
`self.beamChanged.emit(self.beam)` in the same method. This is the exact bug shape
"Lessons learned" Round 1 already documented and fixed once, for `optics_tab.py`'s EFL
label — a display-only computation sitting before a signal emit, with PySide6 silently
swallowing the exception — it just hadn't been applied to `beam_tab.py`.

What made it look composite-specific: once `beam.r_ref` is poisoned at `0.0`,
`physics/system.py`'s `OpticalSystem.propagate()` hits the *same* division on every
subsequent call — including from `PlotView.refresh()` and
`MainWindow._refresh_output_readouts()`, both of which only `except ValueError`, not
`ZeroDivisionError`. So from that point on, *every* refresh (a composite drag's
included) silently no-ops app-wide, not just composite-related ones — the user's next
action just happened to be dragging a composite lens.

**Fixes applied**, following the exact Round-1 precedent rather than inventing a new
pattern: `physics/beam.py`'s `from_measurement()` now raises a clear `ValueError` for
`r_ref == 0.0` (matching `physics/matrices.interface()`'s existing `radius == 0` check)
— this alone makes it consistently catchable by the `except ValueError` clauses already
in place elsewhere. `beam_tab.py`'s `_on_collimated_toggled`/`_on_changed` snap
`r_ref_spin` away from `0.0` on both the checkbox-toggle and direct-typing entry paths
(the same repair `optics_tab.py`'s ROC "Flat" checkboxes already do), and
`_update_input_characteristics()` is now wrapped in `try/except` so a future failure
there can never again block the critical `beamChanged.emit()`. **Lesson, restated**:
this is the second time this exact bug shape has bitten this codebase in two different
tabs — any new read-only/derived-display computation added to a property-change handler
needs the same defensive treatment (wrap it, or put it after the signal emit) on sight,
not just when a bug report eventually traces back to it.

Also fixed this round: the Add-optic dialog's live preview never got `theme.py`'s
dark-mode background/axis-pen treatment (it's a fresh `pg.PlotWidget` per dialog open,
and `apply_theme()` only ever restyles the *main* canvas) — `pg.PlotWidget`'s background
follows the app-wide `QPalette` when not explicitly set, so dark mode left the preview
dark-background-but-light-mode-tuned-text. Fixed by detecting the app palette's
lightness once at construction (safe since the dialog is modal). An "Edit lens..."
button was added to the singlet Properties form (parity with the composite's existing
"Edit...", edits the same `Optic` in place — confirmed with the user, not a
replace-with-new-id flow like the composite side uses). The composite summary panel
gained a `z`/lock field (rigidly shifts every member by the same delta, mirroring a
canvas drag) and EFL/BFL (composed from each member's `thick_lens()` matrix folded with
`propagation()` for the inter-element gaps, in z-order — the same composition
`thick_lens()` already does internally for one lens, just extended across a chain;
verified against the independent two-thin-lens combined-focal-length formula, not
against this app's own matrix code a second time).

### Round 9 (v2.0): real ray tracing, rejecting rayoptics and prysm

`TODO.md`'s v2.0 ask was open-ended: implement real (Snell's-law) ray tracing for
spherical-aberration analysis, decide whether to build it from scratch or adopt
`rayoptics`/`prysm`, and sanity-check the whole plan before implementing. The plan was
worked out and approved before any code was written (see the "Real ray tracing / spherical
aberration (v2.0)" physics section above for the resulting design) — this entry is about
the two decisions worth knowing if you touch this later.

**Why not `rayoptics` or `prysm`.** `rayoptics` is a full sequential lens-design tool built
around its own `OpticalModel`/`SequentialModel` object graph and file format — adopting it
would mean translating this app's `Optic` list into that model and back on every parameter
edit, just to reuse geometry math that (per the rotational-symmetry finding) reduces to a
few lines of 2D trig per surface; it's also this codebase's first non-numpy physics
dependency, breaking the "physics/ only imports numpy" invariant stated at the top of this
file. `prysm` is genuinely well-suited to the Zernike-fitting/PSF half of the ask, but
adopting a second numerical-optics dependency for ~150 lines of code we could write and
fully test ourselves (a 5-term Zernike basis + `numpy.linalg.lstsq`, one `numpy.fft.fft2`)
wasn't a good trade once the rotational-symmetry simplification made the "hard part" prysm
would have solved (general 2D pupil sampling, arbitrary aberration fields) simply not
present in this app's axis-aligned model. Both were rejected in favor of three small,
from-scratch modules (`physics/raytrace.py`, `zernike.py`, `diffraction.py`), each
validated against an independent formula, matching how `optimize.py` and `fit.py` were
already built.

**A design mistake caught during implementation, not before.** The original plan for
`physics/zernike.py` considered fabricating synthetic azimuth samples (replicating each
real ray's radial data point at several made-up angles) so a full 2D Zernike fit could be
run and "confirm" every non-symmetric term comes back at zero. Implementing it made the
flaw obvious: manufacturing data we already know the answer for isn't a validation, it's
just re-asserting the assumption into the input — a fit that can only ever return what you
told it to return proves nothing. The module was written instead to fit *only* the m=0
terms directly against the real (rho, OPD) samples from the actual meridional fan (pooling
the +rho/-rho branches), and the genuine sanity check moved to where it belongs:
`test_raytrace.py::test_wavefront_is_symmetric_about_the_axis`, which checks that the
independently-traced +rho and -rho rays actually agree, on real traced data, not fabricated
data. Lesson: "add fake data so the test/fit output looks complete" is a smell worth
stopping on even mid-implementation of an already-approved plan — the fix here was a
same-round self-correction, not a follow-up bug report.

Also worth knowing: `physics/diffraction.py`'s PSF now propagates from the fan's exit plane
over the measured exit-pupil radius (see the physics section above), but it is still a
single-plane Fraunhofer transform rather than a rigorous multi-plane Fresnel propagation —
flagged in that module and above rather than presented as more rigorous than it is.

### Round 10 (v2.0): the v2.0 code review

A twelve-finding review of the v2.0 working tree. Two of the findings are worth recording
because of the *shape* of the mistake rather than the mistake itself:

- `_intersect_surface` took the nearest forward root of the ray/sphere quadratic. That is
  right for every `R > 0` surface — and every test in the first cut used one — but a
  refracting surface is only the *cap* of its sphere containing the vertex, and for `R < 0`
  that cap is the *far* root: the sphere spans `[vertex - 2|R|, vertex]`, so a ray from
  further than `2|R|` upstream met the phantom rear hemisphere first. A plano-concave lens
  then *converged* the beam, with the bend drawn up to `2|R|` in front of the glass. Lesson:
  when a sign convention admits both signs, a test suite that only ever exercises one of
  them is not covering the code — the bug sat in the one line that looked most obviously
  correct.
- The diffraction PSF aliased silently above ~16 waves of wavefront error, and the existing
  test for it used ~32 waves — i.e. the test was *itself* past the alias threshold and
  passed anyway, because the assertion it made (energy further out than the unaberrated
  case) happened to survive the wraparound. Lesson: a test that passes on aliased data is
  worse than no test; the replacement asserts on encircled energy inside the first Airy
  null, which the wraparound cannot fake.

### Round 11 (v2.0): "the results don't quite match what I expect"

Reported as a vague mismatch against intuition on the two transverse-profile plots, which
turned out to be three separate errors, none of which any existing test could see. All
three share a shape worth recording: **each was invisible in exactly the case the tests
covered.**

- **The diffraction pupil was a uniform disk.** `trace_fan` deliberately runs the fan out to
  `2.5 w` so the wavefront is sampled to where there is still light; the PSF then treated
  that whole disk as filled. An aperture 2.5x too wide reported a spot about half its true
  width, with textbook Airy rings a clean Gaussian beam does not have. Every diffraction
  test passed, because every one of them was a *uniform-aperture* test checked against the
  Airy formula — they were testing the module against the assumption instead of against the
  system it was being handed.
- **The wavefront was referenced to the target plane, not to a reference sphere.** The two
  agree *exactly* at focus and diverge with defocus (a factor of two too wide by ten
  Rayleigh ranges out). Every PSF test pinned a target near focus, which is the natural
  thing to test and the one place the bug cannot show.
- **"RMS wavefront error" was the Zernike fit residual.** Five m=0 terms describe a smooth
  traced wavefront almost exactly, so the number was ~1e-8 waves next to a peak-to-valley of
  25 waves — on screen, permanently, claiming every system was perfect. The test that
  touched it asserted the residual was near zero, which was true and was the wrong question.

The fix that actually mattered was not any of the three individually, it was
`tests/test_model_agreement.py`: cross-checking the Gaussian/ABCD model, the geometric ray
fan and the ray-trace -> Zernike -> FFT chain against *each other* on a system where all
three must agree. Three implementations sharing almost no code cannot be wrong in the same
direction by accident, and all three errors showed up there immediately as
tens-of-percent disagreements. Lesson: when several independent models of the same physics
exist in one codebase, the agreement between them is the strongest test available, and
checking each one only against its own closed form leaves exactly the errors that live in
the seams — the pupil illumination, the reference surface, the meaning of a reported
number.

A fourth, smaller one from the same round: the geometric profile and the PSF *legitimately*
disagree by a few percent within a couple of Rayleigh ranges of focus, because a ray cone
grows linearly and a real beam grows as `sqrt(1 + (z/zR)^2)`. The first version of the
cross-check asserted they agreed there and failed. Widening the tolerance until it passed
would have been asserting a bug into place; the test now pins the *size* of the expected
gap instead, and separately asserts it closes further out.

### Round 12 (v2.0): the artifacts on the axis

Reported as "artifacts in the intensity and PSF plots on axis" — a 15% notch at `x = 0` in
the geometric profile, and a too-tall spike with ripple beside it in the PSF. Three causes,
one per plot and one shared:

- **The irradiance kernel spread each ray's power evenly in radius.** It should spread in
  proportion to radius, because that is what `dP/dr` does across a tube. Spreading evenly
  shifts a near-axis ray's deposit outward by about `sigma^2/mu`, which is a whole bin for
  the rays closest to the axis. Replacing the Gaussian with the ray's actual tube, integrated
  exactly, made the scheme *exact* for a uniform fan and six times faster — the closed-form
  erf integral had been solving the wrong problem accurately.
- **The axial ray was given zero power.** It represents a disc, not a zero-radius annulus.
  See above; this is the error the previous point was partly masking, and vice versa, which
  is why isolating them needed a parameter sweep over four combinations rather than
  inspection.
- **The PSF's azimuthal average labelled each annulus by its integer bin index** rather than
  by the mean radius of the pixels in it. Bin "1" actually samples 1.21 pixels out.

Two lessons worth keeping. First: **two compensating errors read as one small error.** The
notch was 15%, but the individual mistakes were −9% and +5% and neither showed cleanly until
both were varied independently against an analytic answer. A sweep over the cross-product of
the candidate fixes found it in one run; reasoning about them one at a time did not, and had
already produced one confidently wrong attribution in an earlier round (the same 15% was
recorded then as evidence *for* the area weighting, when it was really the missing disc).

Second: **"correct at the origin" is a distinct property worth testing for.** Every one of
these defects lived in the first bin or two and was invisible in any whole-profile tolerance
— an `allclose` over 120 bins passes comfortably with one bin 15% out. The regression tests
added here assert on the innermost bins *specifically*, and against an analytic answer rather
than against the curve's own smoothness, so that a scheme which is smooth and wrong cannot
pass.

### Round 13 (v2.0): a composite lens with zero spacing

Reported as "the rays are ending at the interface between the two lens elements". Every ray
in the fan, the axial one included, came back `vignetted` at the cemented joint — so the
whole Ray Tracing tab went to "the axial ray does not reach z=…", several steps removed
from the cause.

The bug was one character of tolerance: `_intersect_surface` filtered forward roots with
`t > 1e-9`, and with zero spacing the previous element's back surface and the next one's
front surface are literally the same sphere, so the root is exactly `0`. The guard was
written to stop a ray re-finding the surface it had just refracted at — a hazard that does
not exist here, because the trace is strictly sequential and never asks for the same surface
twice. It was protecting against nothing and breaking the one case where a ray legitimately
starts on the surface it is about to meet.

Two things worth keeping from it:

- **An epsilon guarding against an impossible case is not free.** It cost nothing for years
  and then rejected the only geometry that lands exactly on it. Worth asking of any
  `> eps` in a geometric predicate: what does this exclude, and can that thing actually
  occur in this code path?
- **A cemented joint is not an infinitesimal air gap**, even though Snell's law says the two
  give the same ray direction. The equivalence holds for refraction and breaks for total
  internal reflection, so the shortcut is invisible until someone builds a fast, high-index
  doublet — at which point rays stop at a surface that isn't there. The regression test
  pulls the elements one micron apart to show the spurious TIR coming straight back, so it
  cannot pass vacuously if a later change simply vignettes everything instead.

## Testing approach

- `physics/` and pure-function GUI utilities (`color_utils.py`) get real `pytest` unit
  tests in `telescope_simulator/tests/`, checked against independent formulas where
  possible.
- The GUI as a whole is checked with offscreen smoke tests (`QT_QPA_PLATFORM=offscreen`)
  that construct real widgets (`OpticsTab`, `PlotView`, or the full `MainWindow`), call
  real handler methods (not synthetic mocks), and assert on resulting state — e.g. adding
  every optic kind and checking the drawn polygon has no NaN/Inf, simulating a drag and
  checking the model updated, save/load round-tripping a project, or replaying the exact
  click sequence that reproduced a bug. `tests/test_optics_tab.py` and
  `tests/test_plot_view.py` are permanent pytest versions of this pattern (state/wiring
  checks, not pixel checks); one-off variants are still fine to run ad hoc via
  `python -c "..."` during development, but promote the ones worth keeping permanently.
- There is currently no automated visual/pixel-level testing, and offscreen rendering is
  known (see above) to not reproduce all real-backend rendering issues — manual
  on-screen verification is still needed for anything touching `OpticItem.paint()`,
  `PlotView`'s item/viewport update calls, or `theme.py`.

## Extending the app

- **New optic-derived readout** (like the EFL label): check whether it's already
  latent in `physics/matrices.thick_lens`'s system matrix before adding new formulas;
  wire it into `optics_tab.py`'s `_update_efl_label`-style pattern (recompute in both
  `_load_optic_into_form` and at the end of `_on_form_value_changed`).
- **New per-project display/config setting**: add it to `model/config.SystemConfig`
  (remember `to_dict`/`from_dict`), a control in `config_tab.py`, and consume it in
  `plot_view.py`. `from_dict` uses `.get(..., default)` throughout specifically so old
  saved project files missing newer keys still load — keep that pattern.
  New app-level (not per-project) preferences belong in `app_settings.py` instead.
  Dark mode was deliberately split this way; follow that precedent when the setting is
  "how I like my screen to look" vs. "how this optical system should be modeled/shown."
- **New optic kind**: add to `model/optics.OpticKind` and its `_KIND_DEFAULTS` entry;
  the renderer, physics, and save/load all already work generically from `R1`/`R2`/
  thickness/index, so nothing else needs touching.
- **New tab**: build it as its own `QWidget` under `gui/tabs/`, add it in
  `MainWindow.__init__`, wire its signals in `MainWindow._wire_signals()`. Don't give it
  a reference to `plot_view` or another tab directly.
