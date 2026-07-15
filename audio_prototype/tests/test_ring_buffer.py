import numpy as np

from ring_buffer import RingBuffer


def test_initial_read_is_zeros():
    rb = RingBuffer(capacity=10)
    np.testing.assert_array_equal(rb.read_latest(10), np.zeros(10, dtype=np.float32))


def test_write_smaller_than_capacity_is_right_aligned():
    rb = RingBuffer(capacity=10)
    rb.write(np.array([1, 2, 3], dtype=np.float32))
    expected = np.array([0, 0, 0, 0, 0, 0, 0, 1, 2, 3], dtype=np.float32)
    np.testing.assert_array_equal(rb.read_latest(10), expected)


def test_write_larger_than_capacity_keeps_last_capacity_samples():
    rb = RingBuffer(capacity=5)
    rb.write(np.arange(20, dtype=np.float32))
    np.testing.assert_array_equal(rb.read_latest(5), np.array([15, 16, 17, 18, 19], dtype=np.float32))


def test_multiple_writes_roll_forward():
    rb = RingBuffer(capacity=5)
    rb.write(np.array([1, 2, 3], dtype=np.float32))
    rb.write(np.array([4, 5, 6], dtype=np.float32))
    np.testing.assert_array_equal(rb.read_latest(5), np.array([2, 3, 4, 5, 6], dtype=np.float32))


def test_read_latest_fewer_than_capacity():
    rb = RingBuffer(capacity=5)
    rb.write(np.array([1, 2, 3, 4, 5], dtype=np.float32))
    np.testing.assert_array_equal(rb.read_latest(2), np.array([4, 5], dtype=np.float32))
