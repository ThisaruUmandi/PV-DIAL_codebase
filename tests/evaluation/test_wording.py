from experiments.evaluation.wording import check_banned_words


def test_clean_text_has_no_hits():
    assert check_banned_words("Phase 1 differs from Baseline A on 54% of pairs.") == []


def test_catches_banned_words():
    assert check_banned_words("This is the best approach and we recommend it.")


def test_error_is_banned_but_error_classes_are_allowed():
    assert check_banned_words("an error occurred")
    assert check_banned_words("AdapterError was raised") == []
