#pragma once
#include <stdint.h>

#define NUM_JACKS 4

struct Color { uint8_t r, g, b; };

struct Jack {
  bool   present;
  int8_t pairedWith;   // partner index or -1
  Color  color;
  bool   hasColor;
};

enum EventType {
  EV_NONE,
  EV_STAGED,           // color stored for next new cable
  EV_RETRO_COLORED,    // staged color applied to colorless pending jack (jackA)
  EV_NEW_CABLE,        // jackA inserted, took staged color
  EV_NEW_CABLE_DARK,   // jackA inserted, nothing staged, stays dark
  EV_PAIRED,           // jackA inserted, paired with jackB, copied its color
  EV_UNPAIRED,         // jackA removed, jackB back to pending
  EV_PENDING_REMOVED   // jackA removed while pending
};

struct PatchEvent { EventType type; int8_t jackA, jackB; };

struct PatchState {
  Jack    jacks[NUM_JACKS];
  int8_t  pendingQueue[NUM_JACKS];
  uint8_t pendingCount;
  Color   staged;
  bool    hasStaged;
};

void       patchInit(PatchState& s);
PatchEvent stageColor(PatchState& s, Color c);
PatchEvent onInsert(PatchState& s, uint8_t jack);
PatchEvent onRemove(PatchState& s, uint8_t jack);
void       clearStaged(PatchState& s);
