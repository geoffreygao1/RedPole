# Web Full 5x5 Patch Bay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grow `webapp/`'s patch bay from 2 rows / 8 sources to the desktop app's full 5 rows x 5 columns / 25 sources, with the same row order, column labels, and reverb-cell override.

**Architecture:** Pure `webapp/main.js` + canvas-sizing change in `webapp/index.html`. No worker/Python protocol change — `connect_source` already accepts an arbitrary `engine` string (`webapp/worker.js:112-117`); this plan just sends more valid values (`microloop`, `glitch`, `multidelay`, in addition to the existing `tape`/`granules`/`reverb`).

**Tech Stack:** Vanilla JS, HTML5 Canvas 2D, no build step.

**Depends on:** `docs/superpowers/plans/2026-07-21-web-ui-interactions.md` (assumes `drawCable`/`cablePoints` from that plan's Task 2 already exist, since `drawPatchBay` will be reusing them for a 25-cable bay). Apply this plan after that one.

## Global Constraints

- Row order and engine names must exactly match desktop `PATCH_ROW_ENGINES` (`audio_prototype/gui.py:44`): `("microloop", "granules", "glitch", "multidelay", "tape")`.
- Column labels: `tape` row uses `("wow", "flutter", "tone", "dropout", "reverb")` (desktop `PATCH_TAPE_COL_LABELS`, `gui.py:45`); all other rows use `("I", "II", "III", "IV", "V")` (desktop `PATCH_COL_LABELS`, `gui.py:46`).
- Cell (row=`tape`, col=4) always resolves to engine `"reverb"` regardless of row, matching desktop `_patch_cell_to_engine` (`gui.py:83-88`).
- `PATCH_SOURCE_LIMIT` must be 25, matching desktop (`gui.py:56`).

---

### Task 1: Expand grid constants and canvas size

**Files:**
- Modify: `webapp/main.js:1-12` (grid/source constants)
- Modify: `webapp/index.html:33` (`patch-canvas` width/height)

**Interfaces:**
- Consumes: nothing new.
- Produces: updated `PATCH_GRID_ROWS`, `ROW_LABELS`, `PATCH_SOURCE_LIMIT`, `PATCH_SOURCE_GAP` values that Tasks 2-3 rely on.

- [ ] **Step 1: Update the grid/source constants in main.js**

Replace `webapp/main.js:1-12`:

```js
const PATCH_GRID_ROWS = 2;
const PATCH_GRID_COLS = 5;
const PATCH_CELL = 58;
const PATCH_GRID_X = 340;
const PATCH_GRID_Y = 20;
const PATCH_SOURCE_X = 40;
const PATCH_SOURCE_TOP = 30;
const PATCH_SOURCE_GAP = 28;
const PATCH_SOURCE_LIMIT = 8;
const ROW_LABELS = ["tape", "granules"];
const TAPE_COL_LABELS = ["wow", "flutter", "tone", "dropout", "reverb"];
const GRANULES_COL_LABELS = ["I", "II", "III", "IV", "V"];
```

with:

```js
const PATCH_GRID_ROWS = 5;
const PATCH_GRID_COLS = 5;
const PATCH_CELL = 58;
const PATCH_GRID_X = 340;
const PATCH_GRID_Y = 20;
const PATCH_SOURCE_X = 40;
const PATCH_SOURCE_TOP = 30;
const PATCH_SOURCE_GAP = 20;
const PATCH_SOURCE_LIMIT = 25;
// Matches desktop PATCH_ROW_ENGINES (audio_prototype/gui.py:44) -- row
// order and engine names sent in connect_source's "engine" field.
const ROW_LABELS = ["microloop", "granules", "glitch", "multidelay", "tape"];
const TAPE_ROW_INDEX = ROW_LABELS.indexOf("tape");
const TAPE_COL_LABELS = ["wow", "flutter", "tone", "dropout", "reverb"];
const VARIANT_COL_LABELS = ["I", "II", "III", "IV", "V"];
```

Note `GRANULES_COL_LABELS` is renamed `VARIANT_COL_LABELS` since it's now shared by four rows (`microloop`, `granules`, `glitch`, `multidelay`), not just granules. `PATCH_SOURCE_GAP` shrinks from 28 to 20 so 25 stacked source dots fit within a reasonable canvas height alongside 5 grid rows.

- [ ] **Step 2: Resize the patch canvas**

In `webapp/index.html`, the patch bay canvas is currently:

```html
      <canvas id="patch-canvas" width="640" height="260"></canvas>
```

Replace with (taller to fit 5 rows x 58px cells plus a header margin, and to fit 25 stacked source dots at 20px spacing):

```html
      <canvas id="patch-canvas" width="640" height="520"></canvas>
```

- [ ] **Step 3: Manually verify in-browser**

Serve the repo root and open `webapp/index.html` in the Browser preview tool. Confirm the page loads without JS console errors (the renamed `GRANULES_COL_LABELS` → `VARIANT_COL_LABELS` must have no remaining references to the old name — check via the Browser tool's console). The patch bay canvas should now render taller; grid contents will be fixed in Task 2.

- [ ] **Step 4: Commit**

```bash
git add webapp/main.js webapp/index.html
git commit -m "feat(webapp): expand patch bay constants to 5x5/25 sources"
```

---

### Task 2: Update grid rendering and hit-testing for 5 rows

**Files:**
- Modify: `webapp/main.js:232-237` (`cellAt`, unchanged logic but now spans 5 rows automatically via `PATCH_GRID_ROWS`)
- Modify: `webapp/main.js:259-285` (`onPatchRelease` — engine resolution)
- Modify: `webapp/main.js:287-330` (`drawPatchBay` — row label loop)

**Interfaces:**
- Consumes: `ROW_LABELS`, `TAPE_ROW_INDEX`, `TAPE_COL_LABELS`, `VARIANT_COL_LABELS`, `PATCH_GRID_ROWS` from Task 1.
- Produces: no new methods; behavior change only.

- [ ] **Step 1: Fix engine resolution in `onPatchRelease`**

`cellAt` (`main.js:232-237`) already loops correctly against `PATCH_GRID_ROWS`/`PATCH_GRID_COLS` — no change needed there since it was already generic. In `onPatchRelease` (`main.js:259-285`), the engine-resolution line currently reads:

```js
      const engine = cell.row === 0 && cell.col === 4 ? "reverb" : ROW_LABELS[cell.row];
```

Replace with (the reverb override cell moves from row 0 to the `tape` row, matching desktop's `row == 4` which is desktop's tape row index):

```js
      const engine = cell.row === TAPE_ROW_INDEX && cell.col === 4 ? "reverb" : ROW_LABELS[cell.row];
```

- [ ] **Step 2: Fix column labels per row in `drawPatchBay`**

In `drawPatchBay()` (`main.js:287-330`), the row-label loop currently reads:

```js
    for (let row = 0; row < PATCH_GRID_ROWS; row++) {
      const labels = row === 0 ? TAPE_COL_LABELS : GRANULES_COL_LABELS;
```

Replace with:

```js
    for (let row = 0; row < PATCH_GRID_ROWS; row++) {
      const labels = row === TAPE_ROW_INDEX ? TAPE_COL_LABELS : VARIANT_COL_LABELS;
```

- [ ] **Step 3: Manually verify in-browser**

Reload the page. Confirm the patch bay now draws 5 rows labeled `microloop`, `granules`, `glitch`, `multidelay`, `tape` (top to bottom, per `ROW_LABELS` order) and 5 columns. Confirm the `tape` row's columns read `wow`/`flutter`/`tone`/`dropout`/`reverb`, and every other row's columns read `I`/`II`/`III`/`IV`/`V`. Send a source, drag it onto the `tape` row's 5th column (`reverb` label) and release; open the Browser tool's network/console (or add a temporary `console.log` if needed) to confirm `connect_source` was posted with `engine: "reverb"`. Drag another source onto the `microloop` row, any column, and confirm `connect_source` posts `engine: "microloop"`.

- [ ] **Step 4: Commit**

```bash
git add webapp/main.js
git commit -m "feat(webapp): render and connect across all 5 patch bay rows"
```

---

### Task 3: Verify 25-source capacity end-to-end

**Files:**
- No source changes — this task is verification-only, confirming Tasks 1-2 together deliver the full spec requirement.

**Interfaces:**
- Consumes: everything from Tasks 1-2.
- Produces: nothing (verification checkpoint).

- [ ] **Step 1: Manually verify the full 25-source flow in-browser**

Reload the page. Click Send 25 times (waiting briefly between clicks if needed for `source_added` replies to keep the pending queue accurate) and confirm no "Maximum patch outputs reached" alert appears until after the 25th confirmed source. Click Send a 26th time and confirm the alert now appears and no 26th source is created. Drag several of the 25 sources onto different cells across all 5 rows (including at least one onto the reverb override cell) and confirm each connects without error and its cable renders correctly. Remove a few sources via the Task-4-from-the-UI-interactions-plan Remove button (if that plan has already been applied) or by dragging outside the grid to disconnect, and confirm the patch bay remains visually correct (no overlapping dots, no stale cables).

- [ ] **Step 2: Commit**

No code changes in this task — nothing to commit. If any bug is found during verification, fix it as part of Task 1 or 2 above (amend those commits' follow-up with a new commit, not by editing history) and re-run this verification step.
