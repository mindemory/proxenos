"""Where the vault lives, and the settings and secrets Proxenos runs with.

A setting is PROXENOS_<NAME> (the project's earlier TWIN_<NAME> still counts when the new one
isn't set, so an .env that hasn't been migrated keeps working). A secret goes by its own name:
ANTHROPIC_API_KEY, GMAIL_<NAME>, SLACK_USER_TOKEN_<workspace>, ... Each is read from the first
of these that has it:

1. the process's environment;
2. the repo's .env, when running from source;
3. the settings file, ~/Library/Application Support/Proxenos/settings.json, which the page's
   setup and Settings write: {"name": ..., "vault": ..., "model": ...} for PROXENOS_NAME and the
   rest, and under "keychain" the names of the secrets kept in the Keychain;
4. the macOS Keychain, one item per secret (keychain.py).

`load` puts what 2 to 4 hold into the environment once per process, never over a variable that's
already there, so every reader sees the same order. Changes go where they'd be read first: into
.env when running from source with one, else into the settings file or the Keychain.

The vault must stay outside this repo, which is public.
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from proxenos import keychain

REPO_ROOT = Path(__file__).resolve().parents[2]
# A checkout (an editable install too) has the project file; an installed package doesn't.
FROM_SOURCE = (REPO_ROOT / "pyproject.toml").is_file()
ENV_FILE: Path | None = REPO_ROOT / ".env" if FROM_SOURCE else None
SETTINGS_FILE = Path.home() / "Library" / "Application Support" / "Proxenos" / "settings.json"
PREFIX = "PROXENOS_"
OLD_PREFIX = "TWIN_"
DEFAULT_VAULT = "~/proxenos_vault"
KEYCHAIN = "keychain"  # the settings file's list of the secrets in the Keychain
# The secrets: a model key, sign-ins' tokens, and the apps you sign in through.
SECRET = re.compile(
    r"ANTHROPIC_API_KEY|BEEPER_ACCESS_TOKEN|GMAIL_[A-Z0-9_]+|SLACK_USER_TOKEN(_\w+)?"
    r"|STRAVA_(CLIENT_ID|CLIENT_SECRET|REFRESH_TOKEN)|GOOGLE_CLIENT_(ID|SECRET)"
)
_MAX_VALUE = 4096

_loaded = False
# Where `load` and the savers found or put each variable: ".env", "settings" or "keychain".
# A variable that's set and isn't here came with the process's environment.
_origin: dict[str, str] = {}


def env_key(name: str) -> str:
    """The variable that holds setting `name`: PROXENOS_<name>, unless only TWIN_<name> is set."""
    load()
    if PREFIX + name not in os.environ and OLD_PREFIX + name in os.environ:
        return OLD_PREFIX + name
    return PREFIX + name


def env(name: str, default: str = "") -> str:
    """Setting `name` (VAULT, NAME, EMAILS, ...): PROXENOS_<name>, else TWIN_<name>, else default."""
    return os.environ.get(env_key(name), default)


def vault_path() -> Path:
    vault = Path(env("VAULT", DEFAULT_VAULT)).expanduser().resolve()
    if vault.is_relative_to(REPO_ROOT):
        raise ValueError(
            f"{env_key('VAULT')} ({vault}) is inside the public repo; put it elsewhere"
        )
    return vault


def load() -> None:
    """Fill the environment from .env (from source), then the settings file, then the Keychain,
    never over a variable that's already set. Once per process; the savers below keep it current
    after that."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    if ENV_FILE is not None:
        before = set(os.environ)
        load_dotenv(ENV_FILE)
        _origin.update(dict.fromkeys(set(os.environ) - before, ".env"))
    settings = read_settings()
    for key, value in settings.items():
        name = key.upper()
        if key != KEYCHAIN and isinstance(value, str) and not _setting_set(name):
            os.environ[PREFIX + name] = value
            _origin[PREFIX + name] = "settings"
    wanted = [name for name in _in_keychain(settings) if name not in os.environ]
    if wanted and keychain.available():
        for name in wanted:
            try:
                value = keychain.get(name)
            except keychain.KeychainError as e:
                print(f"proxenos: {e}", file=sys.stderr)
                continue
            if value:
                os.environ[name] = value
                _origin[name] = "keychain"


def origin(variable: str) -> str | None:
    """Where a variable's value comes from: "environment", ".env", "settings" or "keychain"; None
    when it isn't set."""
    load()
    if variable not in os.environ:
        return None
    return _origin.get(variable, "environment")


def read_settings() -> dict:
    """The settings file, or {} when there's none or it can't be read."""
    try:
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def saves_to() -> str:
    """Where a change is saved: ".env" from source with one, else "settings" (and the Keychain)."""
    return ".env" if ENV_FILE is not None and ENV_FILE.exists() else "settings"


def save_setting(name: str, value: str) -> str:
    """Save setting `name` (NAME, VAULT, MODEL, ...), or with "" remove it: in .env when running
    from source with one, else in the settings file. Says which."""
    _check_value(name, value, allow_empty=True)
    load()
    where = saves_to()
    if where == ".env":
        assert ENV_FILE is not None
        _set_line(ENV_FILE, PREFIX + name, value)
        if not value:
            _set_line(ENV_FILE, OLD_PREFIX + name, "")
    else:
        settings = read_settings()
        if value:
            settings[name.lower()] = value
        else:
            settings.pop(name.lower(), None)
        _write_settings(settings)
    _set_variable(PREFIX + name, value, where)
    if not value:
        _set_variable(OLD_PREFIX + name, "", where)
    return where


def save_secret(name: str, value: str) -> str:
    """Save a secret: in .env when running from source with one (or with no Keychain to use),
    else in the Keychain, with its name added to the settings file's list. Says where."""
    if not SECRET.fullmatch(name):
        raise ValueError(f"{name} isn't one of Proxenos's secrets")
    _check_value(name, value)
    load()
    if ENV_FILE is not None and (ENV_FILE.exists() or not keychain.available()):
        _set_line(ENV_FILE, name, value)
        where = ".env"
    elif keychain.available():
        keychain.put(name, value)
        settings = read_settings()
        settings[KEYCHAIN] = sorted({*_in_keychain(settings), name})
        _write_settings(settings)
        where = "keychain"
    else:
        raise SystemExit(f"There's no Keychain here to keep {name} in; put it in .env instead.")
    _set_variable(name, value, where)
    return ".env" if where == ".env" else "the Keychain"


def forget_secret(name: str) -> bool:
    """Remove a secret from .env and the Keychain, wherever Proxenos keeps it. Whether it was in
    either. One from the process's environment stays until that changes."""
    if not SECRET.fullmatch(name):
        raise ValueError(f"{name} isn't one of Proxenos's secrets")
    load()
    removed = False
    if ENV_FILE is not None and ENV_FILE.exists():
        removed = _set_line(ENV_FILE, name, "")
    settings = read_settings()
    listed = _in_keychain(settings)
    if name in listed:
        removed = (keychain.available() and keychain.delete(name)) or removed
        settings[KEYCHAIN] = [n for n in listed if n != name]
        _write_settings(settings)
    if origin(name) != "environment":
        _set_variable(name, "", None)
    return removed


def secrets() -> list[str]:
    """The names of the secrets that are set, from anywhere."""
    load()
    return sorted(name for name in os.environ if SECRET.fullmatch(name) and os.environ[name])


def _setting_set(name: str) -> bool:
    return PREFIX + name in os.environ or OLD_PREFIX + name in os.environ


def _in_keychain(settings: dict) -> list[str]:
    names = settings.get(KEYCHAIN)
    if not isinstance(names, list):
        return []
    return [n for n in names if isinstance(n, str) and SECRET.fullmatch(n)]


def _check_value(name: str, value: str, allow_empty: bool = False) -> None:
    if not value and not allow_empty:
        raise ValueError(f"nothing to save as {name}")
    if len(value) > _MAX_VALUE or any(c in value for c in "\r\n\0"):
        raise ValueError(f"{name} has to be one line")


def _set_variable(variable: str, value: str, where: str | None) -> None:
    if value:
        os.environ[variable] = value
    else:
        os.environ.pop(variable, None)
    if value and where is not None:
        _origin[variable] = where
    else:
        _origin.pop(variable, None)


def _set_line(path: Path, name: str, value: str) -> bool:
    """Set one variable in a dotenv file, keeping every other line, or with "" remove its line.
    The file stays private to you. Whether its line was there."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    found = [i for i, line in enumerate(lines) if line.startswith(f"{name}=")]
    if value:
        entry = f"{name}={_quoted(value)}"
        if found:
            lines[found[0]] = entry
        else:
            lines.append(entry)
    elif found:
        lines = [line for i, line in enumerate(lines) if i not in found]
    else:
        return False
    _write_private(path, "\n".join(lines) + "\n" if lines else "")
    return bool(found)


def _quoted(value: str) -> str:
    """A value as a dotenv line keeps it: bare, unless a # or edge spaces or quotes would change
    it, then in single quotes (which nothing inside is read from)."""
    if "#" not in value and value == value.strip() and value[0] not in "\"'":
        return value
    return f"'{value}'" if "'" not in value else value


def _write_settings(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_private(SETTINGS_FILE, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    tmp.chmod(0o600)
    os.replace(tmp, path)
