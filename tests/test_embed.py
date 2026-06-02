# tests/test_embed.py
import math
from ari_os.tools import embed

def test_cosine_identical_is_one():
    assert abs(embed.cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9

def test_cosine_orthogonal_is_zero():
    assert abs(embed.cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9

def test_cosine_zero_vector_is_zero():
    assert embed.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
