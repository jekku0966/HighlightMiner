from highlightminer.chat import analyze_chat


def test_chat_burst_scores_high():
    records = []
    for t in range(120):
        records.append({"time": float(t), "text": "normal"})
    for i in range(15):
        records.append({"time": 60.2 + i * 0.02, "text": "LUL"})
    features = analyze_chat(records, 120)
    peak = max(features, key=lambda x: x["score"])
    assert 59 <= peak["time"] <= 62
    assert peak["score"] > 0.8
