from highlightminer.config import Settings
from highlightminer.scoring import find_candidates


def test_candidate_created_around_spike():
    settings = Settings(
        min_candidate_score=0.35,
        pre_roll_sec=10,
        post_roll_sec=10,
        merge_gap_sec=3,
        reaction_phrases=[],
    )
    audio = [{"time": float(t), "score": 1.0 if t == 50 else 0.1} for t in range(100)]
    transcript = [{"start": 49.0, "end": 52.0, "text": "wow", "score": 0.9}]
    result = find_candidates(100, audio, transcript, [], settings)
    assert result
    assert result[0]["start"] <= 50 <= result[0]["end"]
