# Telescope Simulator — Gaussian Beam Propagation Tool

An interactive desktop tool that models a Gaussian optical beam propagating through a
chain of real (thick, curved) lenses, aimed at students/postdocs in an optics lab as a
lightweight alternative to full optical-design software (Zemax, etc.). This document is
a guide for whoever (human or AI) picks up development next: why the tool is shaped the
way it is, the physics it implements, how the code is organized, and the traps we
already found and fixed.

Current version: **v0.3** (see `TODO.md` for the active worklist).

## Quick start

```
.venv\Scripts\python.exe main.py        # Windows, using the project's venv
```

Dependencies: `numpy`, `pytest`, `PySide6`, `pyqtgraph` (see `requirements.txt`). Run the
physics/unit tests with:

```
.venv\Scripts\python.exe -m pytest telescope_simulator/tests -q
```

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
  model/          # plain dataclasses + JSON (de)serialization, no physics, no Qt
    optics.py     # Optic, OpticKind, make_default_optic() presets
    beam_spec.py  # InputBeamSpec
    config.py     # SystemConfig (display/view settings, saved per-project)
    project.py    # Project (beam + optics + config), save()/load(), demo project
  gui/            # PySide6 + pyqtgraph
    main_window.py    # QMainWindow; the *only* place that wires tabs <-> plot_view
    plot_view.py      # interactive x-z canvas (pg.PlotWidget subclass)
    optic_item.py     # one draggable pg.GraphicsObject per Optic (true lens sag shape)
    color_utils.py    # wavelength -> RGB approximation
    mm_axis.py        # custom pg.AxisItem: um/mm/m/km unit-aware tick labels
    theme.py          # light/dark Qt palette + pyqtgraph background switching
    app_settings.py   # tiny app-level prefs file (currently just dark_mode), NOT
                       # part of Project — deliberately independent of any saved file
    tabs/
      beam_tab.py      # input beam form + input/output/target characteristics panels
      optics_tab.py    # optics list, property form, EFL readout
      config_tab.py    # view/aspect/annotation/color/dark-mode settings
  tests/          # pytest; physics + a few pure-function GUI utilities (color_utils)
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
- Ambient index fixed at 1.0 (air) between/around all optics.
- Tilt (`Optic.angle_deg`) rotates the rendering and would affect a future clear-aperture
  projection, but does **not** induce astigmatism in the beam physics — there is
  intentionally only one `q` per segment (not separate tangential/sagittal), consistent
  with normal-incidence propagation.
- No aperture clipping/vignetting — the beam envelope is drawn regardless of whether it
  exceeds an optic's clear aperture.
- Positions are global-coordinate: an `Optic.z` is its **front-surface vertex**
  position, not "distance from the previous element."

If any of these get lifted (e.g. adding real tilt-induced astigmatism), expect it to
require carrying two `q` parameters per segment instead of one — a genuinely bigger
change than it sounds, not a one-line tweak, since `BeamSegment`/`SystemResult` and
every consumer of `.w(z)` currently assume a single scalar beam radius.

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
