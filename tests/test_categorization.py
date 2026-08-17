from highlightminer.categorization import content_folder_name, normalize_content_label


def test_content_label_defaults_to_unsorted() -> None:
    assert normalize_content_label(None) == "Unsorted"
    assert normalize_content_label("   ") == "Unsorted"


def test_content_label_collapses_whitespace() -> None:
    assert normalize_content_label("  Just   Chatting  ") == "Just Chatting"


def test_content_folder_name_keeps_readable_unicode() -> None:
    assert content_folder_name("Alan Wake 2 – Yö") == "Alan Wake 2 – Yö"


def test_content_folder_name_replaces_windows_invalid_characters() -> None:
    assert content_folder_name('Game: Episode/One?') == "Game_ Episode_One_"


def test_content_folder_name_avoids_reserved_windows_names() -> None:
    assert content_folder_name("CON") == "CON_"
    assert content_folder_name("LPT1.txt") == "LPT1.txt_"
