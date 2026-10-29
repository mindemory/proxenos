"""Keep tests away from real credentials and real data: never load the repo's .env, the settings
file or the secure store (the Keychain, Windows Credential Manager, the Secret Service), nor read
the data/ folder, and clear any keys the shell already exported, so no test can reach a real
account."""

import os
import subprocess

import pytest

_SECRET_PREFIXES = (
    "ANTHROPIC_",
    "BEEPER_",
    "GMAIL_",
    "GOOGLE_CLIENT_",
    "SLACK_USER_TOKEN",
    "STRAVA_",
    "PROXENOS_",
    "TWIN_",
)


class FakeSecurity:
    """The `security` command over a dict of items by account, so no test touches the Keychain.
    It keeps every command it was given, to show no secret was ever on one."""

    def __init__(self):
        self.items: dict[str, str] = {}
        self.commands: list[list[str]] = []

    def __call__(self, args, stdin=None):
        self.commands.append(args)
        if args == ["-i"]:  # each line a command, as `security -i` reads them
            for line in (stdin or "").splitlines():
                self._run(line.split())
            return subprocess.CompletedProcess(args, 0, "", "")
        return self._run(args)

    def _run(self, args):
        command, rest, options = args[0], args[1:], {}
        while rest:
            if rest[0] in ("-U", "-w"):
                options[rest.pop(0)] = True
            else:
                options[rest[0]] = rest[1]
                rest = rest[2:]
        assert options["-s"] == "Proxenos"
        account = options["-a"]
        found = account in self.items
        if command == "add-generic-password":
            if found and "-U" not in options:
                return subprocess.CompletedProcess(args, 45, "", "already exists")
            self.items[account] = bytes.fromhex(options["-X"]).decode()
            return subprocess.CompletedProcess(args, 0, "", "")
        if not found:
            return subprocess.CompletedProcess(args, 44, "", "could not be found")
        if command == "find-generic-password":
            return subprocess.CompletedProcess(args, 0, self.items[account] + "\n", "")
        assert command == "delete-generic-password"
        del self.items[account]
        return subprocess.CompletedProcess(args, 0, "", "")


class FakeKeyring:
    """keyring's backend over a dict of items by (service, account), standing in for Windows
    Credential Manager and the Secret Service, so no test touches either."""

    def __init__(self):
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        del self.items[(service, username)]  # keyring raises an error of its own when it isn't


@pytest.fixture(autouse=True)
def fake_keychain(monkeypatch):
    fake = FakeSecurity()
    monkeypatch.setattr("proxenos.keychain._security", fake)
    monkeypatch.setattr("proxenos.keychain.available", lambda: True)
    return fake


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr("proxenos.keychain._keyring", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch, tmp_path_factory):
    monkeypatch.setattr("proxenos.config.load_dotenv", lambda *args, **kwargs: False)
    # Each test starts with nothing loaded, no settings file and no .env until it writes one.
    app = tmp_path_factory.mktemp("app")
    monkeypatch.setattr("proxenos.config.SETTINGS_FILE", app / "Proxenos" / "settings.json")
    monkeypatch.setattr("proxenos.config.ENV_FILE", app / "repo" / ".env")
    monkeypatch.setattr("proxenos.config._loaded", False)
    monkeypatch.setattr("proxenos.config._origin", {})
    # The repo's data/ folder holds real downloads; tests only ever see their own inbox.
    monkeypatch.setattr("proxenos.importer.inboxes", lambda vault: [vault / "inbox"])

    # Nor the embedding model on this computer: a test that needs one brings a fake.
    def no_model(texts):
        raise RuntimeError("no embedding model in tests")

    monkeypatch.setattr("proxenos.vectors._ollama", no_model)
    # Nor Ollama itself, which setup asks for its models.
    monkeypatch.setattr("proxenos.setup._ollama_models", lambda: None)
    # Nor an Ask running on this computer, which a local model call would wait out.
    monkeypatch.setattr("proxenos.llm.waiting", lambda vault=None: False)
    for name in list(os.environ):
        if name.startswith(_SECRET_PREFIXES):
            monkeypatch.delenv(name)
    # Loading and saving set variables directly; none of them outlives the test.
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)
