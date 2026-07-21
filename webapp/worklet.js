// Runs on the browser's real-time audio-rendering thread. Deliberately
// tiny and dependency-free -- Pyodide cannot run here. It just buffers
// Float32Array blocks handed to it (over a dedicated MessageChannel from
// the Worker, linked in via `this.port`) and copies them into each
// render quantum. An empty queue means the Worker fell behind; we output
// silence for that quantum rather than glitching or crashing.

class RingWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._queue = [];
    this._queueOffset = 0;
    this._underruns = 0;
    this._lastReportTime = 0;
    this._audioPort = null;

    this.port.onmessage = (event) => {
      const data = event.data;
      if (data && data.type === "link" && data.port) {
        this._audioPort = data.port;
        this._audioPort.onmessage = (blockEvent) => {
          if (blockEvent.data && blockEvent.data.type === "block") {
            this._queue.push(blockEvent.data.samples);
          }
        };
      }
    };
  }

  _bufferedFrames() {
    let total = -this._queueOffset;
    for (let i = 0; i < this._queue.length; i++) {
      total += this._queue[i].length;
    }
    return Math.max(0, total);
  }

  process(_inputs, outputs) {
    const output = outputs[0];
    const frames = output[0].length;
    let written = 0;

    while (written < frames) {
      if (this._queue.length === 0) {
        this._underruns += 1;
        break;
      }
      const current = this._queue[0];
      const available = current.length - this._queueOffset;
      const need = frames - written;
      const take = Math.min(available, need);
      for (let ch = 0; ch < output.length; ch++) {
        output[ch].set(
          current.subarray(this._queueOffset, this._queueOffset + take),
          written
        );
      }
      this._queueOffset += take;
      written += take;
      if (this._queueOffset >= current.length) {
        this._queue.shift();
        this._queueOffset = 0;
      }
    }

    if (written < frames) {
      for (let ch = 0; ch < output.length; ch++) {
        output[ch].fill(0, written);
      }
    }

    if (currentTime - this._lastReportTime > 1.0) {
      this._lastReportTime = currentTime;
      this.port.postMessage({
        type: "status",
        bufferedFrames: this._bufferedFrames(),
        underruns: this._underruns,
      });
    }

    return true;
  }
}

registerProcessor("ring-worklet-processor", RingWorkletProcessor);
