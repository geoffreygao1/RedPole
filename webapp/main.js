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
const PATCH_ROW_ENGINES = ["microloop", "granules", "glitch", "multidelay", "tape"];
const ROW_LABELS = ["microloop", "granules", "glitch", "multidelay", "shape"];
const TAPE_ROW_INDEX = PATCH_ROW_ENGINES.indexOf("tape");
const VARIANT_COL_LABELS = ["I", "II", "III", "IV", "V"];

// Finger-scan gamut, matching the desktop app's picker (modulation.py's
// FINGER_HUE_MIN/MAX etc.): a bright red-to-orange range.
const FINGER_HUE_MIN = 0.0;
const FINGER_HUE_MAX = 0.085;
const FINGER_SAT_MIN = 0.64;
const FINGER_SAT_MAX = 0.72;
const FINGER_VAL_MIN = 0.9;
const FINGER_VAL_MAX = 0.98;

// Desktop's RANDOM_BPM_MIN/MAX (gui.py:39-40) -- the range the Random
// button samples from, distinct from the wider 20-300 manual BPM range.
const RANDOM_BPM_MIN = 45;
const RANDOM_BPM_MAX = 180;

function hsvToRgb(h, s, v) {
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const t = v * (1 - (1 - f) * s);
  let r, g, b;
  switch (i % 6) {
    case 0: [r, g, b] = [v, t, p]; break;
    case 1: [r, g, b] = [q, v, p]; break;
    case 2: [r, g, b] = [p, v, t]; break;
    case 3: [r, g, b] = [p, q, v]; break;
    case 4: [r, g, b] = [t, p, v]; break;
    default: [r, g, b] = [v, p, q]; break;
  }
  return [r, g, b];
}

function pickerCoordsToHsv(x, y, w, h) {
  const fx = Math.min(1, Math.max(0, x / (w - 1)));
  const fy = Math.min(1, Math.max(0, y / (h - 1)));
  return {
    hue: FINGER_HUE_MIN + (FINGER_HUE_MAX - FINGER_HUE_MIN) * fx,
    val: FINGER_VAL_MAX - (FINGER_VAL_MAX - FINGER_VAL_MIN) * fy,
    sat: FINGER_SAT_MAX - (FINGER_SAT_MAX - FINGER_SAT_MIN) * fy,
  };
}

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

class App {
  constructor() {
    this.worker = new Worker("worker.js");
    this.sources = new Map(); // sourceId -> {x, y, color, bpm, slot, row, col}
    // FIFO queue of sources sent to the worker via "add_source" but not yet
    // confirmed by a "source_added" reply. The worker processes add_source
    // messages (and replies to them) strictly in the order they were sent,
    // so the front of this queue always corresponds to the next
    // "source_added" message we receive. Keeping each in-flight request's
    // data here (rather than a single shared field) prevents rapid repeat
    // clicks of Send from clobbering each other's color/BPM before their
    // replies arrive.
    this._pendingSources = [];
    this.dragSourceId = null;
    this.dragPos = null;
    this.currentHsv = { hue: 0.03, sat: 0.68, val: 0.94 };

    this.statusEl = document.getElementById("status");
    this.appEl = document.getElementById("app");
    this.pickerCanvas = document.getElementById("picker");
    this.patchCanvas = document.getElementById("patch-canvas");
    this.bpmInput = document.getElementById("bpm-input");
    this.bufferReadout = document.getElementById("buffer-readout");
    this.underrunReadout = document.getElementById("underrun-readout");
    this.playPauseButton = document.getElementById("play-pause-button");
    this.sourceListEl = document.getElementById("source-list");

    this.worker.onmessage = (event) => this.onWorkerMessage(event.data);
    this.setupAudio();
    this.buildPicker();
    this.bindControls();
    this.drawPatchBay();
  }

  async setupAudio() {
    this.audioContext = new AudioContext();
    await this.audioContext.audioWorklet.addModule("worklet.js");
    this.workletNode = new AudioWorkletNode(this.audioContext, "ring-worklet-processor", {
      outputChannelCount: [2],
    });
    this.workletNode.connect(this.audioContext.destination);
    this.workletNode.port.onmessage = (event) => {
      if (event.data.type === "status") {
        const ms = Math.round((event.data.bufferedFrames / this.audioContext.sampleRate) * 1000);
        this.bufferReadout.textContent = `Buffered: ${ms} ms`;
        this.underrunReadout.textContent = `Underruns: ${event.data.underruns}`;
      }
    };

    const channel = new MessageChannel();
    this.workletNode.port.postMessage({ type: "link", port: channel.port2 }, [channel.port2]);
    this.worker.postMessage(
      { type: "init", sampleRate: this.audioContext.sampleRate, audioPort: channel.port1 },
      [channel.port1]
    );
  }

  onWorkerMessage(msg) {
    if (msg.type === "ready") {
      this.statusEl.classList.add("hidden");
      this.appEl.classList.remove("hidden");
    } else if (msg.type === "error") {
      this.statusEl.textContent = `Error: ${msg.message}`;
      this.statusEl.classList.remove("hidden");
    } else if (msg.type === "source_added") {
      this.finishPendingSource(msg.sourceId);
    }
  }

  buildPicker() {
    const ctx = this.pickerCanvas.getContext("2d");
    const w = this.pickerCanvas.width;
    const h = this.pickerCanvas.height;
    const image = ctx.createImageData(w, h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const { hue, sat, val } = pickerCoordsToHsv(x, y, w, h);
        const [r, g, b] = hsvToRgb(hue, sat, val);
        const idx = (y * w + x) * 4;
        image.data[idx] = Math.round(r * 255);
        image.data[idx + 1] = Math.round(g * 255);
        image.data[idx + 2] = Math.round(b * 255);
        image.data[idx + 3] = 255;
      }
    }
    ctx.putImageData(image, 0, 0);

    this.pickerCanvas.addEventListener("mousedown", (e) => this.onPick(e));
    this.pickerCanvas.addEventListener("mousemove", (e) => {
      if (e.buttons === 1) this.onPick(e);
    });
  }

  onPick(event) {
    const rect = this.pickerCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    this.currentHsv = pickerCoordsToHsv(x, y, this.pickerCanvas.width, this.pickerCanvas.height);
  }

  onRandom() {
    const x = Math.random() * this.pickerCanvas.width;
    const y = Math.random() * this.pickerCanvas.height;
    this.currentHsv = pickerCoordsToHsv(x, y, this.pickerCanvas.width, this.pickerCanvas.height);
    const bpm = Math.round(RANDOM_BPM_MIN + Math.random() * (RANDOM_BPM_MAX - RANDOM_BPM_MIN));
    this.bpmInput.value = bpm;
  }

  bindControls() {
    document.getElementById("send-button").addEventListener("click", () => this.onSend());
    document.getElementById("random-button").addEventListener("click", () => this.onRandom());
    document.getElementById("play-pause-button").addEventListener("click", () => this.onTogglePlay());
    document.getElementById("wet-dry-slider").addEventListener("input", (e) => {
      this.worker.postMessage({ type: "set_wet_dry", value: parseFloat(e.target.value) });
    });
    document.getElementById("load-loop-button").addEventListener("click", () => {
      document.getElementById("load-loop-file").click();
    });
    document.getElementById("load-loop-file").addEventListener("change", (e) => this.onLoadFile(e));

    this.patchCanvas.addEventListener("mousedown", (e) => this.onPatchPress(e));
    this.patchCanvas.addEventListener("mousemove", (e) => this.onPatchDrag(e));
    this.patchCanvas.addEventListener("mouseup", (e) => this.onPatchRelease(e));
  }

  onTogglePlay() {
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
      this.worker.postMessage({ type: "play" });
      this.playPauseButton.textContent = "Pause";
    } else {
      this.audioContext.suspend();
      this.worker.postMessage({ type: "pause" });
      this.playPauseButton.textContent = "Play";
    }
  }

  async onLoadFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    const arrayBuffer = await file.arrayBuffer();
    const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
    const channels = [];
    for (let ch = 0; ch < audioBuffer.numberOfChannels; ch++) {
      channels.push(audioBuffer.getChannelData(ch));
    }
    const length = audioBuffer.length;
    const mono = new Float32Array(length);
    for (let i = 0; i < length; i++) {
      let sum = 0;
      for (let ch = 0; ch < channels.length; ch++) sum += channels[ch][i];
      mono[i] = sum / channels.length;
    }
    this.worker.postMessage({ type: "load_loop", samples: mono }, [mono.buffer]);
  }

  onSend() {
    // Count confirmed sources plus requests already in flight, so a burst
    // of rapid clicks can't exceed the limit before any "source_added"
    // replies have come back.
    if (this.sources.size + this._pendingSources.length >= PATCH_SOURCE_LIMIT) {
      alert(`Maximum patch outputs reached (${PATCH_SOURCE_LIMIT}).`);
      return;
    }
    let bpm = parseFloat(this.bpmInput.value);
    if (!Number.isFinite(bpm)) {
      bpm = 70;
    } else {
      bpm = Math.min(300, Math.max(20, bpm));
    }
    const { hue, sat, val } = this.currentHsv;
    const [r, g, b] = hsvToRgb(hue, sat, val);
    const color = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
    this._pendingSources.push({ hue, sat, val, bpm, color });
    this.worker.postMessage({ type: "add_source", hue, sat, val, bpm });
  }

  nextSourceSlot() {
    const used = new Set(Array.from(this.sources.values(), (source) => source.slot));
    for (let slot = 0; slot < PATCH_SOURCE_LIMIT; slot++) {
      if (!used.has(slot)) return slot;
    }
    return this.sources.size;
  }

  finishPendingSource(sourceId) {
    // The worker replies to add_source requests strictly in the order it
    // received them, so the oldest queued entry always matches this reply.
    const pending = this._pendingSources.shift();
    const slot = this.nextSourceSlot();
    this.sources.set(sourceId, {
      x: PATCH_SOURCE_X,
      y: PATCH_SOURCE_TOP + slot * PATCH_SOURCE_GAP,
      color: pending.color,
      bpm: pending.bpm,
      slot,
      row: null,
      col: null,
    });
    this.drawPatchBay();
    this.renderSourceList();
  }

  cellAt(x, y) {
    const col = Math.floor((x - PATCH_GRID_X) / PATCH_CELL);
    const row = Math.floor((y - PATCH_GRID_Y) / PATCH_CELL);
    if (row < 0 || row >= PATCH_GRID_ROWS || col < 0 || col >= PATCH_GRID_COLS) return null;
    return { row, col };
  }

  nearestSource(x, y) {
    for (const [sourceId, source] of this.sources) {
      if ((x - source.x) ** 2 + (y - source.y) ** 2 <= 100) return sourceId;
    }
    return null;
  }

  onPatchPress(event) {
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    this.dragSourceId = this.nearestSource(x, y);
    this.dragPos = null;
  }

  onPatchDrag(event) {
    if (this.dragSourceId === null) return;
    const rect = this.patchCanvas.getBoundingClientRect();
    this.dragPos = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    this.drawPatchBay();
  }

  onPatchRelease(event) {
    if (this.dragSourceId === null) return;
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const cell = this.cellAt(x, y);
    const source = this.sources.get(this.dragSourceId);

    if (cell === null) {
      this.worker.postMessage({ type: "disconnect_source", sourceId: this.dragSourceId });
      source.row = null;
      source.col = null;
    } else {
      const engine = cell.row === TAPE_ROW_INDEX && cell.col === 4 ? "reverb" : PATCH_ROW_ENGINES[cell.row];
      this.worker.postMessage({
        type: "connect_source",
        sourceId: this.dragSourceId,
        engine,
        row: cell.row,
        col: cell.col,
      });
      source.row = cell.row;
      source.col = cell.col;
    }
    this.dragPos = null;
    this.dragSourceId = null;
    this.drawPatchBay();
    this.renderSourceList();
  }

  drawPatchBay() {
    const ctx = this.patchCanvas.getContext("2d");
    ctx.fillStyle = "#161616";
    ctx.fillRect(0, 0, this.patchCanvas.width, this.patchCanvas.height);

    const cellColors = new Map();
    for (const [, source] of this.sources) {
      if (source.row !== null) {
        cellColors.set(`${source.row}:${source.col}`, source.color);
      }
    }

    for (let row = 0; row < PATCH_GRID_ROWS; row++) {
      ctx.fillStyle = "#d5d5d5";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(ROW_LABELS[row], PATCH_GRID_X - 12, PATCH_GRID_Y + row * PATCH_CELL + PATCH_CELL / 2);
      ctx.textAlign = "left";
      for (let col = 0; col < PATCH_GRID_COLS; col++) {
        const x0 = PATCH_GRID_X + col * PATCH_CELL;
        const y0 = PATCH_GRID_Y + row * PATCH_CELL;
        ctx.strokeStyle = "#555";
        ctx.fillStyle = cellColors.get(`${row}:${col}`) || "#2a2a2a";
        ctx.fillRect(x0, y0, PATCH_CELL, PATCH_CELL);
        ctx.strokeRect(x0, y0, PATCH_CELL, PATCH_CELL);
        ctx.fillStyle = cellColors.has(`${row}:${col}`) ? "#111" : "#888";
        ctx.font = "9px sans-serif";
        ctx.fillText(VARIANT_COL_LABELS[col], x0 + 6, y0 + 14);
      }
    }

    for (const [, source] of this.sources) {
      ctx.beginPath();
      ctx.arc(source.x, source.y, 8, 0, 2 * Math.PI);
      ctx.fillStyle = source.color;
      ctx.fill();
      ctx.strokeStyle = "#f0f0f0";
      ctx.stroke();

      if (source.row !== null) {
        const cx = PATCH_GRID_X + source.col * PATCH_CELL + PATCH_CELL / 2;
        const cy = PATCH_GRID_Y + source.row * PATCH_CELL + PATCH_CELL / 2;
        drawCable(ctx, source.x, source.y, cx, cy, source.color, false);
      }
    }

    if (this.dragSourceId !== null && this.dragPos) {
      const source = this.sources.get(this.dragSourceId);
      if (source) {
        drawCable(ctx, source.x, source.y, this.dragPos.x, this.dragPos.y, source.color, true);
      }
    }
  }

  cellLabel(row, col) {
    if (row === null) return "unconnected";
    return `${ROW_LABELS[row]} / ${VARIANT_COL_LABELS[col]}`;
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
      label.textContent = `${Math.round(source.bpm)} BPM - ${this.cellLabel(source.row, source.col)}`;

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
    if (this.dragSourceId === sourceId) {
      this.dragSourceId = null;
      this.dragPos = null;
    }
    this.drawPatchBay();
    this.renderSourceList();
  }
}

window.addEventListener("load", () => new App());
