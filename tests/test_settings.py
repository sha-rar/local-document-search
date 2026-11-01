import json

from local_document_search.settings import (
    MAX_RESULT_LIMIT,
    Settings,
    exclusions,
    load_settings,
    save_settings,
)


def test_round_trip(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    settings = Settings(
        folders=["D:/Docs"],
        excluded_folders=["D:/Docs/Private"],
        result_limit=50,
        index_on_startup=True,
    )
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert list(path.parent.iterdir()) == [path]  # no temp files left behind


def test_missing_or_corrupt_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "absent.json") == Settings()
    corrupt = tmp_path / "settings.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_settings(corrupt) == Settings()
    corrupt.write_text("[1, 2]", encoding="utf-8")
    assert load_settings(corrupt) == Settings()


def test_invalid_values_fall_back_individually(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "folders": ["D:/Docs", 3],
                "excluded_folders": ["D:/Tmp"],
                "result_limit": True,
                "index_on_startup": "yes",
                "future_option": 1,
            }
        ),
        encoding="utf-8",
    )
    assert load_settings(path) == Settings(excluded_folders=["D:/Tmp"])


def test_result_limit_is_clamped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"result_limit": 10**6}), encoding="utf-8")
    assert load_settings(path).result_limit == MAX_RESULT_LIMIT


def test_default_exclusions(tmp_path):
    settings = load_settings(tmp_path / "absent.json")
    assert settings.excluded_patterns == ["~$*", ".git", "node_modules"]
    rules = exclusions(settings)
    assert rules.patterns == ("~$*", ".git", "node_modules") and rules.extensions == ()
