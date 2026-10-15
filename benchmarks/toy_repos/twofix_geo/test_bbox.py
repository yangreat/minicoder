import pytest
from bbox import bbox
def test_box(): assert bbox([(1, 2), (5, -1), (3, 8)]) == (1, -1, 5, 8)
def test_empty():
    with pytest.raises(ValueError): bbox([])
