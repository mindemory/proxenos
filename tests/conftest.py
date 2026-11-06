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
    "BRAVE_",
    "GCALENDAR_",
    "GDOCS_",
    "GMAIL_",
    "GOOGLE_CLIENT_",
    "MICROSOFT_",
    "NTFY_",
    "SLACK_USER_TOKEN",
    "STRAVA_",
    "TWILIO_",
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
    # The Mac's store on every platform, unless a test pins another (tests/test_keychain.py).
    monkeypatch.setattr("proxenos.keychain._platform", lambda: "darwin")
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
    # Nor Alexandria's vault, whose picks and reactions the feed reads when it's on this computer.
    monkeypatch.setenv("ALEXANDRIA_HOME", str(app / "no-alexandria"))
    # The repo's data/ folder holds real downloads; tests only ever see their own inbox.
    monkeypatch.setattr("proxenos.importer.inboxes", lambda vault: [vault / "inbox"])

    # Nor the embedding model on this computer: a test that needs one brings a fake.
    def no_model(texts):
        raise RuntimeError("no embedding model in tests")

    monkeypatch.setattr("proxenos.vectors._ollama", no_model)
    # Nor Ollama itself, nor another model server on this computer, which setup asks for models.
    monkeypatch.setattr("proxenos.setup._ollama_models", lambda: None)
    monkeypatch.setattr("proxenos.setup._server_models", lambda: None)
    # Nor, with no model set, the one Ollama has, which llm would go to first.
    monkeypatch.setattr("proxenos.llm._pulled", lambda: None)
    monkeypatch.setattr("proxenos.llm._default", None)
    # Nor the real ~/Library, which Connect tries to see whether Full Disk Access is on.
    monkeypatch.setattr("proxenos.connect.full_disk_access", lambda *args, **kwargs: None)
    # Nor the real Hugging Face cache, which setup asks about the models Proxenos can run itself.
    monkeypatch.setenv("HF_HUB_CACHE", str(app / "huggingface"))
    # Nor an MLX fast model on this computer, or its server: a test that needs one says so.
    monkeypatch.setattr("proxenos.fastmodel.found", lambda *args, **kwargs: False)
    monkeypatch.setattr("proxenos.fastmodel.capable", lambda *args, **kwargs: False)
    monkeypatch.setattr("proxenos.fastmodel.running", lambda url=None: False)
    # Nor an Ask running on this computer, which a local model call would wait out.
    monkeypatch.setattr("proxenos.llm.waiting", lambda vault=None: False)
    # Nor the real vault's log of model calls: a test that checks the log points it elsewhere.
    monkeypatch.setattr("proxenos.llm._calls_path", lambda: None)

    # Nor MusicBrainz, which the night asks for artists' genres: a test that needs it fakes it.
    def no_network(request):
        raise OSError("no MusicBrainz in tests")

    monkeypatch.setattr("proxenos.musicbrainz._fetch", no_network)

    # Nor a search engine or anyone's web pages, which a lookup reads: a test brings a fake.
    def no_web(url, headers):
        raise OSError("no web lookups in tests")

    monkeypatch.setattr("proxenos.lookup._fetch", no_web)
    monkeypatch.setattr("proxenos.lookup.PACE", 0)

    # Nor Crossref, arXiv, OpenAlex or a reference's page, which a preprint's references are
    # checked against: a test brings a fake.
    def no_indexes(url):
        raise OSError("no scholarly indexes in tests")

    monkeypatch.setattr("proxenos.preprint._fetch", no_indexes)
    for name in list(os.environ):
        if name.startswith(_SECRET_PREFIXES):
            monkeypatch.delenv(name)
    # Nor the user's own vault: a test that runs the command without setting one finds none. Set
    # after the PROXENOS_ variables are cleared, or it would be cleared with them.
    monkeypatch.setenv("PROXENOS_VAULT", str(app / "no-vault"))
    # Loading and saving set variables directly; none of them outlives the test.
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)
