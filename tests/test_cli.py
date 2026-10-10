import json

import pytest

from kleinscoutr.cli import main


def test_help(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0
    assert "kleinscoutr" in capsys.readouterr().out


def test_status_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "name": "empty",
                "site": "kleinanzeigen",
                "location": "",
                "radius": 20,
                "price": [0, 200],
                "searches": [],
            }
        )
    )
    main(["status", "--profile", str(profile)])
    out = capsys.readouterr().out
    assert "new: 0" in out
    assert "gone: 0" in out
    assert (tmp_path / "runs/empty/empty.db").exists()


def test_invalid_profile_cli(tmp_path, capsys):
    profile = tmp_path / "bad.json"
    profile.write_text("{}")
    with pytest.raises(SystemExit) as error:
        main(["status", "--profile", str(profile)])
    assert error.value.code == 2
    assert "name: required" in capsys.readouterr().err
