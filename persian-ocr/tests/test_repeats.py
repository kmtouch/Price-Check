from persian_ocr.engines.base import Block
from persian_ocr.repeats import detect_repeated_boundaries, strip_repeated_boundaries


def page(*texts):
    return [Block("paragraph", t) for t in texts]


def test_a_running_header_repeated_verbatim_is_detected():
    pages = [
        page("غروبِ بت‌ها — نیچه", "متنِ صفحه‌ی یک است."),
        page("غروبِ بت‌ها — نیچه", "متنِ صفحه‌ی دو است."),
        page("غروبِ بت‌ها — نیچه", "متنِ صفحه‌ی سه است."),
        page("غروبِ بت‌ها — نیچه", "متنِ صفحه‌ی چهار است."),
    ]
    signatures = detect_repeated_boundaries(pages)
    assert signatures
    cleaned = strip_repeated_boundaries(pages, signatures)
    assert all(len(p) == 1 for p in cleaned)
    assert cleaned[0][0].text == "متنِ صفحه‌ی یک است."


def test_a_footer_with_a_changing_page_number_is_still_recognised():
    pages = [
        page("متنِ صفحه‌ی یک.", "نشرِ فلان — صفحه‌ی ۱"),
        page("متنِ صفحه‌ی دو.", "نشرِ فلان — صفحه‌ی ۲"),
        page("متنِ صفحه‌ی سه.", "نشرِ فلان — صفحه‌ی ۳"),
        page("متنِ صفحه‌ی چهار.", "نشرِ فلان — صفحه‌ی ۴"),
        page("متنِ صفحه‌ی پنج.", "نشرِ فلان — صفحه‌ی ۵"),
    ]
    signatures = detect_repeated_boundaries(pages)
    cleaned = strip_repeated_boundaries(pages, signatures)
    for original, result in zip(pages, cleaned):
        assert len(result) == 1
        assert "نشر" not in result[0].text
        assert result[0].text == original[0].text


def test_body_text_that_only_repeats_once_or_twice_is_left_alone():
    pages = [
        page("سلامِ تکراری.", "بندِ اصلی یک."),
        page("سلامِ تکراری.", "بندِ اصلی دو."),
        page("متنِ کاملاً متفاوت.", "بندِ اصلی سه."),
        page("باز هم چیزِ دیگر.", "بندِ اصلی چهار."),
        page("و بازهم فرق دارد.", "بندِ اصلی پنج."),
    ]
    signatures = detect_repeated_boundaries(pages)
    cleaned = strip_repeated_boundaries(pages, signatures)
    assert cleaned == [list(p) for p in pages]


def test_middle_of_page_text_is_never_touched_even_if_it_repeats():
    pages = [
        page("آغازِ صفحه.", "این جمله در وسط تکرار می‌شود.", "پایانِ صفحه‌ی یک."),
        page("آغازِ صفحه.", "این جمله در وسط تکرار می‌شود.", "پایانِ صفحه‌ی دو."),
        page("آغازِ صفحه.", "این جمله در وسط تکرار می‌شود.", "پایانِ صفحه‌ی سه."),
        page("آغازِ صفحه.", "این جمله در وسط تکرار می‌شود.", "پایانِ صفحه‌ی چهار."),
    ]
    signatures = detect_repeated_boundaries(pages)
    cleaned = strip_repeated_boundaries(pages, signatures)
    for result in cleaned:
        # the header (first block) is stripped; the middle line survives even
        # though it repeats too, because it is never a page's first/last block
        assert len(result) == 2
        assert "وسط تکرار" in result[0].text
        assert "پایانِ" in result[1].text


def test_a_single_page_document_never_strips_anything():
    pages = [page("عنوان", "بدنه")]
    signatures = detect_repeated_boundaries(pages)
    assert signatures == set()


def test_a_short_lone_page_number_is_not_a_signature_by_itself():
    pages = [page("۱", "متن"), page("۲", "متن"), page("۳", "متن"), page("۴", "متن")]
    signatures = detect_repeated_boundaries(pages)
    # digit-only boundary lines fold to an empty/too-short signature and
    # should not be treated as a running header on their own
    cleaned = strip_repeated_boundaries(pages, signatures)
    numbers = [p[0].text for p in cleaned if p]
    assert numbers == ["۱", "۲", "۳", "۴"]


def test_no_pages_is_handled_gracefully():
    assert detect_repeated_boundaries([]) == set()
    assert strip_repeated_boundaries([], set()) == []
