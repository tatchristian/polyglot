import pytest
from relay import LRUMessageMap

def test_lru_put_and_get():
    lru = LRUMessageMap(maxsize=3)
    lru.put(101, [(201, 301)])
    lru.put(102, [(202, 302)])

    assert len(lru) == 2
    assert lru.get(101) == [(201, 301)]
    assert lru.get(102) == [(202, 302)]
    assert lru.get(999) is None

def test_lru_eviction():
    lru = LRUMessageMap(maxsize=2)
    lru.put(1, [(10, 100)])
    lru.put(2, [(20, 200)])
    lru.put(3, [(30, 300)])  # Should evict key 1

    assert len(lru) == 2
    assert lru.get(1) is None
    assert lru.get(2) == [(20, 200)]
    assert lru.get(3) == [(30, 300)]

def test_lru_recency_update():
    lru = LRUMessageMap(maxsize=2)
    lru.put(1, [(10, 100)])
    lru.put(2, [(20, 200)])

    # Access key 1 to make it most recently used
    _ = lru.get(1)

    # Adding key 3 should now evict key 2 (least recently used)
    lru.put(3, [(30, 300)])

    assert lru.get(2) is None
    assert lru.get(1) == [(10, 100)]
    assert lru.get(3) == [(30, 300)]

def test_lru_remove():
    lru = LRUMessageMap(maxsize=5)
    lru.put(42, [(1, 2)])

    removed = lru.remove(42)
    assert removed == [(1, 2)]
    assert lru.get(42) is None
    assert lru.remove(42) is None
