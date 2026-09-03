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

Current version: v1.2

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
