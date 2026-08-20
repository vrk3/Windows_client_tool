from PyQt6.QtCore import QThreadPool

from core import long_op_pool


def test_get_long_op_pool_is_bounded():
    pool = long_op_pool.get_long_op_pool()
    assert isinstance(pool, QThreadPool)
    assert pool.maxThreadCount() == long_op_pool.MAX_THREADS


def test_get_long_op_pool_is_a_singleton():
    assert long_op_pool.get_long_op_pool() is long_op_pool.get_long_op_pool()


def test_get_long_op_pool_is_not_the_global_pool():
    assert long_op_pool.get_long_op_pool() is not QThreadPool.globalInstance()
