from scripts.check_api_parity import audit


def test_every_public_header_method_has_a_final_parity_state() -> None:
    assert audit() == []
