// Runs in a background Web Worker: loads Pyodide, fetches the shared
// Python DSP files straight from audio_prototype/ (same files the
// desktop app and pytest use -- no copy, no build step), and paces
// audio generation ahead of real time, handing finished blocks directly
// to the AudioWorklet over a MessageChannel so the main thread is never
// on the audio path.

const PYODIDE_VERSION = "v0.26.4";
const PYTHON_FILES = [
  "modulation.py",
  "layers.py",
  "tape_modulator.py",
  "microcosm_processor.py",
  "reverb.py",
  "wet_bus.py",
  "crowd.py",
  "web_engine.py",
];
const BLOCK_FRAMES = 4096;
const HIGH_WATERMARK_SECONDS = 0.3;
const GENERATE_INTERVAL_MS = 40;

let pyodide = null;
let sampleRate = 44100;
let audioPort = null;
let paused = true;
let bufferedAheadFrames = 0;

async function fetchPythonSource(name) {
  // ../audio_prototype/<name>.py resolves correctly both in local dev
  // (serving the whole repo root) and once deployed (Task 6 publishes
  // audio_prototype/ as a sibling of webapp/, matching this relative path).
  const response = await fetch(`../audio_prototype/${name}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${name}: ${response.status}`);
  }
  return response.text();
}

async function initPyodide() {
  importScripts(
    `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/pyodide.js`
  );
  pyodide = await loadPyodide();
  await pyodide.loadPackage("numpy");

  for (const name of PYTHON_FILES) {
    const source = await fetchPythonSource(name);
    pyodide.FS.writeFile(name, source);
  }

  pyodide.runPython(
    `import web_engine\nengine = web_engine.WebEngine(samplerate=${sampleRate})`
  );
}

function generateOneBlock() {
  const pyBlock = pyodide.runPython(`engine.generate_block(${BLOCK_FRAMES})`);
  const buffer = pyBlock.getBuffer("f32");
  const samples = Float32Array.from(buffer.data);
  buffer.release();
  pyBlock.destroy();
  return samples;
}

function pump() {
  if (paused || !pyodide || !audioPort) return;
  const highWatermarkFrames = HIGH_WATERMARK_SECONDS * sampleRate;
  while (bufferedAheadFrames < highWatermarkFrames) {
    let samples;
    try {
      samples = generateOneBlock();
    } catch (err) {
      self.postMessage({ type: "error", message: String(err) });
      paused = true;
      return;
    }
    audioPort.postMessage({ type: "block", samples }, [samples.buffer]);
    bufferedAheadFrames += BLOCK_FRAMES;
  }
}

self.onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.type === "init") {
      sampleRate = msg.sampleRate;
      audioPort = msg.audioPort;
      await initPyodide();
      setInterval(pump, GENERATE_INTERVAL_MS);
      // Approximate playback draining the buffer: real consumption is
      // tracked by the worklet's own status reports (read by main.js for
      // the debug readout), but pump() only needs a rough estimate to
      // avoid generating unboundedly far ahead.
      setInterval(() => {
        if (paused) return;
        bufferedAheadFrames = Math.max(
          0,
          bufferedAheadFrames - (sampleRate * GENERATE_INTERVAL_MS) / 1000
        );
      }, GENERATE_INTERVAL_MS);
      self.postMessage({ type: "ready" });
    } else if (msg.type === "load_loop") {
      pyodide.globals.set("_samples", msg.samples);
      pyodide.runPython("engine.load_loop(_samples)");
      bufferedAheadFrames = 0;
      if (audioPort) audioPort.postMessage({ type: "flush" });
    } else if (msg.type === "add_source") {
      const sourceId = pyodide.runPython(
        `engine.registry.add_source(hue=${msg.hue}, sat=${msg.sat}, val=${msg.val}, bpm=${msg.bpm})`
      );
      self.postMessage({ type: "source_added", sourceId });
    } else if (msg.type === "connect_source") {
      pyodide.runPython(
        `engine.registry.connect_source(${msg.sourceId}, engine=${JSON.stringify(
          msg.engine
        )}, row=${msg.row}, col=${msg.col})`
      );
    } else if (msg.type === "disconnect_source") {
      pyodide.runPython(`engine.registry.disconnect_source(${msg.sourceId})`);
    } else if (msg.type === "remove_source") {
      pyodide.runPython(`engine.registry.remove_source(${msg.sourceId})`);
    } else if (msg.type === "set_wet_dry") {
      pyodide.runPython(`engine.wet_dry = ${msg.value}`);
    } else if (msg.type === "play") {
      paused = false;
      bufferedAheadFrames = 0;
      if (audioPort) audioPort.postMessage({ type: "flush" });
    } else if (msg.type === "pause") {
      paused = true;
    }
  } catch (err) {
    self.postMessage({ type: "error", message: String(err) });
  }
};
