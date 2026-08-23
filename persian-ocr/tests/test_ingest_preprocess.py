import pytest
from PIL import Image

from persian_ocr.ingest import (
    IngestError,
    expand_inputs,
    load_pages,
    parse_page_selection,
)
from persian_ocr.preprocess import (
    autocrop,
    condition,
    detect_content_box,
    estimate_skew,
    tile_page,
)


def test_page_selection_is_one_based_and_inclusive():
    assert parse_page_selection("1-3,7,9-10") == [0, 1, 2, 6, 8, 9]
    assert parse_page_selection("2") == [1]


@pytest.mark.parametrize("spec", ["0", "abc", "5-2", ""])
def test_bad_page_selections_are_rejected(spec):
    with pytest.raises(IngestError):
        parse_page_selection(spec)


def test_missing_inputs_are_reported(tmp_path):
    with pytest.raises(IngestError):
        expand_inputs([str(tmp_path / "nope.pdf")])


def test_a_directory_expands_in_natural_order(tmp_path):
    for name in ("page-10.png", "page-2.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    names = [path.name for path in expand_inputs([str(tmp_path)])]
    assert names == ["page-2.png", "page-10.png"]


def test_images_load_as_pages(sample_image):
    pages = load_pages([sample_image])
    assert len(pages) == 1
    assert pages[0].image.width > 100


def test_page_selection_needs_a_single_pdf(sample_image):
    with pytest.raises(IngestError):
        load_pages([sample_image], page_selection=[0])


def test_the_page_is_found_inside_a_screenshot(sample_image):
    image = Image.open(sample_image)
    box = detect_content_box(image)
    assert box is not None
    left, top, right, bottom = box
    assert top > 0                      # the toolbar was excluded
    assert (right - left) > image.width * 0.5


def test_autocrop_leaves_a_plain_page_alone():
    plain = Image.new("RGB", (800, 1000), "white")
    cropped, changed = autocrop(plain)
    assert not changed
    assert cropped.size == plain.size


def test_skew_estimation_finds_a_deliberate_rotation():
    page = Image.new("L", (600, 800), 255)
    for y in range(80, 720, 40):        # fake text lines
        for x in range(60, 540):
            page.putpixel((x, y), 0)
            page.putpixel((x, y + 1), 0)
    rotated = page.rotate(-1.5, fillcolor=255)
    assert estimate_skew(rotated) == pytest.approx(1.5, abs=0.6)


def test_conditioning_reports_what_it_did(sample_image):
    image, info = condition(Image.open(sample_image))
    assert info["enhanced"]
    assert set(info) >= {"cropped", "skew_angle", "enhanced", "size"}


def test_a_small_page_is_sent_whole():
    tiles = tile_page(Image.new("L", (1000, 1200), 255))
    assert len(tiles) == 1
    assert tiles[0].is_first and tiles[0].is_last


def test_a_tall_page_is_sliced_with_overlap():
    tiles = tile_page(Image.new("L", (1200, 4000), 255), max_edge=1568, overlap=0.15)
    assert len(tiles) > 1
    # every slice is full height, consecutive slices overlap, and together they
    # cover the whole page
    assert tiles[0].top == 0
    for previous, current in zip(tiles, tiles[1:]):
        assert current.top > previous.top
        assert current.top < previous.top + 1200      # genuine overlap
    assert tiles[-1].top + 1200 >= 4000


def test_tiles_never_exceed_the_api_edge_limit():
    for tile in tile_page(Image.new("L", (2480, 3500), 255), max_edge=1568):
        assert max(tile.image.size) <= 1568


def test_tiling_can_be_switched_off():
    assert len(tile_page(Image.new("L", (1200, 4000), 255), enabled=False)) == 1


def test_tiles_encode_as_png_within_the_size_budget(sample_image):
    image, _ = condition(Image.open(sample_image))
    data, media_type = tile_page(image)[0].to_bytes()
    assert media_type in {"image/png", "image/jpeg"}
    assert 0 < len(data) < 4_500_000
