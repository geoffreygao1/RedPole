#include <unity.h>
#include "patch_logic.h"

static PatchState s;
void setUp() { patchInit(s); }
void tearDown() {}

static Color RED()  { Color c{255, 0, 0}; return c; }
static Color BLUE() { Color c{0, 0, 255}; return c; }

void test_init_state() {
  TEST_ASSERT_EQUAL(0, s.pendingCount);
  TEST_ASSERT_FALSE(s.hasStaged);
  for (int i = 0; i < NUM_JACKS; i++) {
    TEST_ASSERT_FALSE(s.jacks[i].present);
    TEST_ASSERT_EQUAL(-1, s.jacks[i].pairedWith);
    TEST_ASSERT_FALSE(s.jacks[i].hasColor);
  }
}

void test_stage_then_insert_lights_new_cable() {
  stageColor(s, RED());
  PatchEvent e = onInsert(s, 0);
  TEST_ASSERT_EQUAL(EV_NEW_CABLE, e.type);
  TEST_ASSERT_EQUAL(0, e.jackA);
  TEST_ASSERT_TRUE(s.jacks[0].hasColor);
  TEST_ASSERT_EQUAL(255, s.jacks[0].color.r);
  TEST_ASSERT_FALSE(s.hasStaged);          // consumed
  TEST_ASSERT_EQUAL(1, s.pendingCount);
}

void test_insert_without_staged_stays_dark_but_pending() {
  PatchEvent e = onInsert(s, 0);
  TEST_ASSERT_EQUAL(EV_NEW_CABLE_DARK, e.type);
  TEST_ASSERT_FALSE(s.jacks[0].hasColor);
  TEST_ASSERT_EQUAL(1, s.pendingCount);
}

void test_retroactive_color_on_colorless_pending() {
  onInsert(s, 0);                          // dark pending
  PatchEvent e = stageColor(s, RED());
  TEST_ASSERT_EQUAL(EV_RETRO_COLORED, e.type);
  TEST_ASSERT_EQUAL(0, e.jackA);
  TEST_ASSERT_TRUE(s.jacks[0].hasColor);
  TEST_ASSERT_FALSE(s.hasStaged);          // consumed by retro-apply
}

void test_second_insert_pairs_and_copies_color() {
  stageColor(s, RED());
  onInsert(s, 0);
  PatchEvent e = onInsert(s, 2);
  TEST_ASSERT_EQUAL(EV_PAIRED, e.type);
  TEST_ASSERT_EQUAL(2, e.jackA);
  TEST_ASSERT_EQUAL(0, e.jackB);
  TEST_ASSERT_EQUAL(0, s.jacks[2].pairedWith);
  TEST_ASSERT_EQUAL(255, s.jacks[2].color.r);
  TEST_ASSERT_EQUAL(0, s.pendingCount);
}

void test_pairing_does_not_consume_staged() {
  stageColor(s, RED());
  onInsert(s, 0);                          // consumes red
  onInsert(s, 2);                          // pairs
  stageColor(s, BLUE());                   // staged for next cable
  PatchEvent e = onInsert(s, 1);
  TEST_ASSERT_EQUAL(EV_NEW_CABLE, e.type);
  TEST_ASSERT_EQUAL(255, s.jacks[1].color.b);
}

void test_unplug_one_end_keeps_other_glowing_pending() {
  stageColor(s, RED());
  onInsert(s, 0);
  onInsert(s, 2);
  PatchEvent e = onRemove(s, 2);
  TEST_ASSERT_EQUAL(EV_UNPAIRED, e.type);
  TEST_ASSERT_EQUAL(2, e.jackA);
  TEST_ASSERT_EQUAL(0, e.jackB);
  TEST_ASSERT_EQUAL(-1, s.jacks[0].pairedWith);
  TEST_ASSERT_TRUE(s.jacks[0].hasColor);   // still glowing
  TEST_ASSERT_EQUAL(1, s.pendingCount);    // 0 pending again
}

void test_replug_loose_end_elsewhere_copies_cable_color() {
  stageColor(s, RED());
  onInsert(s, 0);
  onInsert(s, 2);
  onRemove(s, 2);
  PatchEvent e = onInsert(s, 1);           // ID3 -> ID2 move
  TEST_ASSERT_EQUAL(EV_PAIRED, e.type);
  TEST_ASSERT_EQUAL(1, e.jackA);
  TEST_ASSERT_EQUAL(0, e.jackB);
  TEST_ASSERT_EQUAL(255, s.jacks[1].color.r);
}

void test_remove_pending_jack_drops_from_queue() {
  stageColor(s, RED());
  onInsert(s, 0);
  PatchEvent e = onRemove(s, 0);
  TEST_ASSERT_EQUAL(EV_PENDING_REMOVED, e.type);
  TEST_ASSERT_EQUAL(0, s.pendingCount);
  TEST_ASSERT_TRUE(s.jacks[0].hasColor);   // color remembered
}

void test_fifo_pairs_oldest_pending_first() {
  stageColor(s, RED());
  onInsert(s, 0);                          // pending: [0]
  onInsert(s, 1);                          // pairs with 0 -> queue empty
  stageColor(s, BLUE());
  onInsert(s, 2);                          // new cable, pending: [2]
  PatchEvent e = onInsert(s, 3);
  TEST_ASSERT_EQUAL(EV_PAIRED, e.type);
  TEST_ASSERT_EQUAL(2, e.jackB);
}

void test_clear_staged() {
  stageColor(s, RED());
  clearStaged(s);
  PatchEvent e = onInsert(s, 0);
  TEST_ASSERT_EQUAL(EV_NEW_CABLE_DARK, e.type);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_init_state);
  RUN_TEST(test_stage_then_insert_lights_new_cable);
  RUN_TEST(test_insert_without_staged_stays_dark_but_pending);
  RUN_TEST(test_retroactive_color_on_colorless_pending);
  RUN_TEST(test_second_insert_pairs_and_copies_color);
  RUN_TEST(test_pairing_does_not_consume_staged);
  RUN_TEST(test_unplug_one_end_keeps_other_glowing_pending);
  RUN_TEST(test_replug_loose_end_elsewhere_copies_cable_color);
  RUN_TEST(test_remove_pending_jack_drops_from_queue);
  RUN_TEST(test_fifo_pairs_oldest_pending_first);
  RUN_TEST(test_clear_staged);
  return UNITY_END();
}
