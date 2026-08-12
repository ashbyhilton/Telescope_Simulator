
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

Current version: v1.0

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
