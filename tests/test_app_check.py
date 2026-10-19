import pytest

from ytm_hygiene.app import main


def test_check_exits_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        main(["--check"])
    assert e.value.code == 0
    assert not (tmp_path / "check-error.txt").exists()


def test_check_failure_writes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import ytmusicapi

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(ytmusicapi, "YTMusic", boom)
    with pytest.raises(SystemExit) as e:
        main(["--check"])
    assert e.value.code == 1
    assert "nope" in (tmp_path / "check-error.txt").read_text()
