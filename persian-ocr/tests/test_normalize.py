from persian_ocr.normalize import (
    ZWNJ,
    NormalizeOptions,
    Normalizer,
    fold_for_compare,
    normalize,
)


def test_arabic_letters_become_persian():
    assert normalize("كتاب ايشان") == "کتاب ایشان"


def test_arabic_indic_digits_become_persian():
    assert normalize("سال ٢٠٢٥") == "سال ۲۰۲۵"


def test_latin_digits_convert_in_persian_context():
    assert normalize("در ژانویه‌ی 1889 چاپ شد") == "در ژانویه‌ی ۱۸۸۹ چاپ شد"


def test_latin_digits_survive_in_latin_context():
    # A German title inside a Persian text must keep its own digits.
    assert "1889" in normalize("Dämmerung, 1889 ist gut")
    assert "978" in normalize("این کتاب ISBN 978-3-16 دارد")


def test_punctuation_persianised_only_in_persian_lines():
    assert normalize("سلام , خوبی ?") == "سلام، خوبی؟"
    assert normalize("Hello, world is fine") == "Hello, world is fine"


def test_tatweel_is_preserved_by_default():
    # The explicit dash separator is the author's, not an artefact.
    text = "برادرـ ام و دادـ وـ دهش"
    assert normalize(text) == text


def test_tatweel_can_be_stripped_on_request():
    options = NormalizeOptions(strip_tatweel=True)
    assert "ـ" not in normalize("برادرـ ام", options)


def test_repeated_zwnj_collapses():
    assert normalize(f"کتاب{ZWNJ}{ZWNJ}ها") == f"کتاب{ZWNJ}ها"


def test_zwnj_next_to_a_space_never_glues_two_words():
    # Whitespace wins: a half-space touching a space is contradictory, and
    # gluing two separate words together would be the worse mistake.
    assert normalize(f"سلام{ZWNJ} دنیا") == "سلام دنیا"
    assert normalize(f"می {ZWNJ} کنم") == "می کنم"


def test_a_dropped_half_space_is_restored_from_the_document_convention():
    body = " ".join([f"می{ZWNJ}رود"] * 6)
    assert normalize(f"{body} و می {ZWNJ} رود").endswith(f"و می{ZWNJ}رود")


def test_zwnj_at_a_line_end_does_not_join_the_lines():
    assert normalize(f"کتاب{ZWNJ}\nها") == "کتاب\nها"


def test_zwnj_at_a_word_boundary_is_dropped():
    assert normalize(f"{ZWNJ}سلام{ZWNJ} دنیا") == "سلام دنیا"


def test_spacing_around_punctuation_and_brackets():
    assert normalize("سلام ، دنیا ( تست ) بود") == "سلام، دنیا (تست) بود"


def test_straight_quotes_become_guillemets():
    assert normalize('او گفت "سلام" و رفت') == "او گفت «سلام» و رفت"


def test_half_space_follows_the_document_convention():
    # Six ZWNJ spellings against one spaced one: the odd one out is the typo.
    body = " ".join([f"می{ZWNJ}رود"] * 6)
    text = f"{body} و می رود"
    assert normalize(text).count("می رود") == 0


def test_half_space_left_alone_when_the_document_is_split():
    text = " ".join([f"می{ZWNJ}رود"] * 3 + ["می رود"] * 3)
    assert "می رود" in normalize(text)


def test_half_space_off_keeps_everything():
    options = NormalizeOptions(half_space="off")
    text = " ".join([f"می{ZWNJ}رود"] * 6) + " و می رود"
    assert "می رود" in normalize(text, options)


def test_invisible_marks_are_removed_but_zwnj_survives():
    assert normalize(f"‎سلام‏ {ZWNJ}") == "سلام"


def test_fold_for_compare_ignores_encoding_choices():
    assert fold_for_compare(f"می{ZWNJ}کنم") == fold_for_compare("میکنم")
    assert fold_for_compare("كتاب") == fold_for_compare("کتاب")
    assert fold_for_compare("۱۲۳") == fold_for_compare("123")


def test_change_report_names_the_rules_that_fired():
    _, changes = Normalizer().apply("كتاب ٢٠٢٥ , تست")
    assert set(changes) >= {"letters", "digits", "punctuation"}


def test_a_footnote_marker_stays_attached_to_its_word():
    # واگنر(۸) is set exactly like that in print; pushing the bracket away
    # would be a change, not a fix.
    assert normalize("داستانِ واگنر(۸) آغاز کرد") == "داستانِ واگنر(۸) آغاز کرد"


def test_brackets_still_hug_their_contents():
    assert normalize("کتاب ( چاپ دوم ) بود") == "کتاب (چاپ دوم) بود"


def test_the_unreadable_marker_is_never_split():
    assert normalize("نیچه ⟨؟⟩ای را به اوج می‌رساند") == "نیچه ⟨؟⟩ای را به اوج می‌رساند"
