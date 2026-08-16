from highlightminer.transcribe import score_text


def test_reaction_scores_above_plain_text():
    phrases = ["what the fuck", "no way"]
    plain, _ = score_text("I am walking over to the next room.", phrases)
    reaction, reasons = score_text("WHAT THE FUCK! No way! hahaha", phrases)
    assert reaction > plain
    assert reaction >= 0.7
    assert reasons
