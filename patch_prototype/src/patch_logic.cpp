#include "patch_logic.h"

static void pendingPush(PatchState& s, int8_t j) {
  s.pendingQueue[s.pendingCount++] = j;
}

static int8_t pendingPopOldest(PatchState& s) {
  int8_t j = s.pendingQueue[0];
  for (uint8_t i = 1; i < s.pendingCount; i++)
    s.pendingQueue[i - 1] = s.pendingQueue[i];
  s.pendingCount--;
  return j;
}

static void pendingRemove(PatchState& s, int8_t j) {
  uint8_t w = 0;
  for (uint8_t i = 0; i < s.pendingCount; i++)
    if (s.pendingQueue[i] != j) s.pendingQueue[w++] = s.pendingQueue[i];
  s.pendingCount = w;
}

void patchInit(PatchState& s) {
  for (int i = 0; i < NUM_JACKS; i++) {
    s.jacks[i].present = false;
    s.jacks[i].pairedWith = -1;
    s.jacks[i].color = Color{0, 0, 0};
    s.jacks[i].hasColor = false;
  }
  s.pendingCount = 0;
  s.hasStaged = false;
  s.staged = Color{0, 0, 0};
}

PatchEvent stageColor(PatchState& s, Color c) {
  // A colorless pending jack (plugged before any color was staged) takes the
  // color immediately instead of it waiting for the next insertion.
  for (uint8_t i = 0; i < s.pendingCount; i++) {
    int8_t j = s.pendingQueue[i];
    if (!s.jacks[j].hasColor) {
      s.jacks[j].color = c;
      s.jacks[j].hasColor = true;
      return PatchEvent{EV_RETRO_COLORED, j, -1};
    }
  }
  s.staged = c;
  s.hasStaged = true;
  return PatchEvent{EV_STAGED, -1, -1};
}

void clearStaged(PatchState& s) { s.hasStaged = false; }

PatchEvent onInsert(PatchState& s, uint8_t jack) {
  s.jacks[jack].present = true;
  if (s.pendingCount > 0) {
    // Second end of an existing cable: pair with the oldest waiting jack and
    // copy its color. The staged color stays reserved for the next new cable.
    int8_t p = pendingPopOldest(s);
    s.jacks[jack].pairedWith = p;
    s.jacks[p].pairedWith = jack;
    s.jacks[jack].color = s.jacks[p].color;
    s.jacks[jack].hasColor = s.jacks[p].hasColor;
    return PatchEvent{EV_PAIRED, (int8_t)jack, p};
  }
  pendingPush(s, jack);
  if (s.hasStaged) {
    s.jacks[jack].color = s.staged;
    s.jacks[jack].hasColor = true;
    s.hasStaged = false;
    return PatchEvent{EV_NEW_CABLE, (int8_t)jack, -1};
  }
  return PatchEvent{EV_NEW_CABLE_DARK, (int8_t)jack, -1};
}

PatchEvent onRemove(PatchState& s, uint8_t jack) {
  s.jacks[jack].present = false;
  int8_t p = s.jacks[jack].pairedWith;
  if (p >= 0) {
    // Loose end of a cable: the still-plugged partner keeps its color and
    // becomes the pairing target for the next insertion.
    s.jacks[jack].pairedWith = -1;
    s.jacks[p].pairedWith = -1;
    pendingPush(s, p);
    return PatchEvent{EV_UNPAIRED, (int8_t)jack, p};
  }
  pendingRemove(s, jack);
  return PatchEvent{EV_PENDING_REMOVED, (int8_t)jack, -1};
}
