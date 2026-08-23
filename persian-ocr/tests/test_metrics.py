from persian_ocr.metrics import compare, diff_words, levenshtein


def test_levenshtein_basics():
    assert levenshtein("کتاب", "کتاب") == 0
    assert levenshtein("کتاب", "کتاٮ") == 1
    assert levenshtein("", "abc") == 3


def test_identical_text_scores_perfectly():
    accuracy = compare("سلام دنیا", "سلام دنیا")
    assert accuracy.cer == 0.0 and accuracy.wer == 0.0


def test_folding_forgives_encoding_choices():
    accuracy = compare("می‌کنم كتاب ۱۲", "میکنم کتاب 12")
    assert accuracy.character_accuracy == 1.0


def test_strict_mode_does_not_forgive_them():
    accuracy = compare("می‌کنم", "میکنم", fold=False)
    assert accuracy.cer > 0


def test_a_single_wrong_letter_shows_up_in_the_rates():
    accuracy = compare("این کتاٮ است", "این کتاب است")
    assert 0 < accuracy.cer < 0.2
    assert 0 < accuracy.wer <= 0.34


def test_word_diff_points_at_the_difference():
    differences = diff_words("این کتاٮ است", "این کتاب است")
    assert differences and "کتاٮ" in differences[0]
