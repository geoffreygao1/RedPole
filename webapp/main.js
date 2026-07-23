import { Scheduler } from "./scheduler.js";
import { ToneEngine } from "./tone_engine.js";
import {
  MACRO_COLS,
  MACRO_ROWS,
  SOURCE_GRID,
  SOURCE_ROWS,
  macroPresetId,
  sourceForSlot,
} from "./soundbath_config.js";
import { deriveFingerprint } from "./generative/fingerprint.js";

const PATCH_GRID_ROWS = 5;
const PATCH_GRID_COLS = 5;
const PATCH_CELL = 58;
const PATCH_GRID_X = 480;
const PATCH_GRID_Y = 56;
const OUTPUT_GRID_X = 36;
const OUTPUT_GRID_Y = 56;
const APP_ASSET_VERSION = Date.now().toString();
const JACK_RADIUS = 9;
const PATCH_SOURCE_LIMIT = 25;
// Matches desktop PATCH_ROW_ENGINES (audio_prototype/gui.py:44) -- row
// order and engine names sent in connect_source's "engine" field.
const PATCH_ROW_ENGINES = ["microloop", "granules", "glitch", "multidelay", "tape"];
const LOOP_ROW_LABELS = ["microloop", "granules", "glitch", "multidelay", "shape"];
const SYNTH_ROW_LABELS = MACRO_ROWS;
const SYNTH_SOURCE_ROWS = SOURCE_ROWS;
const SYNTH_SOURCE_INSTRUMENTS = SOURCE_GRID;
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

function hsvToPickerCoords(hsv, w, h) {
  const hueRange = FINGER_HUE_MAX - FINGER_HUE_MIN;
  const valRange = FINGER_VAL_MAX - FINGER_VAL_MIN;
  const fx = hueRange === 0 ? 0 : (hsv.hue - FINGER_HUE_MIN) / hueRange;
  const fy = valRange === 0 ? 0 : (FINGER_VAL_MAX - hsv.val) / valRange;
  return {
    x: Math.min(w - 1, Math.max(0, fx * (w - 1))),
    y: Math.min(h - 1, Math.max(0, fy * (h - 1))),
  };
}

function hsvToCssColor(hsv) {
  const [r, g, b] = hsvToRgb(hsv.hue, hsv.sat, hsv.val);
  return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
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

function gridCenter(originX, originY, row, col) {
  return {
    x: originX + col * PATCH_CELL + PATCH_CELL / 2,
    y: originY + row * PATCH_CELL + PATCH_CELL / 2,
  };
}

function outputSlotPosition(slot) {
  const row = Math.floor(slot / PATCH_GRID_COLS);
  const col = slot % PATCH_GRID_COLS;
  return gridCenter(OUTPUT_GRID_X, OUTPUT_GRID_Y, row, col);
}

function drawJack(ctx, x, y, color) {
  ctx.beginPath();
  ctx.arc(x, y, JACK_RADIUS, 0, 2 * Math.PI);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.strokeStyle = "#888";
  ctx.stroke();
}

class App {
  constructor() {
    // Loop mode (Pyodide worker + AudioWorklet) is created lazily on first use
    // so the page boots straight into the lightweight Tone.js synth with no
    // ~10 MB WASM/numpy load.
    this.worker = null;
    this.loopReady = false;
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
    this.selectedSourceId = null;
    this.dragSourceId = null;
    this.dragPos = null;
    this.currentHsv = { hue: 0.03, sat: 0.68, val: 0.94 };
    this.mode = "synth";
    this.loopLoaded = false;
    this.nextSynthSourceId = 1;
    this.synthEngine = null;
    this.scheduler = null;
    this.synthReady = false;

    this.statusEl = document.getElementById("status");
    this.appEl = document.getElementById("app");
    this.pickerCanvas = document.getElementById("picker");
    this.scanColorPreview = document.getElementById("scan-color-preview");
    this.patchCanvas = document.getElementById("patch-canvas");
    this.bpmInput = document.getElementById("bpm-input");
    this.bufferReadout = document.getElementById("buffer-readout");
    this.underrunReadout = document.getElementById("underrun-readout");
    this.playPauseButton = document.getElementById("play-pause-button");
    this.sourceListEl = document.getElementById("source-list");
    this.autoAssignSourcesEl = document.getElementById("auto-assign-sources");
    this.modeSwitchButton = document.getElementById("mode-switch");
    this.loadLoopButton = document.getElementById("load-loop-button");
    this.loadSamplesButton = document.getElementById("load-samples-button");
    this.loadSamplesFile = document.getElementById("load-samples-file");
    this.rootSlider = document.getElementById("root-slider");
    this.reverbSlider = document.getElementById("reverb-slider");
    this.delaySlider = document.getElementById("delay-slider");
    this.transposeSlider = document.getElementById("transpose-slider");

    this.buildPicker();
    this.drawPicker();
    this.updateScanPreview();
    this.bindControls();
    this.drawPatchBay();
    this.init();
  }

  async init() {
    // Boot straight into the synth (fast Tone.js init, no Pyodide).
    await this.ensureSynthEngine();
    this.applyModeControls();
    this.appEl.classList.remove("hidden");
    this.statusEl.classList.add("hidden");
    this.drawPatchBay();
    this.renderSourceList();
  }

  // Lazily create the loop-mode engine (Pyodide worker + AudioWorklet ring
  // buffer). Only runs when the user actually switches to / plays loop mode.
  async ensureLoopEngine() {
    if (this.loopReady) return;
    this.worker = new Worker(`worker.js?v=${APP_ASSET_VERSION}`);
    this.worker.onmessage = (event) => this.onWorkerMessage(event.data);
    this.audioContext = new AudioContext();
    await this.audioContext.audioWorklet.addModule(`worklet.js?v=${APP_ASSET_VERSION}`);
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
    this.loopReady = true;
  }

  // Show only the controls relevant to the active mode.
  applyModeControls() {
    const synth = this.mode === "synth";
    const toggleLabel = (el, hide) => {
      const label = el?.closest("label");
      if (label) label.classList.toggle("hidden", hide);
    };
    toggleLabel(document.getElementById("wet-dry-slider"), synth); // loop-only
    toggleLabel(this.rootSlider, !synth); // synth-only
    toggleLabel(this.reverbSlider, !synth);
    toggleLabel(this.delaySlider, !synth);
    toggleLabel(this.transposeSlider, !synth);
    this.loadLoopButton?.classList.toggle("hidden", synth);
    document.getElementById("debug")?.classList.toggle("hidden", synth);
    this.modeSwitchButton?.classList.toggle("synth", synth);
    this.modeSwitchButton?.setAttribute("aria-pressed", synth ? "true" : "false");
  }

  async ensureSynthEngine() {
    if (this.synthReady) return;
    this.statusEl.textContent = "Loading Tone.js synth...";
    this.statusEl.classList.remove("hidden");
    this.synthEngine = new ToneEngine();
    await this.synthEngine.init();
    this.scheduler = new Scheduler(this.synthEngine, { seed: 2130 });
    this.scheduler.start();
    if (this.rootSlider) this.scheduler.setRoot(parseFloat(this.rootSlider.value));
    if (this.reverbSlider) this.synthEngine.setReverb(parseFloat(this.reverbSlider.value));
    if (this.delaySlider) this.synthEngine.setDelay(parseFloat(this.delaySlider.value));
    if (this.transposeSlider) this.synthEngine.setTranspose(parseFloat(this.transposeSlider.value));
    this.synthReady = true;
    this.statusEl.classList.add("hidden");
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
    this.pickerImage = ctx.createImageData(w, h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const { hue, sat, val } = pickerCoordsToHsv(x, y, w, h);
        const [r, g, b] = hsvToRgb(hue, sat, val);
        const idx = (y * w + x) * 4;
        this.pickerImage.data[idx] = Math.round(r * 255);
        this.pickerImage.data[idx + 1] = Math.round(g * 255);
        this.pickerImage.data[idx + 2] = Math.round(b * 255);
        this.pickerImage.data[idx + 3] = 255;
      }
    }

    this.pickerCanvas.addEventListener("mousedown", (e) => this.onPick(e));
    this.pickerCanvas.addEventListener("mousemove", (e) => {
      if (e.buttons === 1) this.onPick(e);
    });
  }

  drawPicker() {
    const ctx = this.pickerCanvas.getContext("2d");
    ctx.putImageData(this.pickerImage, 0, 0);
    const { x, y } = hsvToPickerCoords(
      this.currentHsv,
      this.pickerCanvas.width,
      this.pickerCanvas.height
    );
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, 2 * Math.PI);
    ctx.strokeStyle = "#111";
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, 2 * Math.PI);
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.lineWidth = 1;
  }

  updateScanPreview() {
    this.scanColorPreview.style.background = hsvToCssColor(this.currentHsv);
  }

  onPick(event) {
    const rect = this.pickerCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    this.currentHsv = pickerCoordsToHsv(x, y, this.pickerCanvas.width, this.pickerCanvas.height);
    this.drawPicker();
    this.updateScanPreview();
  }

  onRandom() {
    const x = Math.random() * this.pickerCanvas.width;
    const y = Math.random() * this.pickerCanvas.height;
    this.currentHsv = pickerCoordsToHsv(x, y, this.pickerCanvas.width, this.pickerCanvas.height);
    const bpm = Math.round(RANDOM_BPM_MIN + Math.random() * (RANDOM_BPM_MAX - RANDOM_BPM_MIN));
    this.bpmInput.value = bpm;
    this.drawPicker();
    this.updateScanPreview();
  }

  bindControls() {
    document.getElementById("send-button").addEventListener("click", () => this.onSend());
    document.getElementById("random-button").addEventListener("click", () => this.onRandom());
    document.getElementById("play-pause-button").addEventListener("click", () => this.onTogglePlay());
    this.modeSwitchButton.addEventListener("click", async () => {
      await this.setMode(this.mode === "loop" ? "synth" : "loop");
    });
    document.getElementById("wet-dry-slider").addEventListener("input", (e) => {
      if (this.mode === "synth" || !this.worker) return;
      this.worker.postMessage({ type: "set_wet_dry", value: parseFloat(e.target.value) });
    });
    if (this.rootSlider) {
      this.rootSlider.addEventListener("input", (e) => {
        if (this.mode !== "synth" || !this.scheduler) return;
        this.scheduler.setRoot(parseFloat(e.target.value));
      });
    }
    if (this.reverbSlider) {
      this.reverbSlider.addEventListener("input", (e) => {
        if (this.mode !== "synth" || !this.synthEngine) return;
        this.synthEngine.setReverb(parseFloat(e.target.value));
      });
    }
    if (this.delaySlider) {
      this.delaySlider.addEventListener("input", (e) => {
        if (this.mode !== "synth" || !this.synthEngine) return;
        this.synthEngine.setDelay(parseFloat(e.target.value));
      });
    }
    if (this.transposeSlider) {
      this.transposeSlider.addEventListener("input", (e) => {
        this.synthEngine?.setTranspose(parseFloat(e.target.value));
      });
    }
    document.getElementById("load-loop-button").addEventListener("click", () => {
      document.getElementById("load-loop-file").click();
    });
    document.getElementById("load-loop-file").addEventListener("change", (e) => this.onLoadFile(e));
    this.loadSamplesButton.addEventListener("click", () => {
      this.loadSamplesFile.click();
    });
    this.loadSamplesFile.addEventListener("change", (e) => this.loadSynthSamples(e));

    this.patchCanvas.addEventListener("mousedown", (e) => this.onPatchPress(e));
    this.patchCanvas.addEventListener("mousemove", (e) => this.onPatchDrag(e));
    this.patchCanvas.addEventListener("mouseup", (e) => this.onPatchRelease(e));
    this.patchCanvas.addEventListener("dragover", (e) => this.onPatchDragOver(e));
    this.patchCanvas.addEventListener("drop", (e) => this.onPatchDrop(e));
  }

  async setMode(mode) {
    if (mode === this.mode) return;
    if (this.mode === "synth" && this.synthEngine) {
      for (const sourceId of this.sources.keys()) {
        this.scheduler?.removeVoice(sourceId);
        this.synthEngine.disposeVoice(sourceId);
      }
      this.synthEngine.pause();
      this.playPauseButton.textContent = "Play";
    } else if (this.mode === "loop") {
      this.worker?.postMessage({ type: "pause" });
      if (this.audioContext?.state === "running") await this.audioContext.suspend();
      this.playPauseButton.textContent = "Play";
    }
    this.mode = mode;
    if (mode === "synth") {
      await this.ensureSynthEngine();
    } else {
      await this.ensureLoopEngine();
      this.worker.postMessage({ type: "set_mode", mode });
    }

    // Mirror the engine's server-side reset: clear all client patch state.
    this.sources.clear();
    this._pendingSources = [];
    this.selectedSourceId = null;
    this.dragSourceId = null;
    this.dragPos = null;

    this.loadSamplesButton.classList.toggle("hidden", true);
    this.applyModeControls();

    this.drawPatchBay();
    this.renderSourceList();
  }

  async onTogglePlay() {
    if (this.mode === "synth") {
      await this.ensureSynthEngine();
      if (this.synthEngine.paused) {
        await this.synthEngine.resume();
        this.playPauseButton.textContent = "Pause";
      } else {
        this.synthEngine.pause();
        this.playPauseButton.textContent = "Play";
      }
      return;
    }
    await this.ensureLoopEngine();
    if (!this.loopLoaded) {
      this.statusEl.textContent = "Load a loop or switch to Synth before playing.";
      this.statusEl.classList.remove("hidden");
      return;
    }
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
      this.worker.postMessage({ type: "play", mode: this.mode });
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
    this.loopLoaded = true;
    this.statusEl.classList.add("hidden");
    this.worker.postMessage({ type: "load_loop", samples: mono }, [mono.buffer]);
  }

  async loadSynthSamples(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    let loaded = 0;
    for (const file of files) {
      const arrayBuffer = await file.arrayBuffer();
      const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
      const channels = [];
      for (let ch = 0; ch < audioBuffer.numberOfChannels; ch++) {
        channels.push(audioBuffer.getChannelData(ch));
      }
      const mono = new Float32Array(audioBuffer.length);
      for (let i = 0; i < audioBuffer.length; i++) {
        let sum = 0;
        for (let ch = 0; ch < channels.length; ch++) sum += channels[ch][i];
        mono[i] = sum / channels.length;
      }
      this.worker.postMessage(
        { type: "load_synth_sample", name: file.name, samples: mono },
        [mono.buffer]
      );
      loaded += 1;
    }
    this.statusEl.textContent = `Loaded ${loaded} local synth samples.`;
    this.statusEl.classList.remove("hidden");
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
    const color = hsvToCssColor(this.currentHsv);
    this._pendingSources.push({ hue, sat, val, bpm, color });
    if (this.mode === "synth") {
      const sourceId = this.nextSynthSourceId++;
      this.finishPendingSource(sourceId);
      return;
    }
    this.worker.postMessage({ type: "add_source", hue, sat, val, bpm });
  }

  finishPendingSource(sourceId) {
    // The worker replies to add_source requests strictly in the order it
    // received them, so the oldest queued entry always matches this reply.
    const pending = this._pendingSources.shift();
    if (!pending) return;
    this.sources.set(sourceId, {
      x: null,
      y: null,
      color: pending.color,
      bpm: pending.bpm,
      hue: pending.hue,
      sat: pending.sat,
      val: pending.val,
      slot: null,
      row: null,
      col: null,
      behavior: null,
      instrument: null,
      fingerprint: deriveFingerprint({
        hue: pending.hue,
        sat: pending.sat,
        val: pending.val,
        bpm: pending.bpm,
      }),
      macroId: null,
    });
    if (this.autoAssignSourcesEl.checked) {
      const slot = this.nextAvailableOutputSlot();
      if (slot !== null) this.assignSourceToOutput(sourceId, slot);
    }
    this.drawPatchBay();
    this.renderSourceList();
  }

  nextAvailableOutputSlot() {
    const used = new Set(Array.from(this.sources.values(), (source) => source.slot));
    for (let slot = 0; slot < PATCH_SOURCE_LIMIT; slot++) {
      if (!used.has(slot) && this.outputSlotEnabled(slot)) return slot;
    }
    return null;
  }

  outputSlotEnabled(slot) {
    if (this.mode !== "synth") return true;
    const row = Math.floor(slot / PATCH_GRID_COLS);
    const col = slot % PATCH_GRID_COLS;
    return Boolean(SYNTH_SOURCE_INSTRUMENTS[row]?.[col]);
  }

  synthSourceForSlot(slot) {
    return sourceForSlot(slot, PATCH_GRID_COLS);
  }

  cellAt(x, y) {
    const col = Math.floor((x - PATCH_GRID_X) / PATCH_CELL);
    const row = Math.floor((y - PATCH_GRID_Y) / PATCH_CELL);
    if (row < 0 || row >= PATCH_GRID_ROWS || col < 0 || col >= PATCH_GRID_COLS) return null;
    return { row, col };
  }

  outputSlotAt(x, y) {
    const col = Math.floor((x - OUTPUT_GRID_X) / PATCH_CELL);
    const row = Math.floor((y - OUTPUT_GRID_Y) / PATCH_CELL);
    if (row < 0 || row >= PATCH_GRID_ROWS || col < 0 || col >= PATCH_GRID_COLS) return null;
    return row * PATCH_GRID_COLS + col;
  }

  nearestSource(x, y) {
    for (const [sourceId, source] of this.sources) {
      if (source.x === null || source.y === null) continue;
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
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const slot = this.outputSlotAt(x, y);
    const cell = this.cellAt(x, y);
    if (this.dragSourceId === null && this.selectedSourceId !== null && slot !== null) {
      this.assignSourceToOutput(this.selectedSourceId, slot);
      this.drawPatchBay();
      this.renderSourceList();
      return;
    }
    if (this.dragSourceId === null) return;
    const source = this.sources.get(this.dragSourceId);

    if (slot !== null) {
      if (source && source.slot !== slot) {
        this.assignSourceToOutput(this.dragSourceId, slot);
      }
    } else if (cell === null) {
      if (this.mode === "synth") {
        this.scheduler?.setVoiceMacro(this.dragSourceId, null);
        source.row = null;
        source.col = null;
        source.macroId = null;
      } else {
        this.worker.postMessage({ type: "disconnect_source", sourceId: this.dragSourceId });
        source.x = null;
        source.y = null;
        source.slot = null;
        source.row = null;
        source.col = null;
      }
    } else {
      this.routeSourceToMacro(this.dragSourceId, cell);
    }
    this.dragPos = null;
    this.dragSourceId = null;
    this.drawPatchBay();
    this.renderSourceList();
  }

  onPatchDragOver(event) {
    if (!event.dataTransfer.types.includes("text/plain")) return;
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const slot = this.outputSlotAt(x, y);
    if (slot === null || !this.outputSlotEnabled(slot)) return;
    event.preventDefault();
  }

  onPatchDrop(event) {
    const sourceId = Number(event.dataTransfer.getData("text/plain"));
    if (!this.sources.has(sourceId)) return;
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const slot = this.outputSlotAt(x, y);
    if (slot === null || !this.outputSlotEnabled(slot)) return;
    event.preventDefault();
    this.assignSourceToOutput(sourceId, slot);
    this.dragSourceId = null;
    this.dragPos = null;
    this.drawPatchBay();
    this.renderSourceList();
  }

  onSourceListDragStart(event, sourceId) {
    event.dataTransfer.setData("text/plain", String(sourceId));
    event.dataTransfer.effectAllowed = "move";
    this.dragSourceId = sourceId;
  }

  onSourceListClick(sourceId) {
    this.selectedSourceId = this.selectedSourceId === sourceId ? null : sourceId;
    this.renderSourceList();
  }

  assignSourceToOutput(sourceId, slot) {
    const source = this.sources.get(sourceId);
    if (!source || !this.outputSlotEnabled(slot)) return;
    for (const [otherId, other] of this.sources) {
      if (otherId !== sourceId && other.slot === slot) {
        if (this.mode === "synth") {
          this.scheduler?.removeVoice(otherId);
          this.synthEngine?.disposeVoice(otherId);
        } else {
          this.worker.postMessage({ type: "disconnect_source", sourceId: otherId });
        }
        other.x = null;
        other.y = null;
        other.slot = null;
        other.row = null;
        other.col = null;
        other.macroId = null;
      }
    }

    const position = outputSlotPosition(slot);
    const previousMacroId =
      this.mode === "synth" && source.row !== null && source.col !== null
        ? macroPresetId(source.row, source.col)
        : source.macroId;
    source.slot = slot;
    source.x = position.x;
    source.y = position.y;
    if (source.row !== null || source.col !== null) {
      if (this.mode !== "synth") {
        this.worker.postMessage({ type: "disconnect_source", sourceId });
      }
    }
    source.row = null;
    source.col = null;
    source.macroId = null;
    if (this.mode === "synth") {
      const config = this.synthSourceForSlot(slot);
      this.scheduler?.removeVoice(sourceId);
      this.synthEngine?.disposeVoice(sourceId);
      source.behavior = config.behavior;
      source.instrument = config.instrument;
      this.synthEngine?.createVoice(sourceId, {
        instrument: config.instrument,
        behavior: config.behavior,
        fingerprint: source.fingerprint,
      });
      this.scheduler?.addVoice(sourceId, {
        behavior: config.behavior,
        fingerprint: source.fingerprint,
      });
      if (previousMacroId) {
        this.scheduler?.setVoiceMacro(sourceId, previousMacroId);
        const [, macroRow, macroCol] = previousMacroId.match(/^(.+)_(\d+)$/) ?? [];
        if (macroRow) {
          source.row = MACRO_ROWS.indexOf(macroRow);
          source.col = Number(macroCol) - 1;
          source.macroId = previousMacroId;
        }
      }
    }
    this.selectedSourceId = null;
  }

  routeSourceToMacro(sourceId, cell) {
    const source = this.sources.get(sourceId);
    if (!source || source.slot === null) return;
    const row = cell.row;
    const col = cell.col;
    if (this.mode === "synth") {
      const macroId = macroPresetId(row, col);
      this.scheduler?.setVoiceMacro(sourceId, macroId);
      source.row = row;
      source.col = col;
      source.macroId = macroId;
      return;
    }
    const engine =
      this.mode === "loop" && row === TAPE_ROW_INDEX && col === 4
        ? "reverb"
        : PATCH_ROW_ENGINES[row];
    this.worker.postMessage({
      type: "connect_source",
      sourceId,
      engine,
      row,
      col,
      outputSlot: source.slot,
    });
    source.row = row;
    source.col = col;
  }

  rowLabels() {
    return this.mode === "synth" ? SYNTH_ROW_LABELS : LOOP_ROW_LABELS;
  }

  inputColLabel(col) {
    return this.mode === "synth" ? MACRO_COLS[col] : VARIANT_COL_LABELS[col];
  }

  outputRowLabel(row) {
    return this.mode === "synth" ? (SYNTH_SOURCE_ROWS[row] ?? "") : VARIANT_COL_LABELS[row];
  }

  outputCellLabel(row, col) {
    if (this.mode !== "synth") return VARIANT_COL_LABELS[col];
    return SYNTH_SOURCE_INSTRUMENTS[row]?.[col] ?? "";
  }

  drawPatchBay() {
    const ctx = this.patchCanvas.getContext("2d");
    const rowLabels = this.rowLabels();
    ctx.fillStyle = "#161616";
    ctx.fillRect(0, 0, this.patchCanvas.width, this.patchCanvas.height);

    ctx.fillStyle = "#999";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("outputs", OUTPUT_GRID_X, OUTPUT_GRID_Y - 18);
    ctx.fillText("inputs", PATCH_GRID_X, PATCH_GRID_Y - 18);

    const outputColors = new Map();
    const outputLabels = new Map();
    for (const [sourceId, source] of this.sources) {
      if (source.slot === null) continue;
      outputColors.set(source.slot, source.color);
      outputLabels.set(source.slot, String(sourceId));
    }

    const inputColors = new Map();
    for (const [, source] of this.sources) {
      if (source.row !== null) {
        inputColors.set(`${source.row}:${source.col}`, source.color);
      }
    }

    for (let row = 0; row < PATCH_GRID_ROWS; row++) {
      ctx.fillStyle = "#888";
      ctx.font = "9px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(this.outputRowLabel(row), OUTPUT_GRID_X - 34, OUTPUT_GRID_Y + row * PATCH_CELL + 14);
      for (let col = 0; col < PATCH_GRID_COLS; col++) {
        const x0 = OUTPUT_GRID_X + col * PATCH_CELL;
        const y0 = OUTPUT_GRID_Y + row * PATCH_CELL;
        const slot = row * PATCH_GRID_COLS + col;
        const enabled = this.outputSlotEnabled(slot);
        ctx.strokeStyle = enabled ? "#444" : "#303030";
        ctx.strokeRect(x0, y0, PATCH_CELL, PATCH_CELL);
        ctx.fillStyle = outputColors.has(slot) ? "#111" : enabled ? "#888" : "#333";
        ctx.font = "9px sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(this.outputCellLabel(row, col), x0 + 6, y0 + 14);
        if (outputLabels.has(slot)) {
          ctx.fillStyle = "#111";
          ctx.font = "12px sans-serif";
          ctx.textAlign = "center";
          ctx.fillText(outputLabels.get(slot), x0 + PATCH_CELL / 2, y0 + PATCH_CELL - 10);
        }
      }
    }

    for (let row = 0; row < PATCH_GRID_ROWS; row++) {
      ctx.fillStyle = "#d5d5d5";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(rowLabels[row], PATCH_GRID_X - 12, PATCH_GRID_Y + row * PATCH_CELL + PATCH_CELL / 2);
      ctx.textAlign = "left";
      for (let col = 0; col < PATCH_GRID_COLS; col++) {
        const x0 = PATCH_GRID_X + col * PATCH_CELL;
        const y0 = PATCH_GRID_Y + row * PATCH_CELL;
        ctx.strokeStyle = "#444";
        ctx.strokeRect(x0, y0, PATCH_CELL, PATCH_CELL);
        ctx.fillStyle = "#888";
        ctx.font = "9px sans-serif";
        ctx.fillText(this.inputColLabel(col), x0 + 6, y0 + 14);
      }
    }

    for (const [, source] of this.sources) {
      if (source.row !== null) {
        const input = gridCenter(PATCH_GRID_X, PATCH_GRID_Y, source.row, source.col);
        drawCable(ctx, source.x, source.y, input.x, input.y, source.color, false);
      }
    }

    if (this.dragSourceId !== null && this.dragPos) {
      const source = this.sources.get(this.dragSourceId);
      if (source) {
        drawCable(ctx, source.x, source.y, this.dragPos.x, this.dragPos.y, source.color, true);
      }
    }

    for (let row = 0; row < PATCH_GRID_ROWS; row++) {
      for (let col = 0; col < PATCH_GRID_COLS; col++) {
        const slot = row * PATCH_GRID_COLS + col;
        const output = gridCenter(OUTPUT_GRID_X, OUTPUT_GRID_Y, row, col);
        const input = gridCenter(PATCH_GRID_X, PATCH_GRID_Y, row, col);
        const outputColor = outputColors.get(slot) || (this.outputSlotEnabled(slot) ? "#4a4a4a" : "#242424");
        drawJack(ctx, output.x, output.y, outputColor);
        drawJack(ctx, input.x, input.y, inputColors.get(`${row}:${col}`) || "#4a4a4a");
      }
    }
  }

  cellLabel(row, col) {
    if (row === null) return "unconnected";
    return `${this.rowLabels()[row]} / ${VARIANT_COL_LABELS[col]}`;
  }

  renderSourceList() {
    this.sourceListEl.innerHTML = "";
    for (const [sourceId, source] of this.sources) {
      const li = document.createElement("li");
      li.classList.toggle("selected", this.selectedSourceId === sourceId);
      li.draggable = true;
      li.addEventListener("dragstart", (event) => this.onSourceListDragStart(event, sourceId));
      li.addEventListener("click", () => this.onSourceListClick(sourceId));

      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = source.color;

      const label = document.createElement("span");
      label.className = "source-cell";
      label.textContent = this.sourceShortLabel(source);

      const removeButton = document.createElement("button");
      removeButton.className = "icon-button";
      removeButton.textContent = "\u00d7";
      removeButton.setAttribute("aria-label", "Remove source");
      removeButton.title = "Remove source";
      removeButton.addEventListener("click", (event) => {
        event.stopPropagation();
        this.onRemoveSource(sourceId);
      });

      li.append(swatch, label, removeButton);
      this.sourceListEl.appendChild(li);
    }
  }

  sourceShortLabel(source) {
    const bpm = Math.round(source.bpm);
    if (source.slot === null) return `${bpm} BPM`;
    const output =
      this.mode === "synth" && source.behavior && source.instrument
        ? `${source.behavior}/${source.instrument}`
        : `Out ${source.slot + 1}`;
    if (source.row === null) return `${bpm} - ${output}`;
    return `${bpm} - ${output} -> ${this.rowLabels()[source.row]} ${this.inputColLabel(source.col)}`;
  }

  onRemoveSource(sourceId) {
    if (this.mode === "synth") {
      this.scheduler?.removeVoice(sourceId);
      this.synthEngine?.disposeVoice(sourceId);
    } else {
      this.worker.postMessage({ type: "remove_source", sourceId });
    }
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
