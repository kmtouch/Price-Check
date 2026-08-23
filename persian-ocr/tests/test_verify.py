import pytest

from persian_ocr.engines.base import Block
from persian_ocr.verify import (
    Correction,
    apply_corrections,
    apply_missing_text,
    check_structure,
    confidence_score,
    parse_corrections,
)


def block(text: str, kind: str = "paragraph") -> Block:
    return Block(kind, text)


def test_unbalanced_guillemets_are_reported():
    problems = check_structure([block("او گفت «سلام و رفت")])
    assert any("guillemets" in problem for problem in problems)


def test_application_chrome_is_reported():
    problems = check_structure([block("متن فارسی Edit PDF ادامه")])
    assert any("chrome" in problem for problem in problems)


def test_mixed_digit_families_are_reported():
    problems = check_structure([block("صفحه ۱۲ و صفحه 13")])
    assert any("digit" in problem for problem in problems)


def test_repeated_word_is_reported():
    problems = check_structure([block("این کتاب کتاب خوبی است")])
    assert any("twice" in problem for problem in problems)


def test_out_of_order_footnote_markers_are_reported():
    problems = check_structure([block("متن(۳) و متن(۲)")])
    assert any("footnote" in problem for problem in problems)


def test_clean_text_produces_no_structural_problems():
    assert check_structure([block("او گفت «سلام» و رفت(۱) و بازگشت(۲).")]) == []


def test_a_confident_small_fix_is_applied():
    blocks = [block("این کتاٮ خوب است")]
    updated, processed = apply_corrections(
        blocks, [Correction(0, "کتاٮ", "کتاب", "missing dot", 0.95)]
    )
    assert updated[0].text == "این کتاب خوب است"
    assert processed[0].applied


def test_a_low_confidence_fix_is_refused():
    blocks = [block("این کتاٮ خوب است")]
    _, processed = apply_corrections(
        blocks, [Correction(0, "کتاٮ", "کتاب", "guess", 0.4)], min_confidence=0.75
    )
    assert not processed[0].applied
    assert "confidence" in processed[0].rejected_because


def test_a_rewrite_is_refused():
    original = "نیچه همیشه بسیار فشرده می‌نویسد"
    blocks = [block(original)]
    _, processed = apply_corrections(
        blocks,
        [Correction(0, original, "نیچه معمولاً خیلی خلاصه و روان می‌نوشت و بس", "style", 0.99)],
    )
    assert not processed[0].applied
    assert processed[0].rejected_because


def test_a_span_that_is_not_in_the_text_is_refused():
    _, processed = apply_corrections(
        [block("متن فارسی")], [Correction(0, "چیز دیگری", "متن", "", 0.99)]
    )
    assert "does not appear" in processed[0].rejected_because


def test_a_bad_block_index_is_refused():
    _, processed = apply_corrections([block("متن")], [Correction(7, "متن", "متنی", "", 0.99)])
    assert "does not exist" in processed[0].rejected_because


def test_overlay_text_may_be_deleted():
    blocks = [block("متن فارسی Edit PDF ادامه")]
    updated, processed = apply_corrections(
        blocks, [Correction(0, " Edit PDF", "", "overlay", 0.95)]
    )
    assert processed[0].applied
    assert "Edit PDF" not in updated[0].text


def test_a_large_deletion_is_refused():
    long_text = "این " * 60
    _, processed = apply_corrections([block(long_text)], [Correction(0, long_text.strip(), "", "overlay", 0.99)])
    assert not processed[0].applied


def test_deleting_persian_text_needs_the_overlay_reason():
    _, processed = apply_corrections(
        [block("این جمله باید بماند")], [Correction(0, "باید بماند", "", "noise", 0.99)]
    )
    assert not processed[0].applied


def test_missing_text_is_inserted_once():
    blocks = [block("بند نخست"), block("بند سوم")]
    payload = {"missing_text": [{"after_block_index": 0, "text": "بند دوم", "confidence": 0.9}]}
    updated, notes = apply_missing_text(blocks, payload, 0.75)
    assert [b.text for b in updated] == ["بند نخست", "بند دوم", "بند سوم"]
    assert notes

    updated, notes = apply_missing_text(updated, payload, 0.75)
    assert len(updated) == 3 and not notes


def test_parse_corrections_survives_malformed_payloads():
    payload = {"corrections": [{"block_index": "x"}, {"block_index": 0, "original": "a",
                                                      "corrected": "b", "reason": "r", "confidence": 0.9}]}
    assert len(parse_corrections(payload)) == 1


@pytest.mark.parametrize(
    "agreement,coverage,expected_order",
    [(1.0, 1.0, "high"), (0.8, 0.8, "low")],
)
def test_confidence_tracks_agreement_and_coverage(agreement, coverage, expected_order):
    score = confidence_score(
        agreement=agreement, lexicon_coverage=coverage, structural_problems=0,
        unresolved_flags=0, words=200,
    )
    assert (score > 0.95) == (expected_order == "high")


def test_confidence_is_penalised_by_structural_problems():
    kwargs = dict(agreement=1.0, lexicon_coverage=1.0, unresolved_flags=0, words=200)
    assert confidence_score(structural_problems=0, **kwargs) > confidence_score(
        structural_problems=3, **kwargs
    )


def test_a_fluency_rewrite_is_refused_even_when_the_words_look_alike():
    # Persian synonyms share their stems, so character similarity alone lets
    # this through; counting whole changed words is what catches it.
    original = "این گونه واژه‌ها و عبارت‌ها و جمله‌ها"
    _, processed = apply_corrections(
        [block(original)],
        [Correction(0, original, "این‌گونه واژگان و عبارات و جملات", "reads more fluently", 0.99)],
    )
    assert not processed[0].applied
    assert "rewrite" in processed[0].rejected_because


def test_a_two_word_reading_fix_is_still_allowed():
    blocks = [block("در طولِ هزاره‌ها به آن‌ها باور داشته‌اند")]
    updated, processed = apply_corrections(
        blocks, [Correction(0, "هزاره‌ها به", "هزاره‌ها یه", "the page shows a dotless beh", 0.9)]
    )
    assert processed[0].applied


def test_an_encoding_only_fix_is_allowed_at_any_size():
    original = "كتاب ايشان در سال ٢٠٢٥ چاپ شد"
    corrected = "کتاب ایشان در سال ۲۰۲۵ چاپ شد"
    _, processed = apply_corrections([block(original)], [Correction(0, original, corrected, "", 0.9)])
    assert processed[0].applied


def test_changed_words_counts_whole_words():
    from persian_ocr.verify import changed_words

    assert changed_words("این کتاب است", "این کتاٮ است") == 1
    assert changed_words("واژه‌ها و عبارت‌ها و جمله‌ها", "واژگان و عبارات و جملات") == 3


def test_a_correction_repeated_in_a_later_round_is_dropped_quietly():
    blocks = [block("این کتاب خوب است")]
    _, processed = apply_corrections(
        blocks,
        [Correction(0, "کتاٮ", "کتاب", "dots", 0.96)],
        already_applied=[("کتاٮ", "کتاب")],
    )
    assert processed == []
