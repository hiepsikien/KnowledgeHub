from __future__ import annotations

import os

from knowledgehub.dotenv import load_dotenv


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "READ_HUB_TOKEN=from-file\nREAD_API_URL=https://example.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("READ_HUB_TOKEN", "from-shell")
    monkeypatch.delenv("READ_API_URL", raising=False)
    load_dotenv(env)
    assert os.environ["READ_HUB_TOKEN"] == "from-shell"
    assert os.environ["READ_API_URL"] == "https://example.test"
