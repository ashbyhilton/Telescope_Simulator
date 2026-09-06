For v2.0:
- [x] Major change: Implement a ray tracing physics engine to allow for understanding and working with spherical aberation. This engine should be accessed through a tick box in config that is default off. When enabled, it should use the existing input beam properties as a base to construct a number of rays which are propogated through the optical system using Snell's law at each intersection with an optical element. For each ray intersection with an interface, find the local surface normal to calculate incident angle, and using the refractive indices of the two materials (add a new config box for the refractive index of the background medium, default to air) calculate the angle of refraction, and thus the new ray. Consider Rays that escape the optical system before the final lens should end at the z location of the optic they fail to intersect. Consider also where total internal reflection may occur within an optic. Consider whether to implement this model structure from scratch or utilise existing packages such as 'rayoptics'. The calculated rays should be plotted on the graphic screen overlaid ontop of the existing gaussian model, and should update as lens parameters or input beam parameters vary, as for the gaussian model. when a target location is set by clicking (as before), compare each ray's accumulated optical path length to a reference to get the wavefront error map across the pupil at that plane. Fit that map to Zernike polynomials using a standard least-squares fit over the sampled ray fan, and provide the polynomial coefficients along with easy to understand descriptions of each term. consider whether it is possible to plot a transverse intensity profile from this information, either by weighing each ray with the intensity of original input beam, or otherwise. Consider whether to implement this from scratch or utilise existing packages (?prysm?). Sanity check my plan, and identify gaps or better alternatives. Build a detailed plan to implement this major change along the pathway that is the best candidate, along with modifications to the user interface, and be ready to implement if I approve of the plan.
  [Sanity-checked and planned, then implemented from scratch (rejected both
  rayoptics and prysm -- see README "Round 9" for the full reasoning). Key
  finding that shaped everything else: this app is strictly axis-aligned
  with no tilt/decenter (v1.2), so the whole problem is rotationally
  symmetric -- a single 2D meridional ray fan (physics/raytrace.py) fully
  characterizes the system, only the m=0 "spherical" Zernike terms
  (physics/zernike.py) can ever be non-zero, and the diffraction PSF
  (physics/diffraction.py) is exactly a revolution of a 1D radial profile.
  TIR terminates the ray (no reflected-path modeling, confirmed with user);
  a ray missing an optic's clear aperture is vignetted and stops at that
  optic's z, per spec. New Config-tab "Ray tracing" box (enable checkbox,
  background-medium index -- now also feeding the existing Gaussian/ABCD
  model, confirmed with user -- and ray-fan count); ray fan overlaid live on
  the canvas (PlotView._update_ray_trace); new "Ray Tracing" tab shows
  Zernike coefficients + descriptions, RMS/PV wavefront error, W(rho), and
  the diffraction PSF radial profile whenever a target is pinned, following
  the existing "MainWindow owns the trigger logic" convention. All three new
  physics modules validated against independent formulas (thick-lens ABCD
  back focal length in the paraxial limit, a known Zernike boundary-value
  identity, the Airy first-null formula) -- see tests/test_raytrace.py,
  test_zernike.py, test_diffraction.py.]
- [x] Code review of the v2.0 working tree (12 findings), all addressed.
  [Correctness: (1) _intersect_surface took the nearest forward root, which
  picks the phantom rear hemisphere for every R < 0 surface -- a
  plano-concave lens converged the beam and refracted up to 2|R| in front of
  the glass; now selects the vertex-side cap. (2) the diffraction FFT
  aliased silently above ~16 waves, so an off-focus target plotted a
  wrapped, deceptively diffraction-limited PSF -- psf_radial_profile now
  refines the pupil grid to satisfy Nyquist and refuses (ValueError) rather
  than plotting an aliased profile. (3) the Zernike normalization and PSF
  pupil used the *launched* fan half-width even when a stop had vignetted
  most rays, extrapolating a fit made over rho_norm in [0, 0.3] out to 1.0;
  both now use the surviving bundle. (4) the Fraunhofer propagation ran from
  the beam's launch plane over the launched fan radius -- a plane upstream
  of every optic -- giving an Airy null several times wrong; now runs from
  the fan's exit plane over the measured exit-pupil radius. (5) a
  zero-thickness optic marked every ray including the axial one vignetted,
  reported as "the axial ray does not reach z=..."; now named at the source,
  and wavefront_at's message says which surface stopped the ray and how.
  (6) a Gaussian-propagation failure returned before refreshing the Ray
  Tracing tab, leaving stale Zernike/PSF numbers on screen. (7) r_ref == 0.0
  from a hand-edited project file raised an uncatchable ZeroDivisionError.
  (8) the FFT input pixel pitch used 2R/n where linspace gives 2R/(n-1).
  Quality: (9) dragging an optic cost ~120 ms/mouse-move (~8 fps) because
  PlotView.refresh() re-emits the pinned target and so ran the PSF on every
  move -- the tab's recompute is now coalesced onto a single-shot timer,
  measured 5.1 ms/step (~194 fps) with one recompute when the drag settles.
  (10) SystemConfig.ambient_index never reached the Optics tab's EFL/BFL
  readouts or the canvas hover overlay, so those two panels contradicted the
  rest of the app in a non-air medium. (11) the PSF profile took a single
  FFT row while its docstring claimed an azimuthal average; now genuinely
  averages the annulus. (12) dead ray_count == 1 branch removed, and the
  documented odd-ray-count invariant is now enforced in trace_fan rather
  than only in the spin box's step size. 16 new tests; suite 124 -> 140.
  See README "Round 10" for the two findings worth remembering.]
- [x] In addition to the diffraction PSF, plot the actual transverse intensity as would be seen by eye on a card.
  [new physics/irradiance.py + a second plot in the Ray Tracing tab. Each
  ray of a dense (801-ray, independent of the Config fan count) meridional
  fan carries the power of the annulus it stands for -- the input beam's
  Gaussian irradiance at its launch height times |rho| -- binned radially
  and divided by each bin's *annulus area*, not its width (dividing by width
  would make every profile falsely rise toward its outer edge). Weighting by
  |rho| also makes the axial ray weightless, which is correct and removes
  any rho = 0 singularity. This is the honest counterpart to the PSF rather
  than a replacement: the two are valid in opposite regimes, so the tab shows
  both, and adds a caveat when the geometric spot has dropped below the Airy
  radius and stopped being the meaningful one. Verified against the input
  beam's own closed-form Gaussian for the no-optics case.]
- [x] A radius of curvature of 0 should be accepted and mean 'flat'; the field should not gray out, and a non-zero value should clear 'flat'.
  [the spin box is now the authority and the Flat checkbox follows it, in
  both editors (Optics tab form and the Add/Edit-optic dialog) -- typing 0
  ticks Flat and stores float('inf'), typing anything else unticks it, and
  the field is never disabled. Ticking Flat writes 0; unticking snaps to a
  non-zero radius, since otherwise the value would still read as flat. This
  reverses the previous rule (0 was repaired *away* to 100mm), so the two
  tests that encoded that rule were rewritten rather than deleted. Found
  while doing it: _sync_flat_checkbox cleared the _updating_form guard its
  caller was already inside, letting _load_optic_into_form write
  half-populated form values back onto the optic -- now saves/restores.]
- [x] Continue the beam and rays to the edges of the plot window rather than truncating at the Rayleigh-range padding.
  [PlotView now tracks the drawn span separately from the physical one and
  extends both curves to the window in both directions, re-extending on
  pan/zoom via sigXRangeChanged (cheap: it re-samples the cached result,
  it does not re-run the physics). Rays extrapolate back before the launch
  plane too; a vignetted/TIR ray still stops where the physics stops it,
  since that endpoint is real rather than a drawing limit. "Reset view"
  deliberately keeps framing the physical extent, or each pan would widen
  what reset restores. beam_at() gained the first/last-segment fallback so a
  target can be pinned out in the newly-drawn region.]
- [x] Changing the target plane should take a single left click, without unclicking the previous marker first.
  [dropped _on_scene_mouse_clicked's "already pinned" early return, which
  made every retarget a two-click job. Clicking the marker still unpins --
  that path accepts the event before it reaches the scene handler, so it
  can't re-pin on the same click. Added an explicit left-button check, which
  matters more now that clicks are consequential while pinned.]
- [x] Widen the left panel so no horizontal scroll is needed.
  [tab panel 360-460px -> 520-680px, plus the Ray Tracing tab's scroll area
  set to vertical-only and its Zernike table told to wrap the Description
  column into whatever width is left rather than demand its natural width
  (that table was what forced the sideways scroll).]
- [x] Add descriptive text under the diffraction PSF and wavefront error plots, like the transverse intensity one has.
  [all four captions now go through a shared RaytraceTab._note() helper.
  Each plot answers a different question about the same target and which to
  believe depends on the regime, so none is self-explanatory from its axes.]
- [x] Give the rays a spatial width in the transverse intensity plot to smooth its discrete appearance, conserving total energy.
  [Gaussian of the ray's own tube width (half the target-plane spacing to
  its neighbours in the fan), integrated over each bin in closed form and
  normalized per ray. Two things had to be got right, both caught by the
  existing analytic-Gaussian test rather than by inspection: spreading power
  evenly in *radius* rather than in area pushed irradiance ~15% too high in
  the innermost bin, and point-sampling the kernel at bin centres is
  inaccurate whenever the tube is narrower than a bin -- which is the normal
  case -- in a way that does not cancel against the normalization. Kernel is
  mirrored about r=0 since radius is a folded coordinate. Because the
  smoothing scales with ray density, the fan needed for a smooth curve came
  *down* from 801 rays to 401.]
- [x] Put the PSF plot on a log vertical axis.
  [an Airy pattern's first ring is ~1.7% of peak and the second ~0.4%, so on
  a linear axis everything past the core sat on the baseline -- exactly the
  part worth reading when judging how much light an aberration threw out of
  the core. Intensities are clamped to 1e-7 before plotting, since a
  Fraunhofer pattern has exact zeros at its nulls and log10(0) draws as a
  gap running off the bottom of the axis.]
- [x] Unticking "lock aspect ratio" should leave the x and z ranges where they were.
  [the checkbox went through viewRangeChanged, which re-applied the *default*
  z/x range. Removing that was only half of it: a ViewBox keeps the range it
  was asked for alongside the wider one the lock makes it show, and dropping
  the lock snaps back to the request -- so PlotView.set_aspect_locked() now
  re-asserts what was actually on screen. "Unlock" means stop constraining,
  not re-frame.]
- [x] Move "refractive index of the medium" out of Ray tracing into a general properties area of Config.
  [it feeds the Gaussian/ABCD model and the Optics tab's focal lengths
  whether or not ray tracing is enabled, so filing it under Ray tracing
  misdescribed its scope. New "General properties" group, first in the tab.]
- [x] Move "number of rays" from Config to the Ray Tracing tab.
  [still a SystemConfig field, so it still saves and loads with the project;
  it is now edited beside the analysis it controls and the recompute time it
  costs. ConfigTab deliberately no longer writes that field -- its
  self.config *is* the project's config object, so writing a stale local
  copy back would silently undo the other tab's edit.]
- [x] Show the time taken to compute the previous frame in the Ray Tracing tab.
  [total plus a per-stage breakdown, which is the useful half: it shows that
  raising the ray count costs almost nothing (~2 ms) while the PSF is
  ~110-120 ms and is what the debounce exists for.]
- [x] Check the spatial units in plot labels -- "mmm" should read "um" etc.
  [the Ray Tracing tab's three plots and the Add-optic dialog's preview were
  using plain pyqtgraph units="mm" axes; pyqtgraph prepends an SI prefix
  without knowing "mm" is already non-base. All four now use the app's own
  MMAxisItem, which the main canvas has had since v1.1.]
- [x] Plot the transverse intensity as a full slice I(x, 0) rather than I(r), and check the normalisation.
  [normalisation was already correct -- it divides each bin by its annulus
  area, so what it returns is irradiance, not the 2*pi*r-weighted radial
  power distribution; verified against the analytic Gaussian and, now, against
  the ABCD model's w(z) at five planes either side of focus. What was wrong
  was the presentation: it showed only the r >= 0 half at bin *outer edges*.
  Now bin centres, mirrored to a signed x axis, with a default range of 1.5x
  the largest optic's diameter so the spot visibly grows and shrinks as the
  target moves instead of being rescaled to fill the frame.]
- [x] Remove the log axis from the PSF and plot it against x rather than r.
  [reverses the entry above it, and correctly so: once the pupil carried the
  beam's real Gaussian illumination the rings largely went away, and there
  was nothing left down at 1e-4 of peak for a log axis to reveal. Mirrored to
  a signed x like the plot above it so the two read against each other, and
  framed on the core -- the FFT's own radius array runs ~100x further, which
  on a linear axis draws the whole pattern as one spike at the origin.]
- [x] Double-check the physics of both transverse-intensity calculations.
  [three real errors, all invisible in exactly the case the existing tests
  covered -- see README "Round 11" for the full write-up.
   1. The diffraction pupil was a uniform disk, but trace_fan runs the fan
      out to 2.5 w. That is an aperture 2.5x too wide: it reported a spot
      about half its true width, with Airy rings a Gaussian beam does not
      have. Every diffraction test was a uniform-aperture test checked
      against the Airy formula, i.e. testing the module against the
      assumption instead of against the system it was handed.
   2. The wavefront was referenced to the target *plane*, not to a reference
      sphere centred on the target point. Those agree exactly at focus and
      diverge with defocus -- a factor of two too wide by ten Rayleigh
      ranges out -- and every PSF test pinned a target near focus.
   3. "RMS wavefront error" was the Zernike fit *residual*: ~1e-8 waves next
      to a peak-to-valley of 25 waves, permanently claiming every system was
      perfect. Now the area-weighted RMS of the wavefront with piston
      removed; the residual is still shown, under its own name.
  The fix that mattered was tests/test_model_agreement.py, which cross-checks
  the Gaussian/ABCD model, the geometric ray fan and the ray-trace -> Zernike
  -> FFT chain against each other. All three errors showed up there at once
  as tens-of-percent disagreements. The card profile itself needed no physics
  change -- it now agrees with the ABCD model to ~1% from 200 mm out to 2 m.]
- [x] Artifacts on axis in the transverse-intensity and PSF plots.
  [three causes, one per plot and one shared -- see README "Round 12".
   1. The irradiance kernel spread each ray's power evenly in radius. It
      should spread in proportion to radius, since that is what dP/dr does
      across a tube; spreading evenly shifts a near-axis ray's deposit
      outward by ~sigma^2/mu, a whole bin for the innermost rays. Replaced
      the Gaussian with the ray's actual tube integrated exactly: now exact
      for a uniform fan at any ray count, and ~6x faster (no erf).
   2. The axial ray was weighted as a zero-radius annulus, i.e. zero power.
      It has no mirror partner to share an annulus with -- it stands for the
      central disc of radius drho/2, worth I*drho/4 in the same units. The
      missing disc is a dimple exactly on axis.
   3. The PSF's azimuthal average labelled each annulus by its integer bin
      index, but rint() binning puts pixels at 1.0 and 1.414 in the same
      annulus, whose mean radius is 1.21. Now reported at the mean radius of
      the pixels that contributed.
  Innermost bins went from -15% to within 0.02% of the analytic Gaussian,
  the PSF core from a 6% wobble to 0.4%, and the card got faster (19-36 ms
  -> 8-25 ms). Errors 1 and 2 partly cancelled, which is why an earlier round
  recorded that same 15% as evidence *for* the even-in-radius weighting; a
  sweep over all four combinations separated them in one run.]
- [x] A composite lens with zero spacing between elements: rays end at the interface.
  [_intersect_surface filtered forward roots with t > 1e-9. With zero
  spacing the previous element's back surface and the next one's front
  surface are the *same sphere*, so the root is exactly 0 and every ray in
  the fan -- the axial one included -- came back vignetted at the joint,
  which surfaced as "the axial ray does not reach z=..." several steps from
  the cause. The guard was there to stop a ray re-finding the surface it
  had just refracted at, which cannot happen: the trace is strictly
  sequential (front, back, next front) and never asks for the same surface
  twice. Now t >= 0, with a picometre of slack for float noise.
  Fixed alongside it: a zero gap is a cemented joint, not a sliver of air,
  so the back surface now refracts straight into the next glass. Snell
  composes, so the direction is identical either way -- but the detour
  through the ambient index can total-internally-reflect at an angle a real
  cemented joint passes easily (44 deg on the joint is past the 32.7 deg
  glass-air critical angle and nowhere near the 76.7 deg glass-glass one),
  stopping the ray at a surface that does not physically exist. The ABCD
  model composes this correctly already and has no TIR, which is why only
  the ray tracer was visibly broken. Doublet focus now agrees with the
  paraxial model to 1e-3.]
- [ ]




FIXES FOR v1.2
- [x] Improve contrast on the text in the add lens window graphic. In dark mode it is very faint.
  [root cause: the Add-optic dialog's preview widget (a fresh pg.PlotWidget
  each time the dialog opens) never got the background/axis-pen treatment
  theme.py's apply_theme() gives the main canvas -- pg.PlotWidget's
  background follows the app-wide QPalette when not explicitly set, so dark
  mode left the preview with a dark background but still the light-mode-
  tuned dark-gray annotation colors. Fixed by detecting the app palette's
  lightness once at construction (the dialog is modal, so it can't change
  underneath it) and choosing background/axis-pen/annotation colors to
  match, same values theme.py already uses for the main canvas.]
- [x] For singlet lenses, add 'edit lens' as a button to open an existing lens in the new popup window, as for the composite.
  [new "Edit lens..." button in the Optics tab's Properties form, opens
  AddOpticDialog(existing_single=optic) (the dialog's single_page.load()
  method already existed, just unused until now) and applies the result
  back onto the *same* Optic in place (same id/z/lock_z) -- confirmed with
  the user this should edit in place, not replace, matching how the inline
  form already works.]
- [x] Add a parameter for composite lenses: the air gap between lenses.
  [already existed -- the per-element "spacing to next element" field in
  the Add/Edit dialog's composite list. User confirmed they'd just missed
  it; no change made.]
- [x] once a composite lens is created, the properties tab should include a field to set the z position and check box to lock the lens as for the singlet lens. It should also provide the effective focal and back focal lengths.
  [group_z_spin/group_lock_check added to the composite summary panel --
  editing z rigidly shifts every member by the same delta (mirrors a canvas
  drag), lock applies to every member uniformly. EFL/BFL computed by
  composing each member's thick_lens() matrix with propagation() for the
  inter-element air gaps, in z-order -- same composition thick_lens()
  already does internally for one lens, just extended across the chain;
  verified against the independent two-thin-lens combined-focal-length
  formula in tests/test_optics_tab.py.]
- [x] MAJOR ERROR: moving the composite lens does not impact the beam model.
  [not actually a composite-lens bug -- root cause was in gui/tabs/
  beam_tab.py: unchecking "Collimated" left r_ref_spin at its default 0.0,
  and GaussianBeam.from_measurement() divides by r_ref unguarded, raising
  ZeroDivisionError *before* beamChanged.emit() in the same method (same
  bug shape as the v1.0/v0.2 "Lessons learned" Round-1 story, just never
  applied to this tab). Worse: physics/system.py's propagate() hits the
  same crash on every subsequent call once beam.r_ref is poisoned at 0.0,
  and PlotView.refresh()/MainWindow._refresh_output_readouts() only
  `except ValueError` (not ZeroDivisionError) -- so every future
  refresh silently no-ops from that point on, for any action, not just a
  composite drag; that's what made it look composite-specific. Fixed at
  the source: physics/beam.py now raises a clear ValueError for r_ref==0
  (matching physics/matrices.interface()'s existing radius==0 precedent);
  beam_tab.py snaps r_ref away from 0 on both the checkbox-toggle and
  direct-typing entry paths (same repair pattern as optics_tab.py's ROC
  "Flat" checkboxes), and wraps the display-only characteristics update in
  try/except so it can never again block the critical signal emit. Could
  not reproduce a composite-specific failure even before this fix (tested
  via both direct calls and a fully simulated real mouse drag on curved
  composite elements) -- confirmed via the user's attached traceback.]

For v1.2:
- [x] Remove the x offset and angle options from the GUI and associated tickboxes etc. we will limit the model to axis aligned.
  [removed InputBeamSpec.x_offset and Optic.x/angle_deg/lock_x/lock_angle
  entirely (model, both tabs, save format); OpticItem/PlotView collapsed to
  z-only positioning -- drag signals (sigDragged/opticMoved) dropped their
  x parameter rather than always passing 0.0.]
- [x] In the optics tab, remove the dropdown for optics type. Instead, the 'Add' button should open a popup window that shows the new optic and the fields for parameters. The graphic of the optic should change dynamically to match the parameters, and the graphic should show construction detail identifying each parameter (ROC1, ROC2, centre thickness, etc). Also include a parameter: edge thickness. Couple edge thickness, the ROCs, diameter, and centre thickness such that when centre thickness is changed, it updates the calculated edge thickness, or vice versa. The window should have 'accept' and 'reject' buttons, and when accepted the optic is created and added to the list of optics as before.
  [new gui/dialogs/add_optic_dialog.py (first QDialog in this codebase) +
  gui/lens_geometry.py (build_lens_polygon, extracted from optic_item.py so
  the dialog's live preview and the canvas draw the same sag geometry) +
  model/optics.py's surface_sag/edge_thickness_from_center/
  center_thickness_from_edge (edge = center + sag(r2) - sag(r1), 0 sag for
  flat surfaces, linear so the inverse needs no iteration). _ADD_PRESETS/
  kind_combo removed; Optic.kind is now always CUSTOM for dialog-created
  optics.]
- [x] in the graphic window, mousing over an optic should display it's properties in a small overlay.
  [OpticItem gained hoverEnter/Move/Leave (first hover use in this
  codebase) emitting sigHoverEnter/sigHoverLeave; PlotView shows a
  pg.TextItem near the hovered optic with name/shape/diameter/center+edge
  thickness/R1/R2/n/EFL, reusing describe_shape/edge_thickness_from_center/
  thick_lens rather than re-deriving any of it.]
- [x] default to colouring beam by wavelength.
  [this became the *only* mode per discussion -- removed
  SystemConfig.color_by_wavelength and its Config-tab checkbox entirely;
  plot_view.py always calls wavelength_to_rgb() now.]
- [x] Add the functionality for 'composite lenses' - small groups of basic optics with all the normal parameters that are treated as one effective lens. The composite lens should include a list of sub elements and spacings within the sub system, and should be added using the new 'add optic' interface.
  [deliberately not a new data model: added Optic.group_id/group_name
  (a shared group_id -- the first member's own id -- ties several ordinary
  Optic instances into one rigid unit) so physics/system.py, Project's flat
  optics list, and PlotView's per-id OpticItem rendering all work
  unmodified -- a composite is N real optics at consecutive z with real air
  gaps, exactly what OpticalSystem.propagate() already handles. New
  model.optics.group_key()/layout_group_z() helpers; OpticsTab now shows
  one list row per group (read-only summary + "Edit..." reopens the
  dialog) and PlotView._on_item_dragged moves every same-group_id sibling
  by the same delta. Known gap: the "optimise lens for flatness/focus"
  buttons don't move a composite member's group-mates if the governing
  optic happens to be part of a group -- out of scope for this pass, noted
  in main_window.py.]


For v1.1:
- [x] the x and z plot labels don't show until you zoom in or out enough to change from mm to m or um.
  [root cause: MMAxisItem._set_unit() only called setLabel() when the unit
  string changed, but the construction-time call happens before the widget
  has real on-screen geometry, so nothing forced a relabel/layout pass until
  a zoom crossed a _UNIT_BANDS threshold; setLabel() now always fires, plus
  PlotView.showEvent() forces one more apply_default_view() once shown.]
- [x] Introduce new feature: "Fit to data". This should be new tab which has a three column table for input. The first column is an automatically generated index column titled (Point number). The second and third are user inputs with titles (z location (mm)) and (beam diameter (mm)), and when the user completes a row, the plot should add two new markers at (z, -diameter/2) and (z,+diameter/2). The markers should be small filled circles with the index of that row given in text next to the upper marker. The table should show 4 empty rows be default, with 'add row', 'remove row', and 'clear data' buttons underneath. Once at least three rows exist, another button should un-gray called 'Fit intput beam to data' which should run a best fit algorithm to match the input beam parameters to the provided data points.
  [new gui/tabs/fit_data_tab.py, model/fit_data.py (persisted on Project),
  physics/fit.py: full-system fit (accounts for any optics between the input
  beam and a measured point) via a dependency-free 2D Nelder-Mead simplex
  with multi-start restarts -- an earlier attempt reusing optimize.py's 1D
  golden-section search via coordinate descent gave wrong answers on a
  through-a-lens case, since a wide bracket can straddle an optic's
  "invalid beam" wall and break the unimodality assumption. Also fixed a
  related physics/system.py bug found while testing this: segment_covering()
  only handled z past the last segment, not z before the first one (needed
  when a fit trial's candidate z_waist lands after some data point) --
  now falls back to the first segment, matching PlotView's own leading-
  padding precedent.]
- [x] in the config tab add an 'about' section that includes the version number, the date of compile, the author as "Ashby Hilton", and organisation as "Adelaide University, Precision Measurement Group.
  [new version.py with hardcoded, manually-updated constants; ConfigTab
  gained a read-only "About" group box.]

For v0.3:
- [x] the outline of optics is till bulky and unattractive. Make it a thinner, more clean visual. See telescope simulator\pic of optic outline.png
  [root cause: SELECTED_PEN was a non-cosmetic 1mm-wide pen that scaled with
  canvas zoom, unlike GLASS_PEN's cosmetic width-0; made it cosmetic too.]
- [x] Introduce a new functionality with a button in the "beam" tab inside "Beam at target location": Add functionality to automatically adjust the location of the optic immediately before the target location in order to minimise the divergence half-angle at the target location. This should assume that simple numeric optimisation techniques will be sufficient (i.e. the slope should not change sign between the current location at the desired optimum). have a field with the target precision in z axis location, with default at 10um. Name this feature "optimise lens for flatness". If this algorithm would step the lens out of its current order, leave it such that the two lenses are adjacent with 10um separation (including centre thickness), and display an error message. Do not crash the app.
  [new telescope_simulator/physics/optimize.py, dependency-free golden-section
  search; button lives in the Beam tab's target box, requires a *pinned*
  target and is disabled (with a tooltip reason) when there's no eligible
  optic, it's z-locked, or there's no feasible room -- see README.]
- [x] introduce a second functionality similar to the one above, but this time the algorithm should adjust the previous lens to move the location of the next waist to the target z location. Call this "optimise lens for focus". AS above, if this would shift the lenses out of order, fail safely.
  [shares the same search/eligibility machinery as "optimise lens for
  flatness", just a different objective function.]

For v1.0:
- [fixed] optimize buttons stayed enabled and could run against a stale target after the
  user unpinned it (pin-marker click, or add/remove optic) — see README "Round 5".
- [fixed] boundary-clamp snap could pick the wrong bound when the feasible interval was
  narrower than the search precision — see README "Round 5".
- [fixed] duplicate sort of the optics list in `_optimize()` — see README "Round 5".

Current version: v2.0

TODO:
- [fixed] in the view tab, changing the view parameters should automatically update the plot and not require an 'update' button
- [fixed] instead of 'violet' and 'pink' for the beam colour range out of 400 - 700 just use the colour associated with the 400nm and 700nm point on the scale.
- [fixed] the input beam x offset does not work
- [fixed] in the beam characteristics, length units should use um, mm, m, and km instead of for example 3.5e4 mm
- [fixed] default new optics to having zero x offset, zero angle, and both x offset and angle locked.
- [fixed] as well as effective focal length in the beam characteristics, also provide back focal length.
- [fixed] for radius of curvature, always consider positive as convex and negative as concave.
- [fixed] In the 'new optic type' dropdown, remove plano convex, plano concave etc, and instead just have 'flat plate', and 'singlet lens', and the default for singlet lens should be a plano convex lens.
- [fixed] plot padding past output doesn't work
- [fixed] the beam at target location window doesn't update the properties when optics dynamically as lenses are moved
- fix graphics issue that occurs when moving optics (see .png for example)
  [best-effort fix applied: drag no longer rebuilds the item's polygon, only
  repositions it; see README "Round 2" notes — not pixel-confirmed live, so
  leave this item open until you've re-tested on the real display]

The three [x] items above (v0.3) are confirmed fixed by the user on a real
display. The [fixed] items below them were verified with automated tests and
manual state inspection at the time, but not separately re-confirmed on a
real display -- see README's "Lessons learned" Round 2/3/4 notes for what
changed and why.
