"""`proxenos setup`: the page's first-run setup and its Settings, as JSON in and out.

`proxenos setup` prints where things stand: your name, the vault, the model, the folders read on
every sync, the models on this computer (Ollama's, and those of an OpenAI-compatible server at
PROXENOS_LOCAL_URL, such as LM Studio's) with which fit its memory (proxenos.machine), which
secure store keeps secrets here, and which secrets are set and where each comes from. Never a
secret's value: only whether it's set.

`proxenos setup --apply` takes one change as JSON on stdin and prints {"ok", "message" or
"error", "status"}:
- {"settings": {"name": ..., "vault": ..., "docs_dirs": ...}} saves those settings; "" removes
  one. The vault folder is made if it isn't there, and has to be outside this repo. A voice model
  (for reply drafts, see proxenos.voicemodel) is "mlx", "mlx:<port>", "ollama:<name>" or
  "local:<name>". A fast model for the light jobs (proxenos.fastmodel) is "ollama:<name>",
  "local:<name>" or "off". The local server's address ("local_url") has to be this computer's own.
  SearXNG's ("searxng_url"), for looking people up (proxenos.lookup), is any web address, and
  "lookup" is on or off.
- {"key": "sk-ant-..."} checks an Anthropic API key with one small call (it asks for the model
  it would use) and saves it. With "provider": "openai" or "gemini" it's that provider's key
  (OPENAI_API_KEY, GEMINI_API_KEY): checked by listing the provider's models (proxenos.hosted;
  no tokens), saved, and the ask model set to one of them (the one suggested, unless one of
  that provider's is chosen already); the answer carries "models" ({provider, names, suggested,
  chosen}) for the page to pick another from. With no model on this computer and no Anthropic
  key, it's the main model too. {"models": "openai"} lists a saved key's models again, and
  {"hosted_model": "openai:<name>"} chooses another of them. What goes to them is treated as
  what goes to Claude. Claude then answers what the user waits on (the ask model, set to
  Claude unless one is set already); the model for the rest stays as it was, a local one theirs.
  With no model set, one Ollama has on this computer is used first (llm.default).
- {"ollama": "gemma4:26b"} checks that Ollama is running and has that model, and uses it.
  (`proxenos model pull` downloads one, and does this on its own when it's done.)
- {"server": "qwen3-8b"} checks that the server at PROXENOS_LOCAL_URL serves that model, and
  uses it, as "local:qwen3-8b".
- {"fast": "auto"} sets the fast model to the one `proxenos model serve-fast` serves, when this
  is an Apple-silicon Mac with mlx-lm and that model downloaded; {"fast": "off"} keeps it unset.
  The first model, key or name saved here does the same on its own when it's unset and found.
- {"google_client": {"client_id": ..., "client_secret": ...}} saves the Google sign-in client a
  person loaded from the file Google gave them (the page reads it in the browser), as the two
  secrets GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET. One the app ships is used only without it.
- {"secret": NAME, "value": ...} replaces a secret; {"forget": NAME} removes one.
Secrets come in on stdin, never as arguments, and never go back out.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import anthropic

from proxenos import config, fastmodel, hosted, keychain, llm, machine, notify

# What the page can change, by its key in the settings file, and how many folders each takes.
SETTINGS = {
    "name": "NAME",
    "vault": "VAULT",
    "model": "MODEL",
    "ask_model": "ASK_MODEL",
    "review_model": "REVIEW_MODEL",
    "local_url": "LOCAL_URL",
    "voice_model": "VOICE_MODEL",
    "fast_model": "FAST_MODEL",
    "docs_dirs": "DOCS_DIRS",
    "website_repo": "WEBSITE_REPO",
    "spotify_export": "SPOTIFY_EXPORT",
    "slackdump_dir": "SLACKDUMP_DIR",
    "cv_dirs": "CV_DIRS",
    "project_folder": "PROJECT_FOLDER",
    "ntfy_server": "NTFY_SERVER",
    "quiet_hours": "QUIET_HOURS",
    "notice_kinds": "NOTICE_KINDS",
    "searxng_url": "SEARXNG_URL",
    "lookup": "LOOKUP",
}
FOLDER_LISTS = ("docs_dirs", "cv_dirs")
FOLDERS = ("website_repo", "spotify_export", "slackdump_dir", "project_folder", *FOLDER_LISTS)
# Shown whether they're set or not; mail and calendar sign-ins and Slack workspaces only once
# they are.
SECRETS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "BEEPER_ACCESS_TOKEN",
    "STRAVA_REFRESH_TOKEN",
    "STRAVA_CLIENT_ID",
    "STRAVA_CLIENT_SECRET",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_REFRESH_TOKEN",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "MICROSOFT_CLIENT_ID",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "NTFY_TOPIC",
    "NTFY_TOKEN",
    "BRAVE_SEARCH_KEY",
)
# A model's name: LM Studio's may name a quantization after an @ (qwen3-8b@q4_k_m).
_MODEL = re.compile(r"[\w.:/@+-]{1,200}")
_VOICE = re.compile(r"mlx(:\d{1,5})?|(ollama|local):[\w.:/@+-]{1,200}")
_FAST = re.compile(r"off|(ollama|local):[\w.:/@+-]{1,200}")
_KEY = re.compile(r"sk-ant-[\w-]{10,500}")
_HOSTED_KEYS = {
    "openai": re.compile(r"sk-(?!ant-)[\w-]{10,500}"),
    "gemini": re.compile(r"AIza[\w-]{20,100}"),
}
_MAX_NAME = 100
_KEY_CHECK_SECONDS = 20


def status() -> dict:
    home = Path.home()
    vault = Path(config.env("VAULT", config.DEFAULT_VAULT)).expanduser().resolve()
    model = config.env("MODEL") or llm.default()
    held = config.secrets()
    if model.startswith(llm.LOCAL):
        kind, name = "local", llm.bare(model)
        via = "ollama" if model.startswith(llm.OLLAMA) else "server"
    else:
        host = llm.chat_host(model)
        kind, name, via = (
            ("api" if (host[2] if host else "ANTHROPIC_API_KEY") in held else "none"),
            llm.bare(model),
            None,
        )
    memory = machine.memory()
    # The model to pull when there's none yet, unless it's known not to fit.
    get = None if machine.fits(machine.SUGGESTED_BYTES, memory) is False else machine.SUGGESTED
    starter = None if machine.fits(machine.STARTER_BYTES, memory) is False else machine.STARTER
    pulled = _chat_models(_ollama_models())
    served = _chat_models(_server_models())
    try:
        url, refused = llm.local_url(), None
    except llm.ModelError as e:
        url, refused = config.env("LOCAL_URL"), str(e)
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
        "model": {"kind": kind, "name": name, "via": via, "provider": _provider(model)},
        "computer": {
            "memory": memory,
            "advice": machine.advice(memory),
            "rule": machine.RULE,
            "get": get,
            "starter": starter,
            "upgrade": _upgrade(kind, via, name, pulled, memory),
        },
        "ollama": _listed(pulled, memory),
        "server": {
            **_listed(served, memory),
            "url": url,
            "error": refused,
            "context": llm.LOCAL_CONTEXT,  # what to load a model with there
        },
        "fast": _fast(),
        "keychain": keychain.available(),
        "secret_store": keychain.store(),
        "secrets": secrets(),
    }


def _provider(model: str) -> str | None:
    """Who answers for a model that isn't on this computer: anthropic, openai or gemini."""
    if model.startswith(llm.LOCAL):
        return None
    return {llm.OPENAI: "openai", llm.GEMINI: "gemini"}.get(
        next((p for p in llm.CHAT_HOSTS if model.startswith(p)), ""), "anthropic"
    )


def _upgrade(
    kind: str, via: str | None, name: str, pulled: dict[str, int | None] | None, memory: int | None
) -> str | None:
    """The suggested model's name when the page can offer it in the background: the main model is
    a smaller one of Ollama's, the suggested one fits this computer, and Ollama hasn't pulled it."""
    if kind != "local" or via != "ollama" or pulled is None:
        return None
    size = pulled.get(name) or pulled.get(f"{name}:latest")
    if (
        not size
        or size >= machine.SUGGESTED_BYTES
        or machine.fits(machine.SUGGESTED_BYTES, memory) is not True
    ):
        return None
    return None if machine.SUGGESTED in pulled else machine.SUGGESTED


def _fast() -> dict:
    """The fast model for light jobs: the one set (or None), whether this Mac has mlx-lm and
    the model it would serve (`proxenos model serve-fast`), whether that server answers, and the
    name setup would set."""
    model = config.env("FAST_MODEL").strip()
    on = model.startswith(llm.SERVER)
    return {
        "model": model or None,
        "found": fastmodel.found(),
        "running": fastmodel.running() if on else False,
        "suggested": fastmodel.NAME,
    }


def secrets() -> list[dict]:
    """Each secret: whether it's set and where it comes from, by name. Never its value."""
    held = config.secrets()
    return [
        {"name": n, "set": n in held, "from": config.origin(n) if n in held else None}
        for n in [*SECRETS, *(n for n in held if n not in SECRETS)]
    ]


def needed() -> bool:
    """Whether this is a first run: no name and no vault set anywhere."""
    return not config.env("NAME").strip() and not config.env("VAULT").strip()


def apply(request: object) -> dict:
    """Make one change (see the module's notes) and say how it went, with the new status."""
    extra: dict = {}  # what a change adds to its answer: a hosted provider's models
    try:
        message = _apply(request, extra)
    except (ValueError, keychain.KeychainError) as e:
        return {"ok": False, "error": str(e), "status": status()}
    except SystemExit as e:
        return {"ok": False, "error": str(e.code), "status": status()}
    if _first_run_step(request):
        message += _adopt_fast()
    return {"ok": True, "message": message, "status": status(), **extra}


def _first_run_step(request: object) -> bool:
    """Whether a change is one of setup's: a name, a model, or a key."""
    if not isinstance(request, dict):
        return False
    settings = request.get("settings")
    return bool({"key", "ollama", "server"} & request.keys()) or (
        isinstance(settings, dict) and "name" in settings
    )


def _adopt_fast() -> str:
    """Set the fast model when none is set and this Mac has mlx-lm and its model; what to add
    to the message, if anything. "off" is a choice too, so it stays."""
    if config.env("FAST_MODEL").strip() or not fastmodel.found():
        return ""
    config.save_setting("FAST_MODEL", fastmodel.NAME)
    return (
        " This Mac has the fast model, so light jobs (the task list, the network) use it: "
        "run `proxenos model serve-fast` to serve it, or scripts/install-fast-model.sh to keep it "
        "running."
    )


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


def _apply(request: object, extra: dict) -> str:
    if not isinstance(request, dict):
        request = {}  # nothing in it to change
    if isinstance(request.get("settings"), dict):
        return _save_settings(request["settings"])
    if "key" in request:
        provider = str(request.get("provider") or "anthropic")
        if provider != "anthropic":
            return _save_hosted_key(provider, str(request["key"]).strip(), extra)
        return _save_key(str(request["key"]).strip())
    if "models" in request:
        return _list_hosted(str(request["models"]), extra)
    if "hosted_model" in request:
        return _use_hosted(str(request["hosted_model"]).strip(), extra)
    if "fast" in request:
        return _use_fast(str(request["fast"]).strip())
    if "ollama" in request:
        return _use_ollama(str(request["ollama"]).strip())
    if "server" in request:
        return _use_server(str(request["server"]).strip())
    if "google_client" in request:
        return _save_google_client(request["google_client"])
    if "secret" in request:
        name, value = str(request["secret"]), str(request.get("value", "")).strip()
        if name == "ANTHROPIC_API_KEY":
            return _save_key(value)
        if name in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
            return _save_hosted_key(name.split("_")[0].lower(), value, extra)
        _known_secret(name)
        if not value or len(value) > 4096 or any(c in value for c in "\r\n\0"):
            raise ValueError("Paste the new value on one line.")
        if name == "NTFY_TOPIC" and not notify.TOPIC.fullmatch(value):
            raise ValueError("A topic has only letters, digits, - and _, up to 64 of them.")
        if name == "NTFY_TOPIC" and len(value) < notify.MIN_TOPIC:
            raise ValueError(
                f"Make the topic at least {notify.MIN_TOPIC} random characters: anyone who "
                "knows it can read your notices. Settings' Make one gives you one."
            )
        return f"Saved {name} in {config.save_secret(name, value)}."
    if "forget" in request:
        name = str(request["forget"])
        _known_secret(name)
        removed = config.forget_secret(name)
        if config.origin(name) == "environment":
            return f"{name} comes from the environment Proxenos was started with; remove it there."
        return f"Removed {name}." if removed else f"{name} wasn't saved anywhere Proxenos keeps it."
    raise ValueError("Nothing to change.")


def _save_google_client(client: object) -> str:
    """Save a Google OAuth client's ID and secret, both or neither."""
    pair = (
        [client.get("client_id"), client.get("client_secret")] if isinstance(client, dict) else []
    )
    if len(pair) != 2 or not all(isinstance(v, str) and v.strip() for v in pair):
        raise ValueError("That isn't a Google client: it needs a client ID and a client secret.")
    client_id, client_secret = (v.strip() for v in pair)
    if any(len(v) > 512 or not v.isprintable() for v in (client_id, client_secret)):
        raise ValueError("The client's ID and secret each have to be one short line.")
    where = config.save_secret("GOOGLE_CLIENT_ID", client_id)
    config.save_secret("GOOGLE_CLIENT_SECRET", client_secret)
    return f"Saved the Google sign-in client in {where}."


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
    for key in ("model", "ask_model", "review_model"):
        if values.get(key) and not _MODEL.fullmatch(values[key]):
            raise ValueError("That isn't a model's name.")
    if values.get("voice_model") and not _VOICE.fullmatch(values["voice_model"]):
        raise ValueError(
            "A voice model is mlx (as `proxenos voice serve` runs it), ollama:<name> or "
            "local:<name>."
        )
    if values.get("fast_model") and not _FAST.fullmatch(values["fast_model"]):
        raise ValueError("A fast model is ollama:<name> or local:<name>, on this computer, or off.")
    if values.get("ntfy_server"):
        try:
            values["ntfy_server"] = notify.server_address(values["ntfy_server"])
        except notify.Failed:
            raise ValueError(f"The ntfy server is a web address, like {notify.SERVER}.") from None
    if values.get("quiet_hours"):
        try:
            notify.parse_quiet(values["quiet_hours"])
        except ValueError:
            raise ValueError("Give quiet hours as 22:00-08:00, or off.") from None
    if values.get("local_url"):
        try:
            values["local_url"] = llm.local_url(values["local_url"])
        except llm.ModelError as e:
            raise ValueError(str(e)) from None
    if values.get("searxng_url"):
        parts = urllib.parse.urlsplit(values["searxng_url"])
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("SearXNG's address is a web address, like http://127.0.0.1:8888.")
        values["searxng_url"] = values["searxng_url"].rstrip("/")
    if values.get("lookup") and values["lookup"].casefold() not in ("on", "off"):
        raise ValueError("Looking people up is on or off.")
    if values.get("notice_kinds") and values["notice_kinds"].casefold() not in ("on", "off"):
        raise ValueError("Saying what kinds wait in a notice is on or off.")
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
    """Check the key and keep it. Claude then takes what the user waits on (Ask, Think, errands,
    calls): the ask model, set to Claude unless they chose one already. The rest stays where it
    was, on the model on this computer when there is one; only with none does Claude take all."""
    if not _KEY.fullmatch(key):
        raise ValueError("That isn't an Anthropic API key: they start with sk-ant-.")
    ask = config.env("ASK_MODEL")
    model = ask if ask and not ask.startswith(llm.LOCAL) else llm.DEFAULT_MODEL
    problem = _check_key(key, model)
    if problem:
        raise ValueError(problem)
    where = config.save_secret("ANTHROPIC_API_KEY", key)
    if not ask:
        config.save_setting("ASK_MODEL", model)
    rest = config.env("MODEL") or llm.default()
    if rest.startswith(llm.LOCAL):
        return (
            f"The key works with {model}. Saved in {where}. {model} answers what you wait on "
            f"(Ask, Think, errands, calls); the rest stays on {llm.bare(rest)}, on this computer."
        )
    return f"The key works with {model}. Saved in {where}. With no model on this computer, it answers everything."


def _save_hosted_key(provider: str, key: str, extra: dict) -> str:
    """Check an OpenAI or Gemini key by listing the provider's models, keep it, and make the ask
    model one of them (what the user waits on goes there, as Claude's key does for Anthropic);
    with no model on this computer and no Anthropic key, it takes the rest too."""
    lead = hosted.prefix(provider)
    label, _, secret = llm.CHAT_HOSTS[lead]
    if key.startswith("sk-ant-"):
        raise ValueError("That's an Anthropic key. Choose Anthropic for it.")
    if not _HOSTED_KEYS[provider].fullmatch(key):
        start = "sk-" if provider == "openai" else "AIza"
        raise ValueError(f"That isn't {label}'s API key: they start with {start}.")
    names = hosted.list_models(provider, key)
    suggested = hosted.suggest(provider, names)
    if not suggested:
        raise ValueError(f"The key works, but it can't use any of {label}'s chat models.")
    where = config.save_secret(secret, key)
    ask = config.env("ASK_MODEL")
    chosen = ask.removeprefix(lead) if ask.startswith(lead) else ""
    chosen = chosen if chosen in names else suggested
    config.save_setting("ASK_MODEL", lead + chosen)
    rest = config.env("MODEL") or llm.default()
    if not rest.startswith(llm.LOCAL) and "ANTHROPIC_API_KEY" not in config.secrets():
        config.save_setting("MODEL", lead + chosen)
        rest = lead + chosen
    extra["models"] = {
        "provider": provider,
        "names": names,
        "suggested": suggested,
        "chosen": chosen,
    }
    said = f"The key works with {label}. Saved in {where}. {chosen} answers what you wait on"
    if rest.startswith(llm.LOCAL):
        return (
            f"{said} (Ask, Think, errands, calls); the rest stays on {llm.bare(rest)}, on this "
            "computer."
        )
    return f"{said}, and everything else."


def _hosted_key(provider: str) -> tuple[str, str]:
    """(model-name prefix, the saved key) of a provider, or ValueError when none is saved."""
    lead = hosted.prefix(provider)
    label, _, secret = llm.CHAT_HOSTS[lead]
    key = os.environ.get(secret, "")
    if not key:
        raise ValueError(f"No {label} key is saved yet.")
    return lead, key


def _list_hosted(provider: str, extra: dict) -> str:
    """List the models a saved key can use, for the page to pick from."""
    lead, key = _hosted_key(provider)
    names = hosted.list_models(provider, key)
    ask = config.env("ASK_MODEL")
    chosen = ask.removeprefix(lead) if ask.startswith(lead) else None
    suggested = hosted.suggest(provider, names)
    extra["models"] = {
        "provider": provider,
        "names": names,
        "suggested": suggested,
        "chosen": chosen,
    }
    return f"{len(names)} models."


def _use_hosted(model: str, extra: dict) -> str:
    """Choose another model of a provider whose key is saved for what the user waits on, and for
    the rest too when that was already the provider's."""
    provider = next((p for p in ("openai", "gemini") if model.startswith(f"{p}:")), None)
    if provider is None:
        raise ValueError("Name a model as openai:<name> or gemini:<name>.")
    lead, key = _hosted_key(provider)
    names = hosted.list_models(provider, key)
    name = model.removeprefix(lead)
    if name not in names:
        raise ValueError(f"{llm.CHAT_HOSTS[lead][0]} doesn't list {name} for this key.")
    config.save_setting("ASK_MODEL", model)
    if config.env("MODEL").startswith(lead):
        config.save_setting("MODEL", model)
    extra["models"] = {
        "provider": provider,
        "names": names,
        "suggested": hosted.suggest(provider, names),
        "chosen": name,
    }
    return f"{name} answers what you wait on."


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


def _use_fast(how: str) -> str:
    """Set the fast model to the one `proxenos model serve-fast` serves, or off."""
    if how == "off":
        where = config.save_setting("FAST_MODEL", "off")
        return f"Light jobs use the main model. Saved in {_place(where)}."
    if how != "auto":
        raise ValueError("Say auto or off.")
    if not fastmodel.capable():
        raise ValueError(
            "The fast model needs a Mac with Apple silicon and mlx-lm (pip install mlx-lm); "
            f"it serves {fastmodel.BASE}, which it downloads on its first run."
        )
    where = config.save_setting("FAST_MODEL", fastmodel.NAME)
    return (
        f"Light jobs use {fastmodel.BASE}. Saved in {_place(where)}. "
        "Serve it with proxenos model serve-fast."
    )


def _use_ollama(model: str) -> str:
    model = model.removeprefix(llm.OLLAMA)
    if not _MODEL.fullmatch(model):
        raise ValueError("Name a model, e.g. gemma4:26b.")
    pulled = _ollama_models()
    if pulled is None:
        raise ValueError("Ollama isn't running. Open the Ollama app (ollama.com), then try again.")
    if model not in pulled and f"{model}:latest" not in pulled:
        raise ValueError(f"Ollama doesn't have {model} yet. Download it first.")
    where = config.save_setting("MODEL", llm.OLLAMA + model)
    return f"Using {model} on this computer, through Ollama. Saved in {_place(where)}."


def _use_server(model: str) -> str:
    model = model.removeprefix(llm.SERVER)
    if not _MODEL.fullmatch(model):
        raise ValueError("Name a model the server lists.")
    try:
        url = llm.local_url()
    except llm.ModelError as e:
        raise ValueError(str(e)) from None
    served = _server_models()
    if served is None:
        raise ValueError(
            f"Nothing answers at {url}. Start the server (in LM Studio, its Developer tab), "
            "then try again."
        )
    if model not in served:
        raise ValueError(f"The server at {url} doesn't have {model}. Load it there first.")
    where = config.save_setting("MODEL", llm.SERVER + model)
    return f"Using {model} on this computer, through the server at {url}. Saved in {_place(where)}."


def _ollama_models() -> dict[str, int | None] | None:
    """The models Ollama has pulled, with each one's size in bytes, or None when it isn't
    running."""
    try:
        with urllib.request.urlopen(f"{llm._OLLAMA}/api/tags", timeout=2) as response:
            listed = json.load(response).get("models", [])
        return {str(m["name"]): _size(m.get("size")) for m in listed}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _server_models() -> dict[str, int | None] | None:
    """The models the OpenAI-compatible server at PROXENOS_LOCAL_URL serves (its /models), with
    each one's size where the server says (llama-server does, in `meta`), or None when nothing
    answers there or the address isn't this computer's own."""
    try:
        with llm._direct(f"{llm.local_url()}/models", timeout=2) as response:
            listed = json.load(response).get("data", [])
        return {
            str(m["id"]): _size(m.get("size") or (m.get("meta") or {}).get("size")) for m in listed
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, llm.ModelError):
        return None


def _size(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _chat_models(models: dict[str, int | None] | None) -> dict[str, int | None] | None:
    """The models that can write, not the ones that only embed text for search."""
    if models is None:
        return None
    return {name: size for name, size in models.items() if "embed" not in name}


def _listed(models: dict[str, int | None] | None, memory: int | None) -> dict:
    """A server's models as the page lists them: whether it answers, each model with its size
    and whether it fits this computer, and the one to suggest."""
    return {
        "running": models is not None,
        "models": machine.marked(models or {}, memory),
        "suggested": machine.best(models or {}, memory),
    }


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
