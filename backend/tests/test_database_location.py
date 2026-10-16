from app.db import resolve_database_path


def test_explicit_database_location_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CATHEDRA_DATA_DIR", str(tmp_path / "isolated"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    assert resolve_database_path(tmp_path / "source") == tmp_path / "isolated" / "cathedra.db"


def test_development_does_not_implicitly_open_installed_database(monkeypatch, tmp_path):
    monkeypatch.delenv("CATHEDRA_DATA_DIR", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    installed = tmp_path / "profile" / "Cathedra-Faculty" / "data" / "cathedra.db"
    installed.parent.mkdir(parents=True)
    installed.touch()
    assert (
        resolve_database_path(tmp_path / "source") == tmp_path / "source" / "data" / "cathedra.db"
    )


def test_uninstalled_checkout_uses_source_data(monkeypatch, tmp_path):
    monkeypatch.delenv("CATHEDRA_DATA_DIR", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    assert (
        resolve_database_path(tmp_path / "source") == tmp_path / "source" / "data" / "cathedra.db"
    )


def test_no_windows_profile_uses_source_data(monkeypatch, tmp_path):
    monkeypatch.delenv("CATHEDRA_DATA_DIR", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)
    assert (
        resolve_database_path(tmp_path / "source") == tmp_path / "source" / "data" / "cathedra.db"
    )
