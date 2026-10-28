"""Keep tests away from real credentials and real data: never load the repo's .env or read its
data/ folder, and clear any keys the shell already exported, so no test can reach a real account."""

import os

import pytest

_SECRET_PREFIXES = ("ANTHROPIC_", "GMAIL_", "SLACK_USER_TOKEN", "STRAVA_", "PROXENOS_", "TWIN_")


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    monkeypatch.setattr("proxenos.config.load_dotenv", lambda *args, **kwargs: False)
    # The repo's data/ folder holds real downloads; tests only ever see their own inbox.
    monkeypatch.setattr("proxenos.importer.inboxes", lambda vault: [vault / "inbox"])
    for name in list(os.environ):
        if name.startswith(_SECRET_PREFIXES):
            monkeypatch.delenv(name)
