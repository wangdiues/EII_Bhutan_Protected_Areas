import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "02_scripts"))

from _shared import config


def test_gee_key_path_prefers_environment(monkeypatch, tmp_path):
    key_path = tmp_path / "key.json"
    monkeypatch.setenv("EII_GEE_KEY_PATH", str(key_path))

    assert config.get_path("gee_key") == key_path.resolve()


def test_configured_gee_key_filename_is_used(monkeypatch, tmp_path):
    monkeypatch.delenv("EII_GEE_KEY_PATH", raising=False)
    monkeypatch.setitem(config.CONFIG, "gee_key_filename", "configured-key.json")

    expected = tmp_path / "06_Google_application_credentials" / "configured-key.json"
    assert config.get_path("gee_key", tmp_path) == expected.resolve()


def test_fake_example_key_is_not_used_as_real_key(monkeypatch, tmp_path):
    monkeypatch.delenv("EII_GEE_KEY_PATH", raising=False)
    monkeypatch.setitem(config.CONFIG, "gee_key_filename", None)

    credentials_dir = tmp_path / "06_Google_application_credentials"
    credentials_dir.mkdir()
    (credentials_dir / "fake_service_account.example.json.template").write_text("{}", encoding="utf-8")

    default_key = credentials_dir / "service-account-key.json"
    assert config.get_path("gee_key", tmp_path) == default_key.resolve()

    real_key = credentials_dir / "service-account-key.real.json"
    real_key.write_text("{}", encoding="utf-8")
    assert config.get_path("gee_key", tmp_path) == real_key.resolve()


def test_expected_pa_count_matches_current_processed_network():
    assert config.CONFIG["expected_pa_count"] == 20
