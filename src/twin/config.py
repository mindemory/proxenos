"""Where the vault lives. It must stay outside this repo, which is public."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


def vault_path() -> Path:
    load_dotenv(REPO_ROOT / ".env")
    vault = Path(os.environ.get("TWIN_VAULT", "~/twin_vault")).expanduser().resolve()
    if vault.is_relative_to(REPO_ROOT):
        raise ValueError(f"TWIN_VAULT ({vault}) is inside the public repo; put it elsewhere")
    return vault
