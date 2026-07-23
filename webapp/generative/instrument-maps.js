// Clickbath multisample note maps (MIDI note -> local wav under audio/clickbath/).
// Tone.Sampler wants note-name keys; we expose both the MIDI list and the
// note-name->file map it needs.
export const INSTRUMENT_MIDIS = {
  piano: [48, 60, 72, 84],
  guitar: [48, 60, 72],
  tapeguitar: [36, 48, 60],
  tapebell: [48, 60, 72, 84],
  casio: [48, 60, 72, 84],
  strings: [48, 60, 72, 84],
  flute: [60, 72, 84],
  clarinet: [60, 72, 84],
};

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export function midiToNoteName(midi) {
  return `${NOTE_NAMES[midi % 12]}${Math.floor(midi / 12) - 1}`;
}

// instrument -> { "C4": "piano_60.wav", ... } for Tone.Sampler({ urls, baseUrl }).
export const INSTRUMENT_NOTE_URLS = Object.fromEntries(
  Object.entries(INSTRUMENT_MIDIS).map(([inst, midis]) => [
    inst,
    Object.fromEntries(midis.map((m) => [midiToNoteName(m), `${inst}_${m}.wav`])),
  ])
);
export const CLICKBATH_BASE_URL = "audio/clickbath/";
