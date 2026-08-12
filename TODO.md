Current version: v0.2

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

All [fixed] items above were verified with automated tests (pytest + offscreen
GUI smoke checks) and manual state inspection, but not eyeballed on a real
display -- worth a quick visual pass before clearing this list. See README's
"Lessons learned" Round 2/3 notes for what changed and why.
