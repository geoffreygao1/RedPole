// Runs in a background Web Worker: loads Pyodide, fetches the shared
// Runs in a background Web Worker: loads Pyodide, fetches the Python DSP
// files, and paces audio generation ahead of real time. GitHub Pages serves
// the deployable copies from webapp/audio/; local repo-root dev can fall back
// to ../audio_prototype/.

const PYODIDE_VERSION = "v0.26.4";
const PYTHON_FILES = [
  "modulation.py",
  "layers.py",
  "tape_modulator.py",
  "microcosm_processor.py",
  "reverb.py",
  "wet_bus.py",
  "crowd.py",
  "spectral_stretch.py",
  "synth_source.py",
  "synth_bath_processor.py",
  "web_engine.py",
];
const BLOCK_FRAMES = 8192;
const HIGH_WATERMARK_SECONDS = 0.75;
const GENERATE_INTERVAL_MS = 40;
const PYTHON_SOURCE_VERSION = Date.now().toString();

let pyodide = null;
let sampleRate = 44100;
let audioPort = null;
let paused = true;
let bufferedAheadFrames = 0;

async function fetchPythonSource(name) {
  const urls = [
    `audio/${name}?v=${PYTHON_SOURCE_VERSION}`,
    `../audio_prototype/${name}?v=${PYTHON_SOURCE_VERSION}`,
  ];
  let lastStatus = "not requested";
  for (const url of urls) {
    const response = await fetch(url, { cache: "no-store" });
    lastStatus = `${response.status} from ${url}`;
    if (response.ok) return response.text();
  }
  throw new Error(`Failed to fetch ${name}: ${lastStatus}`);
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
    } else if (msg.type === "load_synth_sample") {
      pyodide.globals.set("_samples", msg.samples);
      pyodide.runPython(
        `engine.load_synth_sample(${JSON.stringify(msg.name)}, _samples)`
      );
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
        )}, row=${msg.row}, col=${msg.col}, output_slot=${msg.outputSlot})`
      );
    } else if (msg.type === "disconnect_source") {
      pyodide.runPython(`engine.registry.disconnect_source(${msg.sourceId})`);
    } else if (msg.type === "remove_source") {
      pyodide.runPython(`engine.registry.remove_source(${msg.sourceId})`);
    } else if (msg.type === "set_mode") {
      pyodide.runPython(`engine.set_mode(${JSON.stringify(msg.mode)})`);
      bufferedAheadFrames = 0;
      if (audioPort) audioPort.postMessage({ type: "flush" });
    } else if (msg.type === "set_synth_options") {
      pyodide.runPython(
        `engine.set_synth_options(tone_mode=${JSON.stringify(
          msg.toneMode
        )}, harmony_mode=${JSON.stringify(msg.harmonyMode)})`
      );
      bufferedAheadFrames = 0;
      if (audioPort) audioPort.postMessage({ type: "flush" });
    } else if (msg.type === "set_wet_dry") {
      pyodide.runPython(`engine.wet_dry = ${msg.value}`);
    } else if (msg.type === "play") {
      if (msg.mode === "loop" || msg.mode === "synth") {
        pyodide.runPython(`engine.ensure_mode(${JSON.stringify(msg.mode)})`);
      }
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
