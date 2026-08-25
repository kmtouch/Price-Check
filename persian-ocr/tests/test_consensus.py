from persian_ocr.consensus import reconcile, vote_tokens
from persian_ocr.engines.base import Block, PageReading


def reading(*texts: str) -> PageReading:
    return PageReading(blocks=[Block("paragraph", text) for text in texts])


def test_a_single_pass_is_passed_through():
    result = reconcile([reading("سلام دنیا")])
    assert result.text == "سلام دنیا"
    assert result.agreement == 1.0


def test_identical_passes_agree_completely():
    result = reconcile([reading("سلام دنیا"), reading("سلام دنیا")])
    assert result.agreement == 1.0
    assert not result.disagreements


def test_the_majority_wins_with_three_passes():
    merged, _ = vote_tokens(
        [["این", "کتاٮ", "است"], ["این", "کتاب", "است"], ["این", "کتاب", "است"]]
    )
    assert merged == ["این", "کتاب", "است"]


def test_a_tie_keeps_the_reference_pass():
    merged, contested = vote_tokens([["این", "کتاب"], ["این", "کتاٮ"]])
    assert merged == ["این", "کتاب"]
    assert contested


def test_disagreements_are_reported_for_the_verifier():
    result = reconcile([reading("این کتاب است"), reading("این کتاٮ است")])
    assert result.agreement < 1.0
    assert any("کتاٮ" in d.describe() for d in result.disagreements)


def test_differing_block_counts_fall_back_to_the_medoid_reading():
    result = reconcile(
        [reading("بند نخست", "بند دوم"), reading("بند نخست بند دوم")]
    )
    assert result.structure_mismatch
    assert result.blocks


def test_the_medoid_is_the_reading_the_others_agree_with():
    odd = reading("چیزی کاملاً متفاوت که هیچ ربطی ندارد")
    good_one = reading("این جمله درست است و خوانا")
    good_two = reading("این جمله درست است و خوانا")
    result = reconcile([odd, good_one, good_two])
    assert result.text == "این جمله درست است و خوانا"


def test_uncertain_spans_and_overlays_are_collected():
    first = reading("متن")
    first.uncertain_spans = [{"text": "متن", "reason": "occluded"}]
    first.ignored_overlays = ["Edit PDF"]
    second = reading("متن")
    second.ignored_overlays = ["watermark"]
    result = reconcile([first, second])
    assert result.uncertain_spans
    assert set(result.ignored_overlays) == {"Edit PDF", "watermark"}
