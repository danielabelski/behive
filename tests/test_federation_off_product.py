"""Federation contribute/confirm are off the product."""
from behive.federation import _OFF_PRODUCT


def test_off_product_payload():
    assert _OFF_PRODUCT["ok"] is False
    assert _OFF_PRODUCT["product"] is False
    assert _OFF_PRODUCT["mode"] == "local_seed"
    assert _OFF_PRODUCT["remote_peers"] == 0
