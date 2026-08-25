from persian_ocr.assemble import (
    PageResult,
    find_overlap,
    merge_tiles,
    paragraph_stats,
    relate,
    render_document,
    splice,
)
from persian_ocr.engines.base import Block


def blocks(*texts, kind="paragraph"):
    return [Block(kind, text) for text in texts]


def test_overlap_between_tiles_is_measured_in_words():
    assert find_overlap("الف ب پ ت ث ج", "پ ت ث ج چ ح") == 4
    assert find_overlap("الف ب پ", "چ ح خ") == 0


def test_overlap_ignores_half_space_differences():
    assert find_overlap("کتاب‌ها را خواندند و رفتند", "کتابها را خواندند و رفتند سپس") >= 4


def test_splice_joins_a_paragraph_cut_by_a_tile_boundary():
    assert splice("یک دو سه چهار پنج", "سه چهار پنج شش هفت") == "یک دو سه چهار پنج شش هفت"


def test_splice_drops_a_tile_that_only_repeats_the_previous_one():
    assert splice("یک دو سه چهار", "یک دو سه چهار") == "یک دو سه چهار"


def test_splice_returns_none_for_unrelated_text():
    assert splice("یک دو سه چهار", "الف ب پ ت") is None


def test_merge_tiles_removes_the_deliberate_overlap():
    merged = merge_tiles([blocks("الف ب پ ت ث ج"), blocks("پ ت ث ج چ ح خ")])
    assert len(merged) == 1
    assert merged[0].text == "الف ب پ ت ث ج چ ح خ"


def test_merge_tiles_keeps_genuinely_new_paragraphs():
    merged = merge_tiles([blocks("بند نخست."), blocks("بند دوم.", "بند سوم.")])
    assert [b.text for b in merged] == ["بند نخست.", "بند دوم.", "بند سوم."]


def test_merge_tiles_joins_a_cut_paragraph_without_overlap():
    merged = merge_tiles([blocks("جمله‌ای که ادامه"), blocks("دارد و تمام می‌شود.")])
    assert merged[0].text == "جمله‌ای که ادامه دارد و تمام می‌شود."


def test_page_numbers_are_emitted_on_their_own_line():
    page = PageResult(0, "p1", blocks("متنِ صفحه") + blocks("۴", kind="page_number"))
    assert render_document([page], page_marks="number") == "متنِ صفحه\n\n۴\n"


def test_page_numbers_can_be_dropped():
    page = PageResult(0, "p1", blocks("متنِ صفحه") + blocks("۴", kind="page_number"))
    assert render_document([page], page_marks="none") == "متنِ صفحه\n"


def test_footnotes_come_after_the_body():
    page = PageResult(
        0, "p1", blocks("متنِ اصلی") + blocks("۸. توضیحِ پانویس", kind="footnote")
    )
    assert render_document([page]).splitlines()[0] == "متنِ اصلی"
    assert "توضیحِ پانویس" in render_document([page])


def test_a_paragraph_split_over_a_page_break_is_rejoined():
    first = PageResult(0, "p1", blocks("جمله‌ای که ادامه"))
    second = PageResult(1, "p2", blocks("دارد و تمام می‌شود."))
    assert render_document([first, second], page_marks="none") == (
        "جمله‌ای که ادامه دارد و تمام می‌شود.\n"
    )


def test_a_finished_sentence_is_not_glued_to_the_next_page():
    first = PageResult(0, "p1", blocks("جمله تمام شد."))
    second = PageResult(1, "p2", blocks("جمله‌ی تازه."))
    assert render_document([first, second], page_marks="none") == (
        "جمله تمام شد.\n\nجمله‌ی تازه.\n"
    )


def test_paragraph_stats_counts_what_it_says():
    stats = paragraph_stats("یک دو\n\nسه چهار پنج\n")
    assert stats["words"] == 5
    assert stats["paragraphs"] == 2


def test_two_page_numbers_on_one_image_both_survive():
    # A screenshot spanning a page break carries the number closing the
    # previous page and the one closing this page; both are printed, in place.
    page = PageResult(
        0,
        "spread.jpg",
        blocks("پایانِ صفحه‌ی پیشین")
        + blocks("۴", kind="page_number")
        + blocks("آغازِ صفحه‌ی تازه")
        + blocks("۵", kind="page_number"),
    )
    assert render_document([page]) == (
        "پایانِ صفحه‌ی پیشین\n\n۴\n\nآغازِ صفحه‌ی تازه\n\n۵\n"
    )


def test_page_numbers_keep_their_place_not_the_page_end():
    page = PageResult(0, "p", blocks("۴", kind="page_number") + blocks("متنِ صفحه"))
    assert render_document([page]) == "۴\n\nمتنِ صفحه\n"


# --- tile overlap handling -------------------------------------------------
def test_relate_recognises_a_repeated_paragraph():
    text = "یک دو سه چهار پنج شش هفت هشت"
    assert relate(text, text)[0] == "duplicate"


def test_relate_recognises_the_tail_of_a_paragraph_we_already_have():
    whole = "یک دو سه چهار پنج شش هفت هشت نه ده"
    tail = "شش هفت هشت نه ده"
    assert relate(whole, tail)[0] == "duplicate"


def test_relate_survives_a_small_wording_difference():
    # Two readings of the same lines differ in punctuation; that must not stop
    # the repeat from being recognised.
    whole = "ولی در جاهایِ دیگر که چنین خطایی پیش نمی‌آید، بدون تیره می‌آورم، مانندِ: دانش‌اش، کتاب‌ام."
    tail = "که چنین خطایی پیش نمی‌آید، بدون تیره می‌آورم، مانندِ دانش‌اش، کتاب‌ام."
    assert relate(whole, tail)[0] == "duplicate"


def test_relate_prefers_the_fuller_reading():
    clipped = "یک دو سه چهار پنج شش"
    whole = "یک دو سه چهار پنج شش هفت هشت نه ده یازده"
    kind, text = relate(clipped, whole)
    assert kind == "fuller" and text == whole


def test_relate_joins_a_paragraph_cut_at_the_seam():
    head = "یک دو سه چهار پنج شش هفت"
    tail = "پنج شش هفت هشت نه ده یازده دوازده سیزده"
    kind, text = relate(head, tail)
    assert kind == "continues"
    assert text == "یک دو سه چهار پنج شش هفت هشت نه ده یازده دوازده سیزده"


def test_relate_leaves_unrelated_paragraphs_alone():
    a = "نیچه همیشه بسیار فشرده و جنگی چیز می‌نویسد تا جایی که به نظر می‌رسد"
    b = "در این ترجمه نیز مانند ترجمه‌های پیشین من از او این گونه واژه‌ها را"
    assert relate(a, b)[0] == "unrelated"


def test_heavily_overlapping_tiles_do_not_double_the_page():
    # 50%-overlapping tiles repeat whole paragraphs, not just the seam.
    first = blocks("بندِ یکم که کامل است و تمام شد.", "بندِ دوم که ادامه")
    second = blocks("بندِ دوم که ادامه دارد و تمام شد.", "بندِ سوم تازه است.")
    third = blocks("بندِ سوم تازه است.", "بندِ چهارم پایانی است.")
    merged = merge_tiles([first, second, third])
    assert [b.text for b in merged] == [
        "بندِ یکم که کامل است و تمام شد.",
        "بندِ دوم که ادامه دارد و تمام شد.",
        "بندِ سوم تازه است.",
        "بندِ چهارم پایانی است.",
    ]


def test_real_overlapping_tiles_reassemble_into_the_page():
    """Regression test on real engine output for one of the sample pages.

    `tests/data/real_tiles_page01.json` holds the three tile readings a live
    run produced. Merged naively they doubled the page; this is the check that
    they do not.
    """
    import json
    from pathlib import Path

    from persian_ocr.metrics import compare

    root = Path(__file__).resolve().parents[1]
    tiles = json.loads((root / "tests/data/real_tiles_page01.json").read_text(encoding="utf-8"))
    merged = merge_tiles([[Block("paragraph", text) for text in tile] for tile in tiles["tiles"]])
    text = "\n\n".join(block.text for block in merged)
    reference = (root / "samples/reference/page-01.txt").read_text(encoding="utf-8")

    assert len(merged) == 5
    # Doubling the page would put word count near 2x; this is the real signal.
    assert 0.9 < len(text.split()) / len(reference.split()) < 1.1
    assert compare(text, reference).character_accuracy > 0.98
