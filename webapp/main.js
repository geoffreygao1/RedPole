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

// Finger-scan gamut, matching the desktop app's picker (modulation.py's
// FINGER_HUE_MIN/MAX etc.): a bright red-to-orange range.
const FINGER_HUE_MIN = 0.0;
const FINGER_HUE_MAX = 0.085;
const FINGER_SAT_MIN = 0.64;
const FINGER_SAT_MAX = 0.72;
const FINGER_VAL_MIN = 0.9;
const FINGER_VAL_MAX = 0.98;

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

class App {
  constructor() {
    this.worker = new Worker("worker.js");
    this.sources = new Map(); // sourceId -> {x, y, color, row, col}
    this.dragSourceId = null;
    this.currentHsv = { hue: 0.03, sat: 0.68, val: 0.94 };

    this.statusEl = document.getElementById("status");
    this.appEl = document.getElementById("app");
    this.pickerCanvas = document.getElementById("picker");
    this.patchCanvas = document.getElementById("patch-canvas");
    this.bpmInput = document.getElementById("bpm-input");
    this.bufferReadout = document.getElementById("buffer-readout");
    this.underrunReadout = document.getElementById("underrun-readout");
    this.playPauseButton = document.getElementById("play-pause-button");

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

  bindControls() {
    document.getElementById("send-button").addEventListener("click", () => this.onSend());
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
    if (this.sources.size >= PATCH_SOURCE_LIMIT) {
      alert(`Maximum patch outputs reached (${PATCH_SOURCE_LIMIT}).`);
      return;
    }
    const bpm = parseFloat(this.bpmInput.value);
    const { hue, sat, val } = this.currentHsv;
    const [r, g, b] = hsvToRgb(hue, sat, val);
    const color = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
    this._pendingSource = { hue, sat, val, bpm, color };
    this.worker.postMessage({ type: "add_source", hue, sat, val, bpm });
  }

  finishPendingSource(sourceId) {
    const pending = this._pendingSource;
    this._pendingSource = null;
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
  }

  onPatchDrag(_event) {
    if (this.dragSourceId === null) return;
    // Cable preview omitted for MVP simplicity; the grid + jacks alone
    // are enough to show connection state once released.
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
      const engine = ROW_LABELS[cell.row];
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
    this.dragSourceId = null;
    this.drawPatchBay();
  }

  drawPatchBay() {
    const ctx = this.patchCanvas.getContext("2d");
    ctx.fillStyle = "#161616";
    ctx.fillRect(0, 0, this.patchCanvas.width, this.patchCanvas.height);

    for (let row = 0; row < PATCH_GRID_ROWS; row++) {
      const labels = row === 0 ? TAPE_COL_LABELS : GRANULES_COL_LABELS;
      ctx.fillStyle = "#d5d5d5";
      ctx.font = "12px sans-serif";
      ctx.fillText(ROW_LABELS[row], PATCH_GRID_X - 50, PATCH_GRID_Y + row * PATCH_CELL + PATCH_CELL / 2);
      for (let col = 0; col < PATCH_GRID_COLS; col++) {
        const x0 = PATCH_GRID_X + col * PATCH_CELL;
        const y0 = PATCH_GRID_Y + row * PATCH_CELL;
        ctx.strokeStyle = "#555";
        ctx.fillStyle = "#222";
        ctx.fillRect(x0, y0, PATCH_CELL, PATCH_CELL);
        ctx.strokeRect(x0, y0, PATCH_CELL, PATCH_CELL);
        ctx.fillStyle = "#888";
        ctx.font = "9px sans-serif";
        ctx.fillText(labels[col], x0 + 6, y0 + 14);
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
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(cx, cy);
        ctx.strokeStyle = source.color;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.lineWidth = 1;
      }
    }
  }
}

window.addEventListener("load", () => new App());
