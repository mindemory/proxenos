"""Where the vault lives, and the settings read from the environment.

The vault must stay outside this repo, which is public. Settings are PROXENOS_<NAME> variables
(from the shell, or the repo's .env once `vault_path` has loaded it). The project's earlier
names, TWIN_<NAME>, are still read when the new one isn't set, so an .env that hasn't been
migrated keeps working.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFIX = "PROXENOS_"
OLD_PREFIX = "TWIN_"
DEFAULT_VAULT = "~/proxenos_vault"


def env_key(name: str) -> str:
    """The variable that holds setting `name`: PROXENOS_<name>, unless only TWIN_<name> is set."""
    if PREFIX + name not in os.environ and OLD_PREFIX + name in os.environ:
        return OLD_PREFIX + name
    return PREFIX + name


def env(name: str, default: str = "") -> str:
    """Setting `name` (VAULT, NAME, EMAILS, ...): PROXENOS_<name>, else TWIN_<name>, else default."""
    return os.environ.get(env_key(name), default)


def vault_path() -> Path:
    load_dotenv(REPO_ROOT / ".env")
    vault = Path(env("VAULT", DEFAULT_VAULT)).expanduser().resolve()
    if vault.is_relative_to(REPO_ROOT):
        raise ValueError(
            f"{env_key('VAULT')} ({vault}) is inside the public repo; put it elsewhere"
        )
    return vault
