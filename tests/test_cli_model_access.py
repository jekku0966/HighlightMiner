from __future__ import annotations

import pytest

from highlightminer.cli import build_parser


def test_analyze_model_flags_default_to_no_implicit_permission() -> None:
    args = build_parser().parse_args(["analyze", "vod.mp4"])

    assert args.allow_model_download is False
    assert args.no_transcription is False


def test_analyze_can_explicitly_allow_model_download_for_one_command() -> None:
    args = build_parser().parse_args(["analyze", "vod.mp4", "--allow-model-download"])

    assert args.allow_model_download is True
    assert args.no_transcription is False


def test_analyze_can_explicitly_disable_transcription_for_one_command() -> None:
    args = build_parser().parse_args(["analyze", "vod.mp4", "--no-transcription"])

    assert args.allow_model_download is False
    assert args.no_transcription is True


def test_analyze_model_flags_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["analyze", "vod.mp4", "--allow-model-download", "--no-transcription"]
        )
