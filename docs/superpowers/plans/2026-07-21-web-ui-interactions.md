# Web UI Interactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Random scan button, curved/sagging patch cables (both live drag-preview and committed connections), and a source list panel with per-source Remove, to `webapp/` — matching the desktop Tkinter app's interaction patterns.

**Architecture:** All changes are contained in `webapp/main.js`, `webapp/index.html`, and `webapp/style.css`. No changes to `webapp/worker.js` or any Python file — `remove_source` is already a supported worker message (see `webapp/worker.js:120-121`). `this.sources` (a `Map<sourceId, {x,y,color,row,col}>` in `main.js:54`) is already the canonical registry of confirmed sources; this plan extends its stored fields and adds rendering on top of it.

**Tech Stack:** Vanilla JS (ES2020 class syntax), HTML5 Canvas 2D, no build step, no bundler, no test framework (this repo has none for JS — verification is manual in-browser via the Browser preview tool).

## Global Constraints

- No new dependencies, no build step — this must keep working as static files served directly (matches `docs/superpowers/specs/2026-07-17-github-pages-web-port-design.md`).
- Match desktop behavior exactly where the spec calls for it: Random fills fields but does not send (`docs/superpowers/specs/2026-07-21-web-full-parity-design.md`, Sub-project 1).
- Cable sag curve formula must match desktop's `_patch_cable_points` (`audio_prototype/gui.py:129-140`) exactly: `sag = clamp(|dx| * 0.16, 24, 72)`, 12 steps, `y = lerp(y1,y2,t) + sag * 4 * t * (1-t)`.
- Remove fully deletes a source (disconnects + removes), matching desktop `_on_remove` semantics.

---

### Task 1: Random button

**Files:**
- Modify: `webapp/index.html:25` (add button)
- Modify: `webapp/main.js:1-22` (add constants), `webapp/main.js:149-163` (`bindControls`)

**Interfaces:**
- Consumes: `pickerCoordsToHsv(x, y, w, h)` (`main.js:41-49`, unchanged), `this.currentHsv` (`main.js:65`), `this.bpmInput` (`main.js:71`).
- Produces: `App.onRandom()` — no other task depends on this method.

- [ ] **Step 1: Add the Random button to the HTML**

In `webapp/index.html`, insert a new button right before the existing Send button (currently line 25: `<button id="send-button">Send</button>`):

```html
      <button id="random-button">Random</button>
      <button id="send-button">Send</button>
```

- [ ] **Step 2: Add BPM range constants to main.js**

At the top of `webapp/main.js`, after the existing gamut constants (after line 21, `const FINGER_VAL_MAX = 0.98;`), add:

```js
// Desktop's RANDOM_BPM_MIN/MAX (gui.py:39-40) -- the range the Random
// button samples from, distinct from the wider 20-300 manual BPM range.
const RANDOM_BPM_MIN = 45;
const RANDOM_BPM_MAX = 180;
```

- [ ] **Step 3: Implement `onRandom()` and wire the button**

In `webapp/main.js`, add this method to the `App` class, right after `onPick(event)` (after line 147):

```js
  onRandom() {
    const x = Math.random() * this.pickerCanvas.width;
    const y = Math.random() * this.pickerCanvas.height;
    this.currentHsv = pickerCoordsToHsv(x, y, this.pickerCanvas.width, this.pickerCanvas.height);
    const bpm = Math.round(RANDOM_BPM_MIN + Math.random() * (RANDOM_BPM_MAX - RANDOM_BPM_MIN));
    this.bpmInput.value = bpm;
  }
```

In `bindControls()` (`main.js:149-163`), add this line right after the existing send-button binding (after line 150):

```js
    document.getElementById("random-button").addEventListener("click", () => this.onRandom());
```

- [ ] **Step 4: Manually verify in-browser**

Use the Browser preview tool to open `webapp/index.html` (serve the repo root, e.g. `python -m http.server` from the repo root, then navigate to `http://localhost:<port>/webapp/`). Wait for the status banner to clear (Pyodide finishes loading). Click **Random** several times and confirm the BPM input field's value changes each time to a number between 45 and 180. Click **Send** afterward and confirm a new source dot appears in the patch bay at the expected color (i.e. Random did not auto-send — no dot appears until Send is clicked).

- [ ] **Step 5: Commit**

```bash
git add webapp/index.html webapp/main.js
git commit -m "feat(webapp): add Random scan button"
```

---

### Task 2: Sagging cable curve for committed connections

**Files:**
- Modify: `webapp/main.js:23-49` (add `cablePoints`/`drawCable` helpers near the top-level functions), `webapp/main.js:287-330` (`drawPatchBay`)

**Interfaces:**
- Consumes: nothing new.
- Produces: top-level functions `cablePoints(x1, y1, x2, y2)` → `Array<[number, number]>`, and `drawCable(ctx, x1, y1, x2, y2, color, dashed)` — Task 3 reuses `drawCable` for the live drag preview.

- [ ] **Step 1: Add the cable curve helpers**

In `webapp/main.js`, add these two top-level functions right after `pickerCoordsToHsv` (after line 49, before `class App`):

```js
// Matches desktop's _patch_cable_points (audio_prototype/gui.py:129-140):
// a 12-step parabolic sag curve, sag clamped to [24, 72] scaled by the
// horizontal distance between the two ends.
function cablePoints(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const sag = Math.min(72, Math.max(24, Math.abs(dx) * 0.16));
  const steps = 12;
  const points = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const x = x1 + dx * t;
    const baseline = y1 + (y2 - y1) * t;
    const y = baseline + sag * 4 * t * (1 - t);
    points.push([x, y]);
  }
  return points;
}

function drawCable(ctx, x1, y1, x2, y2, color, dashed) {
  const points = cablePoints(x1, y1, x2, y2);
  ctx.beginPath();
  ctx.moveTo(points[0][0], points[0][1]);
  for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.setLineDash(dashed ? [4, 3] : []);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.lineWidth = 1;
}
```

- [ ] **Step 2: Replace the straight-line draw in `drawPatchBay` with the curve**

In `webapp/main.js`, inside `drawPatchBay()` (`main.js:287-330`), replace the existing straight-line block (lines 318-328):

```js
      if (source.row !== null) {
        const cx = PATCH_GRID_X + source.col * PATCH_CELL + PATCH_CELL / 2;
        const cy = PATCH_GRID_Y + source.row * PATCH_CELL + PATCH_CELL / 2;
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(cx, cy);
        ctx.strokeStyle = source.color;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.lineWidth = 1;
      }
```

with:

```js
      if (source.row !== null) {
        const cx = PATCH_GRID_X + source.col * PATCH_CELL + PATCH_CELL / 2;
        const cy = PATCH_GRID_Y + source.row * PATCH_CELL + PATCH_CELL / 2;
        drawCable(ctx, source.x, source.y, cx, cy, source.color, false);
      }
```

- [ ] **Step 3: Manually verify in-browser**

Reload the page in the Browser preview tool, click Send to create a source, drag its dot onto any patch cell, and release. Confirm the connection line now visibly sags (curves downward toward the middle) rather than being perfectly straight, and is still color-matched and 2px wide.

- [ ] **Step 4: Commit**

```bash
git add webapp/main.js
git commit -m "feat(webapp): render patch cables with a sagging curve"
```

---

### Task 3: Live cable-drag preview

**Files:**
- Modify: `webapp/main.js:64` (add `dragPos` field), `webapp/main.js:246-257` (`onPatchPress`, `onPatchDrag`), `webapp/main.js:259-285` (`onPatchRelease`), `webapp/main.js:287-330` (`drawPatchBay`)

**Interfaces:**
- Consumes: `drawCable(ctx, x1, y1, x2, y2, color, dashed)` from Task 2.
- Produces: `this.dragPos` (`{x, y} | null`) — no other task depends on this.

- [ ] **Step 1: Track drag position**

In the `App` constructor (`main.js:64`), right after `this.dragSourceId = null;`, add:

```js
    this.dragPos = null;
```

- [ ] **Step 2: Set `dragPos` on press, clear it on release**

In `onPatchPress` (`main.js:246-251`), replace:

```js
  onPatchPress(event) {
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    this.dragSourceId = this.nearestSource(x, y);
  }
```

with:

```js
  onPatchPress(event) {
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    this.dragSourceId = this.nearestSource(x, y);
    this.dragPos = null;
  }
```

At the end of `onPatchRelease` (`main.js:259-285`), right before `this.dragSourceId = null;` (currently line 283), add:

```js
    this.dragPos = null;
```

so the tail of the method reads:

```js
    this.dragPos = null;
    this.dragSourceId = null;
    this.drawPatchBay();
```

- [ ] **Step 3: Implement the live preview in `onPatchDrag`**

Replace the current no-op `onPatchDrag` (`main.js:253-257`):

```js
  onPatchDrag(_event) {
    if (this.dragSourceId === null) return;
    // Cable preview omitted for MVP simplicity; the grid + jacks alone
    // are enough to show connection state once released.
  }
```

with:

```js
  onPatchDrag(event) {
    if (this.dragSourceId === null) return;
    const rect = this.patchCanvas.getBoundingClientRect();
    this.dragPos = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    this.drawPatchBay();
  }
```

- [ ] **Step 4: Draw the dashed preview cable in `drawPatchBay`**

In `drawPatchBay()` (`main.js:287-330`), add this block right after the `for (const [, source] of this.sources) { ... }` loop ends (after the closing `}` that follows the cable-drawing code from Task 2, before the final closing `}` of the method):

```js
    if (this.dragSourceId !== null && this.dragPos) {
      const source = this.sources.get(this.dragSourceId);
      if (source) {
        drawCable(ctx, source.x, source.y, this.dragPos.x, this.dragPos.y, source.color, true);
      }
    }
```

- [ ] **Step 5: Manually verify in-browser**

Reload the page, click Send to create a source, press down on its dot and drag toward the patch grid without releasing. Confirm a dashed, color-matched, sagging line follows the cursor in real time. Release over a cell and confirm the dashed preview is replaced by the solid committed cable from Task 2. Press and drag again, then release outside the grid, and confirm the dashed preview disappears with no committed cable drawn (disconnect path still works).

- [ ] **Step 6: Commit**

```bash
git add webapp/main.js
git commit -m "feat(webapp): show a live dashed cable preview while dragging"
```

---

### Task 4: Source list panel with Remove

**Files:**
- Modify: `webapp/index.html:30-34` (add a Sources section between Patch Bay and Debug)
- Modify: `webapp/style.css` (append list styling)
- Modify: `webapp/main.js:51-81` (constructor: cache new element, extend stored source fields), `webapp/main.js:217-230` (`finishPendingSource`), `webapp/main.js:259-285` (`onPatchRelease`)

**Interfaces:**
- Consumes: `this.sources` Map (`main.js:54`), `this.worker.postMessage` (existing pattern).
- Produces: `App.renderSourceList()`, `App.onRemoveSource(sourceId)` — no other task depends on these.

- [ ] **Step 1: Add the Sources section to the HTML**

In `webapp/index.html`, insert a new `<section>` between the existing Patch Bay section (ends at line 34) and the Debug section (starts at line 36):

```html
    <section id="sources">
      <h2>Sources</h2>
      <ul id="source-list"></ul>
    </section>
```

- [ ] **Step 2: Add list styling to style.css**

Append to `webapp/style.css`:

```css
#source-list {
  list-style: none;
  padding: 0;
  margin: 6px 0 0;
  min-width: 220px;
}

#source-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 0.85em;
}

#source-list .swatch {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid #f0f0f0;
  flex-shrink: 0;
}

#source-list .source-cell {
  flex-grow: 1;
  color: #ccc;
}
```

- [ ] **Step 3: Cache the list element and extend stored source fields**

In the `App` constructor (`main.js:51-81`), right after `this.playPauseButton = document.getElementById("play-pause-button");` (line 74), add:

```js
    this.sourceListEl = document.getElementById("source-list");
```

In `finishPendingSource` (`main.js:217-230`), the `this.sources.set(...)` call currently stores `{x, y, color, row, col}`. Add `bpm` so the list can display it. Replace:

```js
  finishPendingSource(sourceId) {
    // The worker replies to add_source requests strictly in the order it
    // received them, so the oldest queued entry always matches this reply.
    const pending = this._pendingSources.shift();
    const slot = this.sources.size;
    this.sources.set(sourceId, {
      x: PATCH_SOURCE_X,
      y: PATCH_SOURCE_TOP + slot * PATCH_SOURCE_GAP,
      color: pending.color,
      row: null,
      col: null,
    });
    this.drawPatchBay();
  }
```

with:

```js
  finishPendingSource(sourceId) {
    // The worker replies to add_source requests strictly in the order it
    // received them, so the oldest queued entry always matches this reply.
    const pending = this._pendingSources.shift();
    const slot = this.sources.size;
    this.sources.set(sourceId, {
      x: PATCH_SOURCE_X,
      y: PATCH_SOURCE_TOP + slot * PATCH_SOURCE_GAP,
      color: pending.color,
      bpm: pending.bpm,
      row: null,
      col: null,
    });
    this.drawPatchBay();
    this.renderSourceList();
  }
```

- [ ] **Step 4: Implement `renderSourceList()` and `onRemoveSource()`**

Add these two methods to the `App` class, right after `drawPatchBay()` (after line 330, i.e. right before the closing `}` of the class):

```js
  cellLabel(row, col) {
    if (row === null) return "unconnected";
    if (row === 0 && col === 4) return "reverb";
    const labels = row === 0 ? TAPE_COL_LABELS : GRANULES_COL_LABELS;
    return `${ROW_LABELS[row]} / ${labels[col]}`;
  }

  renderSourceList() {
    this.sourceListEl.innerHTML = "";
    for (const [sourceId, source] of this.sources) {
      const li = document.createElement("li");

      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = source.color;

      const label = document.createElement("span");
      label.className = "source-cell";
      label.textContent = `${Math.round(source.bpm)} BPM — ${this.cellLabel(source.row, source.col)}`;

      const removeButton = document.createElement("button");
      removeButton.textContent = "Remove";
      removeButton.addEventListener("click", () => this.onRemoveSource(sourceId));

      li.append(swatch, label, removeButton);
      this.sourceListEl.appendChild(li);
    }
  }

  onRemoveSource(sourceId) {
    this.worker.postMessage({ type: "remove_source", sourceId });
    this.sources.delete(sourceId);
    this.drawPatchBay();
    this.renderSourceList();
  }
```

- [ ] **Step 5: Refresh the list wherever connection state changes**

In `onPatchRelease` (`main.js:259-285`), the method ends with `this.dragSourceId = null; this.drawPatchBay();` (after Task 3's edit, also `this.dragPos = null;`). Add a call to keep the list's cell-label text in sync after a connect/disconnect. Replace the tail:

```js
    this.dragPos = null;
    this.dragSourceId = null;
    this.drawPatchBay();
  }
```

with:

```js
    this.dragPos = null;
    this.dragSourceId = null;
    this.drawPatchBay();
    this.renderSourceList();
  }
```

- [ ] **Step 6: Manually verify in-browser**

Reload the page. Click Send twice to create two sources with different colors/BPMs; confirm two rows appear in the Sources list with matching swatch colors, correct BPM numbers, and "unconnected". Drag one source onto a patch cell and release; confirm its list row updates to show the correct row/column label (e.g. "tape / dropout"), and dragging onto the tape row's reverb cell (row 0, col 4) shows "reverb". Click Remove on a connected source; confirm its dot and cable disappear from the patch bay, its row disappears from the list, and a new Send afterward can reuse the freed slot without hitting the "Maximum patch outputs reached" alert prematurely. Confirm a source sent but not yet confirmed (rapid double-click Send) does not appear in the list until its dot appears on the canvas.

- [ ] **Step 7: Commit**

```bash
git add webapp/index.html webapp/style.css webapp/main.js
git commit -m "feat(webapp): add source list panel with per-source Remove"
```
