export const SOURCE_ROWS = ["pluck", "pad", "bloom", "bell", "drone"];
export const MACRO_ROWS = ["veil", "shimmer", "flutter", "scatter", "space"];
export const MACRO_COLS = ["I", "II", "III", "IV", "V"];

export const SOURCE_GRID = [
  ["piano", "guitar", "tapeguitar", "tapebell", "casio"],
  ["strings", "flute", "clarinet", "casio", "piano"],
  ["strings", "flute", "clarinet", "tapebell", "guitar"],
  ["tapebell", "casio", "piano", "guitar", "flute"],
  ["strings", "casio", "flute", "clarinet", "tapeguitar"],
];

export function sourceForSlot(slot, cols = 5) {
  const row = Math.floor(slot / cols);
  const col = slot % cols;
  return sourceForCell(row, col);
}

export function sourceForCell(row, col) {
  const behavior = SOURCE_ROWS[row];
  const instrument = SOURCE_GRID[row]?.[col];
  if (!behavior || !instrument) return null;
  return { behavior, instrument, row, col };
}

export function macroPresetId(row, col) {
  const macro = MACRO_ROWS[row];
  if (!macro || col < 0 || col >= MACRO_COLS.length) return null;
  return `${macro}_${col + 1}`;
}

export function macroLabel(row, col) {
  const macro = MACRO_ROWS[row];
  const variant = MACRO_COLS[col];
  return macro && variant ? `${macro} ${variant}` : "";
}
