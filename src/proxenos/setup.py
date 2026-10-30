"""`proxenos setup`: the page's first-run setup and its Settings, as JSON in and out.

`proxenos setup` prints where things stand: your name, the vault, the model, the folders read on
every sync, whether Ollama is running and with which models, which secure store keeps secrets
here, and which secrets are set and where each comes from. Never a secret's value: only whether
it's set.

`proxenos setup --apply` takes one change as JSON on stdin and prints {"ok", "message" or
"error", "status"}:
- {"settings": {"name": ..., "vault": ..., "docs_dirs": ...}} saves those settings; "" removes
  one. The vault folder is made if it isn't there, and has to be outside this repo. A voice model
  (for reply drafts, see proxenos.voicemodel) is "mlx", "mlx:<port>" or "ollama:<name>".
- {"key": "sk-ant-..."} checks an Anthropic API key with one small call (it asks for the model
  it would use) and saves it, and the model is then Anthropic's.
- {"ollama": "gemma4:26b"} checks that Ollama is running and has that model, and uses it.
- {"secret": NAME, "value": ...} replaces a secret; {"forget": NAME} removes one.
Secrets come in on stdin, never as arguments, and never go back out.
"""

import json
import re
import urllib.request
from pathlib import Path

import anthropic

from proxenos import config, keychain, llm

# What the page can change, by its key in the settings file, and how many folders each takes.
SETTINGS = {
    "name": "NAME",
    "vault": "VAULT",
    "model": "MODEL",
    "voice_model": "VOICE_MODEL",
    "docs_dirs": "DOCS_DIRS",
    "website_repo": "WEBSITE_REPO",
    "spotify_export": "SPOTIFY_EXPORT",
    "slackdump_dir": "SLACKDUMP_DIR",
    "cv_dirs": "CV_DIRS",
}
FOLDER_LISTS = ("docs_dirs", "cv_dirs")
FOLDERS = ("website_repo", "spotify_export", "slackdump_dir", *FOLDER_LISTS)
# Shown whether they're set or not; mail and calendar sign-ins and Slack workspaces only once
# they are.
SECRETS = (
    "ANTHROPIC_API_KEY",
    "BEEPER_ACCESS_TOKEN",
    "STRAVA_REFRESH_TOKEN",
    "STRAVA_CLIENT_ID",
    "STRAVA_CLIENT_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "MICROSOFT_CLIENT_ID",
)
_MODEL = re.compile(r"[\w.:/-]{1,100}")
_VOICE = re.compile(r"mlx(:\d{1,5})?|ollama:[\w.:/-]{1,100}")
_KEY = re.compile(r"sk-ant-[\w-]{10,500}")
_MAX_NAME = 100
_KEY_CHECK_SECONDS = 20


def status() -> dict:
    home = Path.home()
    vault = Path(config.env("VAULT", config.DEFAULT_VAULT)).expanduser().resolve()
    model = config.env("MODEL", llm.DEFAULT_MODEL)
    held = config.secrets()
    if model.startswith(llm.LOCAL):
        kind, name = "local", model.removeprefix(llm.LOCAL)
    else:
        kind, name = ("api" if "ANTHROPIC_API_KEY" in held else "none"), model
    pulled = _ollama_models()
    return {
        "needed": needed(),
        "saves_to": config.saves_to(),
        "settings_file": _shown(config.SETTINGS_FILE),
        "home": str(home),
        "settings": {
            key: {
                "value": config.env(name) or None,
                "from": config.origin(config.env_key(name)),
            }
            for key, name in SETTINGS.items()
        },
        "vault": {
            "path": _shown(vault),
            "exists": vault.is_dir(),
            "cloud": cloud(vault),
        },
        "model": {"kind": kind, "name": name},
        "ollama": {"running": pulled is not None, "models": _chat_models(pulled or [])},
        "keychain": keychain.available(),
        "secret_store": keychain.store(),
        "secrets": [
            {"name": n, "set": n in held, "from": config.origin(n) if n in held else None}
            for n in [*SECRETS, *(n for n in held if n not in SECRETS)]
        ],
    }


def needed() -> bool:
    """Whether this is a first run: no name and no vault set anywhere."""
    return not config.env("NAME").strip() and not config.env("VAULT").strip()


def apply(request: object) -> dict:
    """Make one change (see the module's notes) and say how it went, with the new status."""
    try:
        message = _apply(request)
    except (ValueError, keychain.KeychainError) as e:
        return {"ok": False, "error": str(e), "status": status()}
    except SystemExit as e:
        return {"ok": False, "error": str(e.code), "status": status()}
    return {"ok": True, "message": message, "status": status()}


def cloud(path: Path) -> str | None:
    """Which cloud a folder syncs to, if it's one Macs sync by default: "icloud" for Desktop and
    Documents (with Desktop & Documents Folders on) and iCloud Drive, "drive" for the folders
    other cloud drives keep."""
    home = Path.home()
    synced = {
        home / "Desktop": "icloud",
        home / "Documents": "icloud",
        home / "Library" / "Mobile Documents": "icloud",
        home / "Library" / "CloudStorage": "drive",
    }
    for folder, where in synced.items():
        if path.is_relative_to(folder) or path.is_relative_to(folder.resolve()):
            return where
    return None


def _apply(request: object) -> str:
    if not isinstance(request, dict):
        request = {}  # nothing in it to change
    if isinstance(request.get("settings"), dict):
        return _save_settings(request["settings"])
    if "key" in request:
        return _save_key(str(request["key"]).strip())
    if "ollama" in request:
        return _use_ollama(str(request["ollama"]).strip())
    if "secret" in request:
        name, value = str(request["secret"]), str(request.get("value", "")).strip()
        if name == "ANTHROPIC_API_KEY":
            return _save_key(value)
        _known_secret(name)
        if not value or len(value) > 4096 or any(c in value for c in "\r\n\0"):
            raise ValueError("Paste the new value on one line.")
        return f"Saved {name} in {config.save_secret(name, value)}."
    if "forget" in request:
        name = str(request["forget"])
        _known_secret(name)
        removed = config.forget_secret(name)
        if config.origin(name) == "environment":
            return f"{name} comes from the environment Proxenos was started with; remove it there."
        return f"Removed {name}." if removed else f"{name} wasn't saved anywhere Proxenos keeps it."
    raise ValueError("Nothing to change.")


def _save_settings(changes: dict) -> str:
    unknown = sorted(set(changes) - set(SETTINGS))
    if unknown:
        raise ValueError(f"Not a setting: {', '.join(unknown)}.")
    values = {key: str(value or "").strip() for key, value in changes.items()}
    for key, value in values.items():
        if len(value) > 4096 or any(c in value for c in "\r\n\0"):
            raise ValueError(f"The {key.replace('_', ' ')} has to be one line.")
    if len(values.get("name", "")) > _MAX_NAME:
        raise ValueError(f"Keep the name under {_MAX_NAME} characters.")
    if values.get("model") and not _MODEL.fullmatch(values["model"]):
        raise ValueError("That isn't a model's name.")
    if values.get("voice_model") and not _VOICE.fullmatch(values["voice_model"]):
        raise ValueError(
            "A voice model is mlx (as `proxenos voice serve` runs it) or ollama:<name>."
        )
    if "vault" in values:
        values["vault"] = _make_vault(values["vault"])

    where = config.saves_to()
    for key, value in values.items():
        config.save_setting(SETTINGS[key], value)
    missing = [
        folder
        for key in FOLDERS
        for folder in _folders(values.get(key, ""), key)
        if not Path(folder).expanduser().is_dir()
    ]
    said = f"Saved in {_place(where)}." if values else "Nothing to save."
    return said + (f" Not there yet: {', '.join(missing)}." if missing else "")


def _make_vault(typed: str) -> str:
    """The vault as it's saved, once its folder is there: under your home as ~/..., else whole."""
    if not typed:
        return ""
    if not (typed.startswith(("~", "/")) or Path(typed).is_absolute()):
        raise ValueError(
            "Give the vault's whole path, starting with ~/ or / (or a drive, like C:\\)."
        )
    vault = Path(typed).expanduser().resolve()
    if vault.is_relative_to(config.REPO_ROOT):
        raise ValueError("The vault can't be inside Proxenos's own folder, which is public.")
    if vault.exists() and not vault.is_dir():
        raise ValueError(f"{_shown(vault)} is a file, not a folder.")
    try:
        vault.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"Couldn't make {_shown(vault)}: {e.strerror or e}.") from None
    return _shown(vault)


def _save_key(key: str) -> str:
    if not _KEY.fullmatch(key):
        raise ValueError("That isn't an Anthropic API key: they start with sk-ant-.")
    model = config.env("MODEL", llm.DEFAULT_MODEL)
    if model.startswith(llm.LOCAL):
        model = llm.DEFAULT_MODEL
    problem = _check_key(key, model)
    if problem:
        raise ValueError(problem)
    where = config.save_secret("ANTHROPIC_API_KEY", key)
    if config.env("MODEL").startswith(llm.LOCAL):
        config.save_setting("MODEL", "")
    return f"The key works with {model}. Saved in {where}."


def _check_key(key: str, model: str) -> str | None:
    """Ask Anthropic about the model with this key: one call, no tokens. What's wrong, or None."""
    client = anthropic.Anthropic(
        api_key=key, base_url=llm._API, max_retries=0, timeout=_KEY_CHECK_SECONDS
    )
    try:
        client.models.retrieve(model)
    except anthropic.AuthenticationError:
        return "Anthropic didn't accept that key. Copy it again from console.anthropic.com."
    except anthropic.PermissionDeniedError:
        return "That key isn't allowed to use the API. Check its workspace in the Console."
    except anthropic.NotFoundError:
        return f"The key works, but it can't use {model}."
    except anthropic.APIConnectionError:
        return "Couldn't reach Anthropic. Check the internet connection and try again."
    except anthropic.APIStatusError as e:
        return f"Anthropic answered with an error ({e.status_code}). Try again in a minute."
    return None


def _use_ollama(model: str) -> str:
    model = model.removeprefix(llm.LOCAL)
    if not _MODEL.fullmatch(model):
        raise ValueError("Name a model, e.g. gemma4:26b.")
    pulled = _ollama_models()
    if pulled is None:
        raise ValueError("Ollama isn't running. Open the Ollama app (ollama.com), then try again.")
    if model not in pulled and f"{model}:latest" not in pulled:
        raise ValueError(f"Ollama doesn't have {model} yet. Run: ollama pull {model}")
    where = config.save_setting("MODEL", llm.LOCAL + model)
    return f"Using {model} on this Mac. Saved in {_place(where)}."


def _ollama_models() -> list[str] | None:
    """The models Ollama has pulled, or None when it isn't running."""
    try:
        with urllib.request.urlopen(f"{llm._OLLAMA}/api/tags", timeout=2) as response:
            listed = json.load(response).get("models", [])
        return sorted(str(m["name"]) for m in listed)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _chat_models(names: list[str]) -> list[str]:
    """The pulled models that can write, not the ones that only embed text for search."""
    return [n for n in names if "embed" not in n]


def _known_secret(name: str) -> None:
    if not config.SECRET.fullmatch(name):
        raise ValueError(f"{name} isn't one of Proxenos's secrets.")


def _folders(value: str, key: str) -> list[str]:
    if key in FOLDER_LISTS:
        return [p.strip() for p in value.split(",") if p.strip()]
    return [value] if value else []


def _place(where: str) -> str:
    return ".env" if where == ".env" else "your settings"


def _shown(path: Path) -> str:
    """A path as ~/... (~\\... on Windows) when it's under your home folder."""
    for home in (Path.home(), Path.home().resolve()):
        if path != home and path.is_relative_to(home):
            return str(Path("~", path.relative_to(home)))
    return str(path)
