from distance import manhattan
def test_pos(): assert manhattan((0, 0), (3, 4)) == 7
def test_neg(): assert manhattan((3, 4), (0, 0)) == 7
def test_mixed(): assert manhattan((1, 5), (4, 1)) == 7
