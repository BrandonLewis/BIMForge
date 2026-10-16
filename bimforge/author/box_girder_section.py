"""author.box_girder_section: the parametric CIP box-girder profile the
bridge_standard family sweeps (R13b; spec 4.2).

Section coordinates follow the sweep engine: x positive to the LEFT of
travel, z UP — with the origin at the superelevation pivot ON THE DECK
SURFACE, so the deck is z = 0 and the soffit is z = -depth. Drawing it
pivot-at-origin is what makes `roll` rotate the deck about the PGL
(spec 3.3 pivot convention).

Box girders are design-specific, so this is computed from params rather
than looked up in an agency table (unlike the B3/D80 families).
"""
from __future__ import annotations


class BoxGirderSection:
    """Exterior polygon + one cell void per bay, from deck parameters.

    The exterior is an orthogonal polygon: deck slab full width, then the
    overhang undersides step in to the soffit, which runs web-to-web
    out-to-out. Corner fillets are out of scope this cycle (spec 7-9), so
    the section understates concrete slightly and conservatively.

    `web_count` is the number of webs, so cells = web_count - 1: a real box
    needs at least two. web_count=1 is accepted and yields a SOLID section
    (no cells, and `web_thickness` genuinely has no effect, so it is not
    validated in that case) — a solid-slab superstructure, not a girder.
    That is a legitimate section but a costly typo if a girder was meant,
    since the solid block prices several times the concrete: every deck
    element `bridge_standard` builds carries `describe()` as its estimator
    note, so the cell count reaches the model rather than staying implicit.
    """

    def __init__(self, deck_width: float, depth: float, overhang: float,
                 web_count: int, web_thickness: float, top_slab: float,
                 bot_slab: float) -> None:
        if web_count < 1:
            raise ValueError("web_count must be at least 1")
        if deck_width <= 0 or depth <= 0:
            raise ValueError("deck_width and depth must be positive")
        if overhang < 0:
            raise ValueError(f"overhang {overhang:g} ft cannot be negative")
        if top_slab <= 0 or bot_slab <= 0:
            raise ValueError(
                f"slab thicknesses must be positive (top {top_slab:g}, "
                f"bot {bot_slab:g})")
        if 2 * overhang >= deck_width:
            raise ValueError(
                f"overhang {overhang:g} ft x2 consumes the {deck_width:g} ft "
                f"deck; no soffit is left")
        if top_slab + bot_slab >= depth:
            raise ValueError(
                f"slabs {top_slab:g} + {bot_slab:g} ft consume the "
                f"{depth:g} ft structure depth; no cell is left")
        soffit_w = deck_width - 2.0 * overhang
        # web_thickness only shapes the section when there are cells to
        # separate; validating it on a solid (web_count=1) section would
        # reject a valid deck over a parameter that changes nothing
        if web_count > 1:
            if web_thickness <= 0:
                raise ValueError(
                    f"web_thickness {web_thickness:g} must be positive")
            if web_count * web_thickness >= soffit_w:
                raise ValueError(
                    f"{web_count} webs x {web_thickness:g} ft exceed the "
                    f"{soffit_w:g} ft soffit width")
        self.deck_width, self.depth = float(deck_width), float(depth)
        self.overhang, self.web_count = float(overhang), int(web_count)
        self.web_thickness = float(web_thickness)
        self.top_slab, self.bot_slab = float(top_slab), float(bot_slab)
        self.soffit_width = soffit_w

        hw, hs = deck_width / 2.0, soffit_w / 2.0
        z_soffit, z_top = -self.depth, 0.0
        z_deck_u = -self.top_slab            # underside of the deck slab
        z_soffit_u = z_soffit + self.bot_slab
        # From the left (+x) deck edge, down the left overhang, along the
        # soffit, up the right side and back across the deck. This traversal
        # winds CW in (x, z); nothing downstream cares (poly_area is
        # absolute, ring_centroid is winding-independent, and keyhole_ring
        # re-winds outer and holes itself), so it is stated rather than
        # "corrected" into a reversal that would only look tidier.
        if hw - hs > 1e-12:
            self.outline = [
                (hw, z_top), (hw, z_deck_u), (hs, z_deck_u), (hs, z_soffit),
                (-hs, z_soffit), (-hs, z_deck_u), (-hw, z_deck_u),
                (-hw, z_top),
            ]
        else:
            # overhang 0: the deck edge IS the soffit edge, so the step
            # points coincide - emit the plain rectangle instead of a ring
            # carrying two zero-length edges
            self.outline = [(hw, z_top), (hw, z_soffit),
                            (-hw, z_soffit), (-hw, z_top)]
        # cells: clear bays between webs, webs spaced evenly across the soffit
        self.voids = []
        cells = self.web_count - 1
        if cells:
            clear = (soffit_w - self.web_count * self.web_thickness) / cells
            x = hs - self.web_thickness             # left edge of cell 1
            for _ in range(cells):
                self.voids.append([
                    (x, z_deck_u), (x, z_soffit_u),
                    (x - clear, z_soffit_u), (x - clear, z_deck_u)])
                x -= clear + self.web_thickness
            self.cell_clear_width = clear
        else:
            self.cell_clear_width = 0.0

    def describe(self) -> str:
        """One-line estimator note: what section actually got built.

        Carried onto every deck element so a `web_count=1` typo shows up as
        "SOLID (no cells)" in the model instead of quietly pricing a solid
        block as if it were a girder."""
        cells = len(self.voids)
        shape = (f"{cells}-cell box" if cells
                 else "SOLID section (no cells)")
        return (f"{shape}, {self.deck_width:g} ft deck x {self.depth:g} ft "
                f"deep, {self.web_count} web(s) @ {self.web_thickness:g} ft, "
                f"slabs {self.top_slab:g}/{self.bot_slab:g} ft")

    @property
    def gross_area_sf(self) -> float:
        """Area of the exterior polygon, cells NOT deducted."""
        from bimforge.author.alignment import poly_area
        return poly_area(self.outline)

    @property
    def area_sf(self) -> float:
        """Net concrete area: exterior minus the cells."""
        from bimforge.author.alignment import poly_area
        return self.gross_area_sf - sum(poly_area(v) for v in self.voids)

    @property
    def soffit_z(self) -> float:
        """Section-z of the soffit (negative, = -depth)."""
        return -self.depth

    def web_centers(self) -> list[float]:
        """Section-x of each web centreline, left (+x) to right."""
        hs = self.soffit_width / 2.0
        if self.web_count == 1:
            return [0.0]
        step = (self.soffit_width - self.web_thickness) / (self.web_count - 1)
        return [hs - self.web_thickness / 2.0 - i * step
                for i in range(self.web_count)]
