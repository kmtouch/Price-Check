from persian_ocr.lexicon import Lexicon, fold_word


def test_common_words_are_known():
    lexicon = Lexicon()
    for word in ("کتاب", "نوشتن", "فلسفه", "ترجمه"):
        assert lexicon.known(word), word


def test_inflected_forms_resolve_to_their_stem():
    lexicon = Lexicon()
    assert lexicon.known("کتاب‌ها")
    assert lexicon.known("کتاب‌هایش")
    assert lexicon.known("بزرگ‌ترین")
    assert lexicon.known("نمی‌نویسد") or lexicon.known("مینویسد")


def test_arabic_spelling_folds_onto_the_persian_one():
    assert fold_word("كتاب") == fold_word("کتاب")
    assert Lexicon().known("كتاب")


def test_the_document_teaches_its_own_vocabulary():
    text = "زردشتنامه زردشتنامه زردشتنامه"
    assert not Lexicon().known("زردشتنامه")
    assert Lexicon(document_text=text).known("زردشتنامه")


def test_a_word_seen_once_is_not_taken_on_trust():
    assert not Lexicon(document_text="زردشتنامه").known("زردشتنامه")


def test_shape_rules_catch_impossible_words():
    assert Lexicon.shape_problem("xyzفارسی")
    assert Lexicon.shape_problem("ااا")
    assert Lexicon.shape_problem("ًکتاب")
    assert Lexicon.shape_problem("کتاب") is None


def test_screening_flags_a_misread_word_and_not_the_rest():
    text = "این کتاب را خواندند و آن را دوست داشتند ولی کتاٮ دیگر نه"
    flags = [flag.word for flag in Lexicon().screen(text)]
    assert "کتاٮ" in flags
    assert "کتاب" not in flags


def test_foreign_words_are_not_flagged():
    flags = [flag.word for flag in Lexicon().screen("مصدرِ dämmern به معنای تاریک شدن است")]
    assert not any("dämmern" in flag for flag in flags)


def test_coverage_is_high_on_ordinary_prose():
    text = (
        "در این ترجمه نیز مانند ترجمه‌های پیشین من از او، این گونه واژه‌ها و "
        "عبارت‌ها و جمله‌ها را به فارسی ترجمه کرده‌ام."
    )
    assert Lexicon(document_text=text).coverage(text) > 0.9


def test_an_extra_dictionary_is_honoured(tmp_path):
    path = tmp_path / "extra.txt"
    path.write_text("# comment\nزردشتنامه/AB\n", encoding="utf-8")
    assert Lexicon(extra_paths=(path,)).known("زردشتنامه")
