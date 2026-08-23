import json
from pathlib import Path

import pytest

from persian_ocr.cli import build_parser, main
from persian_ocr.webui import parse_multipart


def test_the_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_convert_defaults_match_the_documented_behaviour():
    args = build_parser().parse_args(["convert", "book.pdf"])
    assert args.passes == 2
    assert args.dpi == 300
    assert not args.no_verify
    assert args.model == "claude-opus-5"


def test_convert_flags_are_wired_through():
    from persian_ocr.cli import _settings_from_args

    args = build_parser().parse_args(
        ["convert", "book.pdf", "--passes", "3", "--no-verify", "--latin-digits",
         "--dpi", "450", "--engine", "tesseract", "--dictionary", "a.txt"]
    )
    settings = _settings_from_args(args)
    assert settings.passes == 3
    assert settings.verify is False
    assert settings.persian_digits is False
    assert settings.dpi == 450
    assert settings.engine == "tesseract"
    assert [str(path) for path in settings.lexicon_paths] == ["a.txt"]


def test_benchmark_prints_accuracy(tmp_path, capsys):
    hypothesis = tmp_path / "hyp.txt"
    reference = tmp_path / "ref.txt"
    hypothesis.write_text("این کتاٮ خوب است", encoding="utf-8")
    reference.write_text("این کتاب خوب است", encoding="utf-8")

    assert main(["benchmark", str(hypothesis), "--reference", str(reference)]) == 0
    output = capsys.readouterr().out
    assert "character accuracy" in output
    assert "differences" in output


def test_benchmark_json_output(tmp_path, capsys):
    hypothesis = tmp_path / "hyp.txt"
    reference = tmp_path / "ref.txt"
    hypothesis.write_text("سلام", encoding="utf-8")
    reference.write_text("سلام", encoding="utf-8")

    assert main(["benchmark", str(hypothesis), "--reference", str(reference), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["character_accuracy"] == 1.0


def test_benchmark_against_the_bundled_reference(tmp_path, samples_dir, capsys):
    reference = samples_dir / "reference" / "page-01.txt"
    assert main(["benchmark", str(reference), "--reference", str(reference), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["word_accuracy"] == 1.0
    assert payload["reference_words"] > 50


def test_convert_reports_missing_inputs(tmp_path, capsys):
    assert main(["convert", str(tmp_path / "nothing.pdf")]) == 2
    assert "error" in capsys.readouterr().err


def test_doctor_runs(capsys):
    main(["doctor"])
    assert "persian-ocr" in capsys.readouterr().out


def test_multipart_parser_reads_files_and_fields():
    boundary = b"XBOUND"
    body = (
        b"--XBOUND\r\n"
        b'Content-Disposition: form-data; name="files"; filename="page.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
        b"\x89PNG-data\r\n"
        b"--XBOUND\r\n"
        b'Content-Disposition: form-data; name="passes"\r\n\r\n'
        b"3\r\n"
        b"--XBOUND--\r\n"
    )
    files, fields = parse_multipart(body, boundary)
    assert files == [("page.png", b"\x89PNG-data")]
    assert fields["passes"] == "3"


def test_multipart_parser_strips_path_traversal():
    boundary = b"B"
    body = (
        b"--B\r\n"
        b'Content-Disposition: form-data; name="files"; filename="../../etc/passwd.png"\r\n\r\n'
        b"data\r\n"
        b"--B--\r\n"
    )
    files, _ = parse_multipart(body, boundary)
    assert files[0][0] == "passwd.png"


def _write_verify_fixture(fixtures: Path, image: Path, payload: dict, settings) -> None:
    """Record a canned verification reply keyed on the tiles the pipeline sends."""
    import hashlib
    import json

    from PIL import Image

    from persian_ocr.preprocess import condition, tile_page

    conditioned, _ = condition(
        Image.open(image),
        do_autocrop=settings.autocrop,
        do_deskew=settings.deskew,
        do_enhance=settings.enhance,
    )
    tiles = tile_page(conditioned, max_edge=settings.max_edge, overlap=settings.tile_overlap,
                      enabled=settings.tile)
    digest = hashlib.sha256(tiles[0].to_bytes()[0]).hexdigest()[:12]
    (fixtures / "verify").mkdir(parents=True, exist_ok=True)
    (fixtures / "verify" / f"{digest}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_verify_command_corrects_an_existing_transcription(tmp_path, sample_image, monkeypatch):
    from persian_ocr.cli import _settings_from_args

    args = build_parser().parse_args(
        ["verify", "x.txt", "--images", "y.jpg", "--engine", "mock", "--no-cache"]
    )
    settings = _settings_from_args(args)

    fixtures = tmp_path / "fixtures"
    _write_verify_fixture(
        fixtures,
        sample_image,
        {
            "verdict": "corrected",
            "corrections": [
                {"block_index": 0, "original": "کتاٮ", "corrected": "کتاب",
                 "reason": "missing dots", "confidence": 0.97}
            ],
            "missing_text": [],
            "notes": "",
        },
        settings,
    )
    monkeypatch.setenv("PERSIAN_OCR_FIXTURES", str(fixtures))

    transcript = tmp_path / "draft.txt"
    transcript.write_text("این کتاٮ خوب است", encoding="utf-8")
    output = tmp_path / "fixed.txt"

    code = main([
        "verify", str(transcript), "--images", str(sample_image), "-o", str(output),
        "--engine", "mock", "--no-cache", "-q",
    ])
    assert code == 0
    assert "کتاب" in output.read_text(encoding="utf-8")
    assert (tmp_path / "fixed.report.json").exists()


def test_multipart_parser_does_not_truncate_binary_content_ending_in_crlf_bytes():
    # A blanket strip of trailing \r/\n would eat real bytes here; the exact
    # CRLF-only strip must not.
    payload = b"\x89PNG\r\n\x1a\n\x00\x00\x0d\x0a"
    boundary = b"B"
    body = (
        b"--B\r\n"
        b'Content-Disposition: form-data; name="files"; filename="page.png"\r\n\r\n'
        + payload
        + b"\r\n--B--\r\n"
    )
    files, _ = parse_multipart(body, boundary)
    assert files == [("page.png", payload)]


def test_multipart_parser_handles_no_parts():
    files, fields = parse_multipart(b"--B--\r\n", b"B")
    assert files == [] and fields == {}
