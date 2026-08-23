from persian_ocr.assemble import (
    PageResult,
    find_overlap,
    merge_tiles,
    paragraph_stats,
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
