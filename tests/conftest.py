"""Keep tests away from real credentials and real data: never load the repo's .env or read its
data/ folder, and clear any keys the shell already exported, so no test can reach a real account."""

import os

import pytest

_SECRET_PREFIXES = (
    "ANTHROPIC_",
    "BEEPER_",
    "GMAIL_",
    "SLACK_USER_TOKEN",
    "STRAVA_",
    "PROXENOS_",
    "TWIN_",
)


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    monkeypatch.setattr("proxenos.config.load_dotenv", lambda *args, **kwargs: False)
    # The repo's data/ folder holds real downloads; tests only ever see their own inbox.
    monkeypatch.setattr("proxenos.importer.inboxes", lambda vault: [vault / "inbox"])

    # Nor the embedding model on this computer: a test that needs one brings a fake.
    def no_model(texts):
        raise RuntimeError("no embedding model in tests")

    monkeypatch.setattr("proxenos.vectors._ollama", no_model)
    for name in list(os.environ):
        if name.startswith(_SECRET_PREFIXES):
            monkeypatch.delenv(name)
