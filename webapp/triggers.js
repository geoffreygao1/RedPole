// The destination grid is a trigger/sequencer, not an effects chain: cabling
// a placed source onto a cell here assigns it a rhythmic subdivision (row)
// and a probability of firing on each step (column). All voices share ONE
// Tone.Transport clock (see scheduler.js), so different rows/columns stay
// phase-locked to each other instead of drifting.
export const TRIGGER_ROWS = ["pulse", "half-time", "bar", "long", "glacial"];
export const TRIGGER_COLS = ["rare", "sparse", "often", "frequent", "always"];

const BEATS_PER_STEP = [1, 2, 4, 8, 16]; // one entry per TRIGGER_ROWS
const PROBABILITY = [0.15, 0.35, 0.55, 0.75, 1.0]; // one entry per TRIGGER_COLS

export const TRIGGER_PRESETS = Object.fromEntries(
  TRIGGER_ROWS.flatMap((rowLabel, row) =>
    TRIGGER_COLS.map((colLabel, col) => {
      const id = `${rowLabel}_${col + 1}`;
      return [
        id,
        {
          id,
          row,
          col,
          label: `${rowLabel} / ${colLabel}`,
          beatsPerStep: BEATS_PER_STEP[row],
          probability: PROBABILITY[col],
        },
      ];
    })
  )
);

export function triggerPresetId(row, col) {
  return `${TRIGGER_ROWS[row]}_${col + 1}`;
}
