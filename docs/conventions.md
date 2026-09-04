# Structura — Sign, Unit and DOF Conventions

**This document is a contract.** Every formula in `structura.core.analysis` and every assertion in
`tests/` is written against it. If a result looks wrong, the bug is either in the code or in this
document — never in "how the textbook I happened to open does it".

Do not copy sign conventions from other sources into the codebase. Derive against this page.

---

## 1. Units

**The solver only ever sees SI base units.**

| Quantity | Solver unit |
|---|---|
| Length, coordinate, displacement | metre (m) |
| Force | newton (N) |
| Moment | newton-metre (N·m) |
| Distributed load intensity | newton per metre (N/m) |
| Elastic modulus, stress | pascal (Pa) |
| Area | m² |
| Second moment of area | m⁴ |
| Angle, rotation | radian (rad) |
| Density | kg/m³ |

Conversion to and from user-facing units (kN, mm, GPa, degrees) happens **only** in
`structura.core.units` and is applied at the GUI / file-import boundary. There is no unit
conversion anywhere inside `structura.core.analysis`. The `.stru` file stores SI base units; its
`display_units` block is a UI preference and carries no numerical meaning.

---

## 2. Global axes

- **+X** points right.
- **+Y** points up.
- **+Z** points out of the screen, toward the viewer.
- **Moments and rotations are counter-clockwise (CCW) positive**, i.e. about +Z by the right-hand
  rule.

The drawing canvas uses screen coordinates where Y grows downward. That flip is confined to
`structura.gui.scene.coords` and never reaches the model or the solver.

---

## 3. Degrees of freedom

Every node owns **three** DOFs, in this fixed order:

| Local slot | Meaning |
|---|---|
| 0 | `ux` — translation along global +X |
| 1 | `uy` — translation along global +Y |
| 2 | `rz` — rotation about global +Z, CCW positive |

For the node occupying **0-based position `n`** in the `DofMap` ordering, the global DOF indices
are `3n`, `3n + 1`, `3n + 2`.

> Node **position** in the DofMap is not the node **id**. Ids are stable, sparse and never reused;
> positions are dense and assigned at assembly time. Always go through `DofMap`.

### Truss mode

Truss elements contribute no rotational stiffness, so every `rz` row and column would be
identically zero and `K` would be singular. In truss mode the `DofMap` therefore
**automatically adds every `rz` DOF to the constrained set** before partitioning.

Consequence: the value computed at those DOFs during reaction recovery is identically zero and is
**not a physical reaction moment**. It must never be displayed or exported.

---

## 4. Element local axes

For a member running from node **i** to node **j**:

- **Local x** points from i to j. Its direction cosines are `c = (xj − xi)/L`, `s = (yj − yi)/L`.
- **Local y** is 90° CCW from local x, i.e. direction `(−s, c)`.
- **Local z** coincides with global +Z.

The member angle reported to the user is `atan2(yj − yi, xj − xi)`, in degrees, in `(−180°, 180°]`.

Local DOF order for the 6-DOF frame element:

```
[ u_i , v_i , θ_i , u_j , v_j , θ_j ]
```

The 4-DOF truss element uses `[ u_i , v_i , u_j , v_j ]`.

Transformation: `u_local = T · u_global`, `k_global = Tᵀ · k_local · T`.

---

## 5. Member end forces

The recovery equation is

```
f_local = k_local · (T · u_global) + f_FE_local
```

where `f_FE_local` is the **fixed-end force vector** for any loads applied along the member span.
Omitting that second term leaves reactions correct but makes bending moments wrong in mid-span —
see `docs/` note in §9.

`f_local` is ordered `[N_i, V_i, M_i, N_j, V_j, M_j]` and is interpreted as:

> **the forces and moments that the nodes exert on the member**, expressed in local axes.

---

## 6. Internal force diagrams

Cut the member at local coordinate `x ∈ [0, L]` and take the free body of the segment `[0, x]`.

Let

- `p(ξ)` = distributed **axial** load intensity, positive along local **+x**;
- `w(ξ)` = distributed **transverse** load intensity, positive along local **+y**.

Then:

### Axial force — **tension positive**

```
N(x) = − N_i − ∫₀ˣ p(ξ) dξ
```

*Check:* a bar in pure tension `T` has the node at end i pulling the member outward (local −x), so
`N_i = −T` and `N(x) = +T`. ✔

### Shear force

```
V(x) = V_i + ∫₀ˣ w(ξ) dξ        (+ ΣP_y for every point load at a < x)
```

`V(x)` is the algebraic sum of transverse forces on the segment to the left of the cut, measured
along local **+y**.

*Check:* simply supported beam, span `L`, downward UDL of intensity `q` (so `w = −q`). The left
reaction pushes the member up, `V_i = +qL/2`, giving `V(x) = qL/2 − qx`: `+qL/2` at the left end,
zero at midspan, `−qL/2` at the right end. ✔

### Bending moment — **sagging positive**

```
M(x) = − M_i + x · V_i + ∫₀ˣ (x − ξ) · w(ξ) dξ
                        (+ Σ (x − a)·P_y  for point loads at a < x)
                        (−  Σ M₀          for applied moments at a < x)
```

*Check 1 — SS beam, downward UDL `q`:* `M_i = 0`, `V_i = qL/2`, `w = −q`
→ `M(x) = qLx/2 − qx²/2`, maximum `qL²/8` at midspan, sagging positive. ✔

*Check 2 — cantilever fixed at i, downward point load `P` at the free end:* the support exerts
`V_i = +P` and `M_i = +PL` on the member, so `M(x) = −PL + Px`: `−PL` (hogging) at the fixed end,
zero at the free end. ✔

*Check 3 — SS beam with a CCW moment `M₀` applied at midspan:* `M` rises linearly to `+M₀/2`, jumps
**down** by `M₀` to `−M₀/2`, then returns to zero at the right support. An applied CCW moment makes
the BMD step downward. ✔

### Differential identities (used directly as automated tests)

```
dM/dx = V(x)          dV/dx = w(x)
```

Note `dV/dx = w` and not `−w`, because `w` here is positive along local **+y**, whereas textbooks
usually define the load intensity as positive downward.

---

## 7. Reactions vs. internal moments — they legitimately differ in sign

At a fixed support, the **reaction moment** reported in the reactions table is the moment the
support exerts on the structure (CCW positive, global axes). The **bending moment** shown on the
BMD at that same point is the internal moment (sagging positive, local axes).

For the cantilever of Check 2 these are `+PL` and `−PL` respectively. Both are correct. The UI must
label them distinctly ("Reaction M" vs. "Bending moment") so the difference never reads as a bug.

---

## 8. Diagram plotting

- SFD is plotted with positive shear **above** the member axis.
- BMD is by default plotted **on the tension side** — i.e. positive (sagging) moment plotted
  **below** the axis. This is the usual Indian/British teaching convention.
- A `hogging_positive` display toggle flips the plotted sign. **The stored sign convention never
  changes**; the toggle is presentation only.

---

## 9. Distributed-load direction on inclined members

A "5 kN/m UDL" is ambiguous on a sloping member. Every distributed load carries an explicit
`LoadDirection`:

| Value | Meaning |
|---|---|
| `LOCAL_PERPENDICULAR` | intensity normal to the member, per unit **member** length (wind, pressure) |
| `LOCAL_AXIAL` | intensity along the member, per unit **member** length |
| `GLOBAL_Y` | intensity along global −Y/+Y, per unit **member** length |
| `GLOBAL_Y_PROJECTED` | intensity along global Y, per unit **horizontal** length (gravity, snow) — resolved by multiplying by `cos α` |

`GLOBAL_Y_PROJECTED` is the default for gravity-type loads, because that is how such loads are
specified in practice. For a horizontal member all three vertical variants coincide, which is why
beam-only test cases cannot catch a mistake here — the inclined-member cases must.

---

## 10. Sign summary for the user interface

| Displayed quantity | Positive means |
|---|---|
| Member axial force | **tension** |
| Member bending moment | **sagging** |
| Nodal load `Fx`, `Fy` | along global +X, +Y |
| Nodal moment `Mz` | counter-clockwise |
| Reaction `Rx`, `Ry` | along global +X, +Y |
| Reaction `Mz` | counter-clockwise |
| Displacement `ux`, `uy` | along global +X, +Y |
| Rotation `rz` | counter-clockwise |

A downward 10 kN load is entered as `Fy = −10 kN`. The GUI may offer a "downward" affordance, but
the stored value is signed.
