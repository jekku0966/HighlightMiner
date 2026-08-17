from pathlib import Path

from highlightminer.identity import describe_source, sampled_file_fingerprint, stable_signature


def test_sampled_fingerprint_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    vod = tmp_path / "vod.mp4"
    vod.write_bytes((b"abc123" * 5000) + b"tail")
    first = sampled_file_fingerprint(vod, sample_bytes=4096)
    second = sampled_file_fingerprint(vod, sample_bytes=4096)
    assert first == second

    vod.write_bytes((b"abc123" * 5000) + b"TAIL")
    assert sampled_file_fingerprint(vod, sample_bytes=4096) != first


def test_describe_source_does_not_depend_on_filename(tmp_path: Path) -> None:
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.mp4"
    payload = b"same-vod-content" * 1000
    first.write_bytes(payload)
    second.write_bytes(payload)
    assert describe_source(first)["fingerprint"] == describe_source(second)["fingerprint"]


def test_stable_signature_ignores_mapping_order() -> None:
    assert stable_signature("x", {"a": 1, "b": 2}) == stable_signature("x", {"b": 2, "a": 1})
