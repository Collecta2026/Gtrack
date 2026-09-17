#!/usr/bin/env python3
"""
golive — put a Python web app online: Neon Postgres, GitHub, Render.

Drop this single file into any project folder and run it:

    python golive.py

The first run inspects the project, works out how it should be built and started,
shows you what it found, and asks you to confirm. It saves those answers to
golive.json, so every run after that is unattended.

    python golive.py --status      what is deployed, without changing anything
    python golive.py --redeploy    push the current code and trigger a new build
    python golive.py --help        all options

WHAT IT NEEDS
-------------
Three API tokens, which you create yourself and paste in when prompted. Never an
account password. Tokens are scoped to one service, can be given a short expiry,
and can be revoked individually. They are read without echoing, sent only to the
service they belong to, and never written to disk.

    Neon    https://console.neon.tech/app/settings/api-keys
    GitHub  https://github.com/settings/personal-access-tokens/new
            Fine-grained; Administration + Contents = Read and write
    Render  https://dashboard.render.com/settings#api-keys

Or set NEON_API_KEY, GITHUB_TOKEN and RENDER_API_KEY in the environment.

WHAT IT DOES
------------
    1. Inspects the project and checks your machine and tokens
    2. Creates the Neon project, takes the pooled connection string
    3. Runs your migration command against it, from here
    4. Creates the GitHub repository and pushes
    5. Creates the Render service, wired to Neon, and deploys
    6. Attaches a custom domain, if you set one, and prints the DNS record
    7. Fetches the live site to confirm it really is up

Every step is idempotent. An interrupted run resumes; it never creates duplicates.
Progress lives in golive.state.json — identifiers only, never secrets.

WHAT IT CANNOT DO
-----------------
Two things need a human in a browser, once each. The script stops and tells you
exactly what to click, then picks up where it left off on the next run:

    - Authorising Render to read your GitHub account. Render offers this only as
      an interactive install of its GitHub App; there is no API for it.
    - Adding the CNAME record at your domain registrar.
"""

from __future__ import annotations

import argparse
import ast
import getpass
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0"

HERE = Path.cwd()
CONFIG_FILE = HERE / "golive.json"
STATE_FILE = HERE / "golive.state.json"

NEON_API = "https://console.neon.tech/api/v2"
GITHUB_API = "https://api.github.com"
RENDER_API = "https://api.render.com/v1"

RENDER_REGIONS = ["oregon", "ohio", "virginia", "frankfurt", "singapore"]
NEON_REGIONS = {
    "frankfurt": "aws-eu-central-1", "oregon": "aws-us-west-2",
    "ohio": "aws-us-east-2", "virginia": "aws-us-east-1",
    "singapore": "aws-ap-southeast-1",
}

# Anything whose name looks like this is a secret: generated if not supplied,
# and never printed or stored in the config file.
SECRETISH = re.compile(r"(SECRET|PASSWORD|_KEY$|^KEY$|TOKEN|SALT|PRIVATE)", re.I)


# --------------------------------------------------------------------------
# Console
# --------------------------------------------------------------------------

def _colour_ok() -> bool:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True


COLOUR = _colour_ok()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOUR else text


def head(text: str) -> None:
    print()
    print(_c("1;36", text))
    print(_c("36", "-" * len(text)))


def step(n, total, text) -> None:
    print()
    print(_c("1;36", f"[{n}/{total}] {text}"))
    print(_c("36", "-" * (len(text) + 8)))


def ok(t): print(f"  {_c('32', 'OK')}    {t}")
def info(t): print(f"        {t}")
def warn(t): print(f"  {_c('33', 'NOTE')}  {t}")
def fail(t): print(f"  {_c('31', 'FAIL')}  {t}")


def action(title: str, body: str) -> None:
    print()
    print(_c("1;33", f"  >>> {title}"))
    for line in textwrap.dedent(body).strip().splitlines():
        print(_c("33", f"      {line}"))
    print()


class Abort(Exception):
    """Stop cleanly, having said what to do next."""


def ask(prompt: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    try:
        got = input(f"        {prompt}{shown}: ").strip()
    except EOFError:
        return default
    return got or default


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    try:
        got = input(f"        {prompt} [{d}] ").strip().lower()
    except EOFError:
        return default
    if not got:
        return default
    return got.startswith("y")


# --------------------------------------------------------------------------
# Secrets never reach the screen, a log, or a file
# --------------------------------------------------------------------------

SECRET_RE = re.compile(
    r"(napi_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|gho_[A-Za-z0-9]+"
    r"|rnd_[A-Za-z0-9]+"
    r"|postgres(?:ql)?(?:\+\w+)?://[^\s\"']+"
    r"|mysql(?:\+\w+)?://[^\s\"']+)"
)


def redact(text: str) -> str:
    def _mask(m):
        v = m.group(0)
        if "://" in v:
            return re.sub(r"//[^@/]+@", "//****:****@", v)
        return v[:9] + "..." + v[-4:] if len(v) > 16 else "****"
    return SECRET_RE.sub(_mask, str(text))


# --------------------------------------------------------------------------
# Config and state
# --------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        warn(f"{path.name} was unreadable and has been ignored.")
        return {}


def _write_json(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        warn(f"Could not write {path.name}: {exc}")


def load_state() -> dict:
    return _read_json(STATE_FILE)


def save_state(state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_json(STATE_FILE, state)


# --------------------------------------------------------------------------
# HTTP — stdlib only, so there is nothing to install before running this
# --------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, body: str, url: str):
        self.status, self.body, self.url = status, body, url
        super().__init__(f"HTTP {status} from {url}: {redact(body)[:400]}")


def request(method, url, token=None, body=None, headers=None,
            timeout=60, retries=3):
    data = None
    hdrs = {"Accept": "application/json", "User-Agent": f"golive/{VERSION}"}
    if headers:
        hdrs.update(headers)
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"

    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                if not raw.strip():
                    return {}
                try:
                    return json.loads(raw)
                except ValueError:
                    return raw
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = min(30, 2 ** attempt)
                warn(f"HTTP {exc.code} — retrying in {wait}s "
                     f"(attempt {attempt} of {retries})")
                time.sleep(wait)
                last = ApiError(exc.code, raw, url)
                continue
            raise ApiError(exc.code, raw, url) from None
        except urllib.error.URLError as exc:
            if attempt < retries:
                wait = min(30, 2 ** attempt)
                warn(f"Network error ({exc.reason}) — retrying in {wait}s")
                time.sleep(wait)
                last = exc
                continue
            raise Abort(
                f"Could not reach {urllib.parse.urlparse(url).netloc}: {exc.reason}\n"
                "        Check your internet connection, then run this again."
            ) from None
    raise last if last else RuntimeError("unreachable")


# ==========================================================================
# Project detection
# ==========================================================================

def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s) or "app"


def _module_defines_app(path: Path):
    """Find a module-level WSGI/ASGI callable without importing the file.

    Importing would run the module, which for a real app means connecting to
    things. Parsing the syntax tree tells us what we need and touches nothing.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return None
    names, framework = [], None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            label = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if label == "Flask":
                framework = "flask"
            elif label == "FastAPI":
                framework = "fastapi"
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Name) and t.id in ("app", "application"):
                names.append(t.id)
    return (names[0], framework) if names else None


def _framework_in_tree(root: Path) -> str:
    """Which framework this project uses, when the entry module does not say.

    An application factory — `app = create_app()` in wsgi.py, with `Flask(...)`
    over in app/__init__.py — is the common layout, and it hides the framework
    from the entry point entirely. Look a little wider before giving up.
    """
    looked = 0
    for py in root.rglob("*.py"):
        if any(p in py.parts for p in
               ("site-packages", ".venv", "venv", "node_modules", ".git")):
            continue
        looked += 1
        if looked > 300:
            break
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\bFastAPI\s*\(", text):
            return "fastapi"
        if re.search(r"\bFlask\s*\(", text):
            return "flask"
    return ""


def detect_entrypoint(root: Path) -> tuple[str, str, str]:
    """Return (framework, module:callable, kind) — kind is 'wsgi' or 'asgi'."""
    # Django announces itself unambiguously.
    manage = root / "manage.py"
    if manage.exists():
        for settings in root.rglob("settings.py"):
            if any(p in settings.parts for p in ("site-packages", ".venv", "venv")):
                continue
            pkg = settings.parent
            if (pkg / "wsgi.py").exists():
                rel = pkg.relative_to(root).as_posix().replace("/", ".")
                return "django", f"{rel}.wsgi:application", "wsgi"
        return "django", "config.wsgi:application", "wsgi"

    for name in ("wsgi.py", "asgi.py", "app.py", "main.py", "server.py",
                 "application.py", "run.py"):
        f = root / name
        if not f.exists():
            continue
        found = _module_defines_app(f)
        if not found:
            continue
        var, framework = found
        mod = name[:-3]
        framework = framework or _framework_in_tree(root)
        if name == "asgi.py" or framework == "fastapi":
            return (framework or "asgi"), f"{mod}:{var}", "asgi"
        return (framework or "wsgi"), f"{mod}:{var}", "wsgi"

    return "", "", ""


def detect_requirements(root: Path) -> str:
    for name in ("requirements-deploy.txt", "requirements-prod.txt",
                 "requirements.txt"):
        if (root / name).exists():
            return name
    if (root / "pyproject.toml").exists():
        return "pyproject.toml"
    return ""


def detect_python_version(root: Path) -> str:
    rt = root / "runtime.txt"
    if rt.exists():
        m = re.search(r"(\d+\.\d+\.\d+)", rt.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(1)
    pv = root / ".python-version"
    if pv.exists():
        raw = pv.read_text(encoding="utf-8", errors="replace").strip()
        if re.fullmatch(r"\d+\.\d+(\.\d+)?", raw):
            return raw if raw.count(".") == 2 else raw + ".0"
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def detect_database_var(root: Path) -> str:
    """Which environment variable this app reads its database URL from.

    Apps that namespace it (GTRACK_DATABASE_URL) do so deliberately, usually to
    avoid colliding with another app's generic DATABASE_URL on the same machine.
    Guessing wrong here is the difference between a working deploy and a confusing
    one, so prefer what the source actually reads.
    """
    candidates = []
    for name in ("config.py", "settings.py", "app.py", "wsgi.py", "main.py",
                 ".env.example", ".env.sample"):
        f = root / name
        if f.exists():
            candidates.append(f)
    for f in list(root.glob("*/settings.py")) + list(root.glob("*/config.py")):
        candidates.append(f)

    hits = []
    for f in candidates:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"\b([A-Z][A-Z0-9_]*_DATABASE_URL|DATABASE_URL)\b", text):
            hits.append(m.group(1))
    if not hits:
        return ""
    # A namespaced name beats the generic one when both appear.
    for h in hits:
        if h != "DATABASE_URL":
            return h
    return hits[0]


def detect_env_keys(root: Path) -> list[str]:
    keys = []
    for name in (".env.example", ".env.sample", ".env.template"):
        f = root / name
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k = line.split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", k):
                keys.append(k)
        break
    return keys


def detect_migrate(root: Path, framework: str) -> str:
    if (root / "seed.py").exists():
        text = (root / "seed.py").read_text(encoding="utf-8", errors="replace")
        return "python seed.py --force" if "--force" in text else "python seed.py"
    if framework == "django":
        return "python manage.py migrate --noinput"
    if (root / "alembic.ini").exists():
        return "alembic upgrade head"
    if (root / "migrations").is_dir():
        return "flask db upgrade"
    return ""


def detect_health_path(root: Path) -> str:
    """A path that returns 200 without a session. '/' is the safe default."""
    wanted = ("/healthz", "/health", "/login", "/ping")
    for py in list(root.rglob("*.py"))[:400]:
        if any(p in py.parts for p in ("site-packages", ".venv", "venv", "node_modules")):
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for path in wanted:
            if re.search(rf'(route|get|post)\(\s*["\']{re.escape(path)}["\']', text):
                return path
    return "/"


def detect_disk_var(root: Path, env_keys: list[str]) -> str:
    for k in env_keys:
        if re.search(r"(UPLOAD|MEDIA|STORAGE|FILES?)_(FOLDER|DIR|PATH|ROOT)", k):
            return k
    return ""


def inspect_project(root: Path) -> dict:
    framework, entry, kind = detect_entrypoint(root)
    env_keys = detect_env_keys(root)
    db_var = detect_database_var(root)
    found = dict(
        name=slug(root.name),
        framework=framework,
        entrypoint=entry,
        server=kind,
        requirements=detect_requirements(root),
        python_version=detect_python_version(root),
        database_url_var=db_var,
        migrate_command=detect_migrate(root, framework),
        health_path=detect_health_path(root),
        env_keys=env_keys,
        disk_var=detect_disk_var(root, env_keys),
    )
    return found


def build_start_command(cfg: dict) -> str:
    entry = cfg["entrypoint"]
    if cfg.get("server") == "asgi":
        return (f"uvicorn {entry.replace(':', ':')} --host 0.0.0.0 --port $PORT"
                if ":" in entry else f"uvicorn {entry} --host 0.0.0.0 --port $PORT")
    return (f"gunicorn {entry} --bind 0.0.0.0:$PORT "
            f"--workers {cfg.get('workers', 2)} --timeout 120")


# ==========================================================================
# First-run wizard
# ==========================================================================

def confirm_config(root: Path, args) -> dict:
    existing = _read_json(CONFIG_FILE)
    if existing and not args.reconfigure:
        ok(f"Read settings from {CONFIG_FILE.name}")
        return existing

    head("Inspecting the project")
    found = inspect_project(root)

    if not found["entrypoint"]:
        fail("Could not work out how to start this app.")
        info("Looked for a Flask/FastAPI 'app' in wsgi.py, app.py or main.py,")
        info("and for Django's manage.py. None matched.")
        print()
        entry = ask("Start module and callable (e.g. wsgi:app)")
        if not entry:
            raise Abort("Cannot deploy without knowing how to start the app.")
        found["entrypoint"] = entry
        found["server"] = "wsgi"

    if not found["requirements"]:
        raise Abort(
            "No requirements file found.\n"
            "        Render installs dependencies from requirements.txt. Create one\n"
            "        (pip freeze > requirements.txt) and run this again."
        )

    label = {"flask": "Flask", "django": "Django", "fastapi": "FastAPI"}.get(
        found["framework"], found["framework"] or "Python")
    print()
    ok(f"{label} app — starts with {found['entrypoint']}")
    ok(f"Dependencies from {found['requirements']}")
    ok(f"Python {found['python_version']}")
    if found["database_url_var"]:
        ok(f"Reads its database URL from {found['database_url_var']}")
    else:
        warn("No database URL variable found in the source.")
    if found["migrate_command"]:
        ok(f"Migration command: {found['migrate_command']}")
    ok(f"Health check path: {found['health_path']}")
    if found["env_keys"]:
        ok(f"{len(found['env_keys'])} variable(s) named in .env.example")

    print()
    print("  Press Enter to accept each value, or type a replacement.")
    print()

    cfg = {"_golive_version": VERSION}
    cfg["name"] = slug(ask("Service and repository name", found["name"]))
    cfg["entrypoint"] = ask("Start module:callable", found["entrypoint"])
    cfg["server"] = found["server"] or "wsgi"
    cfg["framework"] = found["framework"]
    cfg["requirements"] = ask("Requirements file", found["requirements"])
    cfg["python_version"] = ask("Python version", found["python_version"])
    cfg["health_path"] = ask("Health check path", found["health_path"])
    cfg["region"] = ask(f"Render region ({'/'.join(RENDER_REGIONS)})",
                        args.region)
    if cfg["region"] not in RENDER_REGIONS:
        warn(f"'{cfg['region']}' is not a Render region; using frankfurt.")
        cfg["region"] = "frankfurt"
    cfg["plan"] = ask("Render plan (free sleeps when idle, starter is always on)",
                      args.plan)
    cfg["branch"] = ask("Git branch", args.branch)
    cfg["private_repo"] = ask_yes("Make the GitHub repository private?", True)
    cfg["domain"] = ask("Custom domain (blank for none)", args.domain or "")

    print()
    if ask_yes("Does this app need a Postgres database?",
               bool(found["database_url_var"])):
        cfg["database"] = True
        cfg["database_url_var"] = ask("Environment variable for the database URL",
                                      found["database_url_var"] or "DATABASE_URL")
        cfg["neon_project"] = ask("Neon project name", cfg["name"])
        cfg["migrate_command"] = ask(
            "Command to build the schema (blank to skip)",
            found["migrate_command"])
    else:
        cfg["database"] = False
        cfg["database_url_var"] = ""
        cfg["neon_project"] = ""
        cfg["migrate_command"] = ""

    print()
    if ask_yes("Does it store uploaded files that must survive a redeploy?",
               bool(found["disk_var"])):
        cfg["disk_gb"] = int(ask("Disk size in GB", "5") or 5)
        cfg["disk_mount"] = ask("Mount path", "/var/data")
        cfg["disk_var"] = ask("Environment variable pointing at the upload folder",
                              found["disk_var"] or "")
    else:
        cfg["disk_gb"] = 0
        cfg["disk_mount"] = ""
        cfg["disk_var"] = ""

    # Remaining environment variables from .env.example.
    env = {}
    skip = {cfg["database_url_var"], cfg["disk_var"], ""}
    leftover = [k for k in found["env_keys"] if k not in skip]
    if leftover:
        print()
        print("  Environment variables from .env.example.")
        print("  Anything that looks like a secret is generated for you; leave it blank.")
        print()
        for key in leftover:
            if SECRETISH.search(key):
                env[key] = {"generate": 64}
                info(f"{key} — will be generated")
                continue
            val = ask(f"{key}", "")
            if val:
                env[key] = val
    cfg["env"] = env

    print()
    _write_json(CONFIG_FILE, cfg)
    ok(f"Saved to {CONFIG_FILE.name} — future runs will not ask again.")
    info("It contains no secrets and is safe to commit.")
    return cfg


# ==========================================================================
# Credentials
# ==========================================================================

TOKEN_HELP = {
    "neon": ("Neon API key", "NEON_API_KEY",
             "https://console.neon.tech/app/settings/api-keys",
             "Click 'Create new API key'. A personal key is right.", "napi_"),
    "github": ("GitHub token", "GITHUB_TOKEN",
               "https://github.com/settings/personal-access-tokens/new",
               "Use a FINE-GRAINED token. Repository access: All repositories.\n"
               "     Permissions -> Repository: Administration = Read and write,\n"
               "     Contents = Read and write. A 7-day expiry is plenty.",
               "github_pat_"),
    "render": ("Render API key", "RENDER_API_KEY",
               "https://dashboard.render.com/settings#api-keys",
               "Click 'Create API Key'. Copy it at once — Render shows it once.",
               "rnd_"),
}


def prompt_token(kind: str) -> str:
    label, env_name, url, how, prefix = TOKEN_HELP[kind]
    from_env = os.environ.get(env_name, "").strip()
    if from_env:
        ok(f"{label} read from {env_name}")
        return from_env

    print()
    print(_c("1", f"  {label}"))
    print(f"     Create one at: {_c('4', url)}")
    for line in how.splitlines():
        print(f"     {line}")
    print()
    for _ in range(3):
        value = getpass.getpass(f"     Paste the {label} (hidden): ").strip()
        if not value:
            fail("Nothing entered.")
            continue
        if prefix and not value.startswith(prefix):
            warn(f"That does not start with '{prefix}', which {label}s normally do.")
            if not ask_yes("Use it anyway?", False):
                continue
        return value
    raise Abort(f"No {label} supplied after three attempts.")


def collect_tokens(cfg: dict) -> dict:
    kinds = ["github", "render"] + (["neon"] if cfg.get("database") else [])
    return {k: prompt_token(k) for k in kinds}


# ==========================================================================
# Preflight
# ==========================================================================

def check_machine(cfg: dict, root: Path) -> None:
    if sys.version_info < (3, 9):
        raise Abort(f"Python 3.9 or newer is needed; this is {sys.version.split()[0]}.")
    ok(f"Python {sys.version.split()[0]}")

    if not shutil.which("git"):
        raise Abort(
            "git is not installed, or is not on PATH.\n"
            "        Install it from https://git-scm.com/downloads, reopen the\n"
            "        terminal, then run this again."
        )
    ok(subprocess.run(["git", "--version"], capture_output=True,
                      text=True).stdout.strip() or "git found")

    req = root / cfg["requirements"]
    if not req.exists():
        raise Abort(f"'{cfg['requirements']}' is missing from {root}.")
    ok(f"{cfg['requirements']} present")

    if cfg.get("server") == "wsgi" and cfg["requirements"].endswith(".txt"):
        text = req.read_text(encoding="utf-8", errors="replace").lower()
        if "gunicorn" not in text:
            warn(f"gunicorn is not in {cfg['requirements']}; Render needs it to "
                 "start the app.")
            if ask_yes("Add it now?", True):
                with req.open("a", encoding="utf-8") as fh:
                    fh.write("\ngunicorn>=23.0\n")
                ok("gunicorn added")
        if cfg.get("database") and "psycopg" not in text:
            warn(f"No Postgres driver in {cfg['requirements']}.")
            if ask_yes("Add psycopg2-binary?", True):
                with req.open("a", encoding="utf-8") as fh:
                    fh.write("psycopg2-binary>=2.9.9\n")
                ok("psycopg2-binary added")


def check_tokens(tokens: dict, state: dict) -> None:
    me = None
    try:
        me = request("GET", f"{GITHUB_API}/user", tokens["github"],
                     headers={"X-GitHub-Api-Version": "2022-11-28"})
    except ApiError as exc:
        if exc.status == 401:
            raise Abort("The GitHub token was rejected — expired or mistyped.")
        raise
    state["github_login"] = me["login"]
    ok(f"GitHub token valid — signed in as {me['login']}")

    if "neon" in tokens:
        try:
            p = request("GET", f"{NEON_API}/projects", tokens["neon"])
            ok(f"Neon key valid — {len(p.get('projects', []))} existing project(s)")
        except ApiError as exc:
            if exc.status in (401, 403):
                raise Abort("The Neon API key was rejected — expired or mistyped.")
            raise

    try:
        owners = request("GET", f"{RENDER_API}/owners?limit=20", tokens["render"])
    except ApiError as exc:
        if exc.status in (401, 403):
            raise Abort(
                "The Render API key was rejected.\n"
                "        If you are locked out of the Render dashboard, sign in with\n"
                "        GitHub or Google rather than a password, then create a key at\n"
                "        https://dashboard.render.com/settings#api-keys"
            )
        raise
    rows = [o["owner"] for o in owners] if isinstance(owners, list) else []
    if not rows:
        raise Abort("The Render key works but returned no workspace.")
    chosen = rows[0]
    if len(rows) > 1 and not state.get("render_owner_id"):
        print()
        info("More than one Render workspace is available:")
        for i, o in enumerate(rows, 1):
            info(f"  {i}. {o.get('name')} ({o.get('email', o.get('type', ''))})")
        pick = ask(f"Which one? [1-{len(rows)}]", "1")
        if pick.isdigit() and 1 <= int(pick) <= len(rows):
            chosen = rows[int(pick) - 1]
    elif state.get("render_owner_id"):
        chosen = next((o for o in rows if o["id"] == state["render_owner_id"]), chosen)
    state["render_owner_id"] = chosen["id"]
    ok(f"Render key valid — workspace '{chosen.get('name')}'")
    save_state(state)


# ==========================================================================
# Neon
# ==========================================================================

def make_pooled(uri: str) -> str:
    """Neon drops idle connections; the pooler is what keeps the first query
    after a quiet spell from failing. Always deploy against the pooled host."""
    if not uri or "-pooler." in uri:
        return uri
    return re.sub(r"@(ep-[^.]+)\.", r"@\1-pooler.", uri, count=1)


def pooled_uri(token, project_id, database, role) -> str:
    q = urllib.parse.urlencode(dict(database_name=database, role_name=role,
                                    pooled="true"))
    try:
        got = request("GET", f"{NEON_API}/projects/{project_id}/connection_uri?{q}",
                      token)
        if isinstance(got, dict) and got.get("uri"):
            return got["uri"]
    except ApiError as exc:
        warn(f"Pooled connection endpoint returned HTTP {exc.status}; deriving it.")
    return ""


def setup_neon(tokens, cfg, state) -> str:
    name = cfg["neon_project"]
    page = request("GET", f"{NEON_API}/projects?limit=100", tokens["neon"])
    existing = next((p for p in page.get("projects", []) if p.get("name") == name),
                    None)

    if existing:
        pid = existing["id"]
        ok(f"Neon project '{name}' already exists ({pid})")
        state["neon_project_id"] = pid
        save_state(state)
        branches = request("GET", f"{NEON_API}/projects/{pid}/branches",
                           tokens["neon"]).get("branches", [])
        if not branches:
            raise Abort(f"Neon project '{name}' has no branch to connect to.")
        default = next((b for b in branches if b.get("default")), branches[0])
        dbs = request("GET", f"{NEON_API}/projects/{pid}/branches/{default['id']}"
                             "/databases", tokens["neon"]).get("databases", [])
        roles = request("GET", f"{NEON_API}/projects/{pid}/branches/{default['id']}"
                               "/roles", tokens["neon"]).get("roles", [])
        if not dbs or not roles:
            raise Abort(f"Neon project '{name}' has no database or role.")
        uri = pooled_uri(tokens["neon"], pid, dbs[0]["name"], roles[0]["name"])
        if not uri:
            raise Abort("Could not get a connection string for the existing Neon "
                        "project. Copy the pooled string from the dashboard and set "
                        f"{cfg['database_url_var']} by hand.")
        return make_pooled(uri)

    region = NEON_REGIONS.get(cfg["region"], "aws-eu-central-1")
    info(f"Creating Neon project '{name}' in {region}...")
    created = request("POST", f"{NEON_API}/projects", tokens["neon"],
                      body={"project": {"name": name, "region_id": region,
                                        "pg_version": 16}})
    project = created["project"]
    state["neon_project_id"] = project["id"]
    save_state(state)
    ok(f"Neon project created ({project['id']})")

    uris = created.get("connection_uris") or []
    uri = uris[0].get("connection_uri", "") if uris else ""
    if not uri:
        dbs, roles = created.get("databases", []), created.get("roles", [])
        if dbs and roles:
            uri = pooled_uri(tokens["neon"], project["id"],
                             dbs[0]["name"], roles[0]["name"])
    if not uri:
        raise Abort("Neon created the project but returned no connection string.")
    ok("Pooled connection string retrieved")
    return make_pooled(uri)


# ==========================================================================
# Migrate
# ==========================================================================

def run_migration(cfg, db_url, state, skip) -> None:
    command = cfg.get("migrate_command", "")
    if skip or not command:
        if not command:
            info("No migration command configured — skipping.")
        else:
            warn("Skipping the migration at your request.")
        return
    if state.get("migrated"):
        ok("Database already built on an earlier run — skipping.")
        return

    try:
        import psycopg2  # noqa: F401
    except ImportError:
        info("Installing psycopg2-binary so this machine can reach Neon...")
        r = subprocess.run([sys.executable, "-m", "pip", "install",
                            "psycopg2-binary", "--quiet"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Abort("Could not install psycopg2-binary:\n        "
                        + redact(r.stderr.strip())[:400])
        ok("psycopg2-binary installed")

    info(f"Running: {command}")
    env = dict(os.environ)
    env[cfg["database_url_var"]] = db_url
    # Many libraries look only at the generic name; set both so either works.
    env.setdefault("DATABASE_URL", db_url)
    parts = command.split()
    if parts[0] == "python":
        parts[0] = sys.executable
    r = subprocess.run(parts, cwd=str(HERE), env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise Abort("The migration failed:\n        "
                    + redact((r.stdout[-700:] + r.stderr[-700:]).strip())
                    + "\n        Fix the cause and run this again — it retries this step.")
    for line in r.stdout.splitlines()[-12:]:
        if line.strip():
            info(redact(line.rstrip()))
    state["migrated"] = True
    save_state(state)
    ok("Database built")


# ==========================================================================
# GitHub
# ==========================================================================

def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=str(HERE), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Abort(f"git {' '.join(args)} failed:\n        "
                    + redact(r.stderr.strip())[:500])
    return r


def ensure_gitignore(extra: list[str]) -> None:
    path = HERE / ".gitignore"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [e for e in extra if e not in current]
    if not missing:
        return
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n# added by golive\n" + "\n".join(missing) + "\n")
    ok(f"Added {', '.join(missing)} to .gitignore")


def setup_github(tokens, cfg, state) -> str:
    login = state["github_login"]
    full = f"{login}/{cfg['name']}"
    try:
        repo = request("GET", f"{GITHUB_API}/repos/{full}", tokens["github"],
                       headers={"X-GitHub-Api-Version": "2022-11-28"})
        ok(f"Repository {full} already exists")
    except ApiError as exc:
        if exc.status == 403:
            raise Abort(
                "GitHub refused the request (403). The token most likely lacks the\n"
                "        Administration or Contents permission. Create a fine-grained\n"
                "        token with both set to 'Read and write'."
            )
        if exc.status != 404:
            raise
        info(f"Creating {'private' if cfg.get('private_repo', True) else 'public'} "
             f"repository {full}...")
        repo = request("POST", f"{GITHUB_API}/user/repos", tokens["github"], body={
            "name": cfg["name"], "private": bool(cfg.get("private_repo", True)),
            "has_issues": True, "has_wiki": False, "auto_init": False,
        }, headers={"X-GitHub-Api-Version": "2022-11-28"})
        ok(f"Repository created — {repo['html_url']}")

    state["repo_full_name"] = full
    state["repo_url"] = repo["html_url"]
    save_state(state)

    if not (HERE / ".git").exists():
        info("Initialising a local git repository...")
        git("init")
        git("checkout", "-b", cfg["branch"], check=False)
    if not git("config", "user.email", check=False).stdout.strip():
        git("config", "user.email", f"{login}@users.noreply.github.com")
    if not git("config", "user.name", check=False).stdout.strip():
        git("config", "user.name", login)
    ok("Local git repository ready")

    ensure_gitignore([STATE_FILE.name, ".env", "__pycache__/", "*.pyc"])

    git("add", "-A")
    if git("status", "--porcelain").stdout.strip():
        git("commit", "-m", "golive: deploy", check=False)
        ok("Changes committed")
    else:
        ok("Nothing new to commit")
    if not git("rev-parse", "HEAD", check=False).stdout.strip():
        raise Abort("There is nothing committed to push.")

    branch_now = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    authed = repo["clone_url"].replace(
        "https://", f"https://x-access-token:{tokens['github']}@")
    info(f"Pushing '{branch_now}' to {full}...")
    r = subprocess.run(["git", "push", authed, f"{branch_now}:{cfg['branch']}",
                        "--force"], cwd=str(HERE), capture_output=True, text=True)
    if r.returncode != 0:
        raise Abort("Push failed:\n        " + redact(r.stderr.strip())[:600])
    ok(f"Pushed to {full} ({cfg['branch']})")

    # Leave a remote with no credential baked into it.
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", repo["clone_url"], check=False)
    return repo["clone_url"]


# ==========================================================================
# Render
# ==========================================================================

def build_env_vars(cfg, db_url) -> list:
    out = []
    if cfg.get("database") and db_url:
        out.append({"key": cfg["database_url_var"], "value": db_url})
    if cfg.get("disk_var") and cfg.get("disk_mount"):
        out.append({"key": cfg["disk_var"],
                    "value": f"{cfg['disk_mount'].rstrip('/')}/uploads"})
    for key, val in (cfg.get("env") or {}).items():
        if isinstance(val, dict) and val.get("generate"):
            out.append({"key": key, "value": secrets.token_hex(
                max(16, int(val["generate"]) // 2))})
        elif isinstance(val, str) and val:
            out.append({"key": key, "value": val})
    out.append({"key": "PYTHON_VERSION", "value": cfg["python_version"]})
    seen, unique = set(), []
    for e in out:
        if e["key"] in seen:
            continue
        seen.add(e["key"])
        unique.append(e)
    return unique


def find_service(token, owner_id, name):
    got = request("GET", f"{RENDER_API}/services?name={urllib.parse.quote(name)}"
                          f"&ownerId={owner_id}&limit=20", token)
    for row in (got if isinstance(got, list) else []):
        svc = row.get("service", row)
        if svc.get("name") == name:
            return svc
    return None


def build_command_for(cfg) -> str:
    if cfg["requirements"] == "pyproject.toml":
        return "pip install ."
    return f"pip install -r {cfg['requirements']}"


def setup_render(tokens, cfg, state, repo_url, db_url):
    owner = state["render_owner_id"]
    svc = find_service(tokens["render"], owner, cfg["name"])
    env_vars = build_env_vars(cfg, db_url)

    if svc:
        ok(f"Render service '{cfg['name']}' already exists ({svc['id']})")
        state["render_service_id"] = svc["id"]
        save_state(state)
        # Only refresh the values we own; leave anything set by hand alone.
        try:
            current = request("GET", f"{RENDER_API}/services/{svc['id']}/env-vars"
                                     "?limit=100", tokens["render"])
            have = {}
            for row in (current if isinstance(current, list) else []):
                ev = row.get("envVar", row)
                if isinstance(ev, dict) and ev.get("key"):
                    have[ev["key"]] = ev.get("value", "")
            merged = dict(have)
            for e in env_vars:
                # never rotate a generated secret that already exists
                if e["key"] in have and SECRETISH.search(e["key"]):
                    continue
                merged[e["key"]] = e["value"]
            request("PUT", f"{RENDER_API}/services/{svc['id']}/env-vars",
                    tokens["render"],
                    body=[{"key": k, "value": v} for k, v in merged.items()])
            ok("Environment variables updated")
        except ApiError as exc:
            warn(f"Could not update environment variables (HTTP {exc.status}). "
                 "Set them by hand in the Render dashboard.")
        return svc

    body = {
        "type": "web_service",
        "name": cfg["name"],
        "ownerId": owner,
        "repo": repo_url.removesuffix(".git"),
        "branch": cfg["branch"],
        "autoDeploy": "yes",
        "envVars": env_vars,
        "serviceDetails": {
            "env": "python",
            "plan": cfg["plan"],
            "region": cfg["region"],
            "healthCheckPath": cfg["health_path"],
            "envSpecificDetails": {
                "buildCommand": build_command_for(cfg),
                "startCommand": build_start_command(cfg),
            },
        },
    }
    if cfg.get("disk_gb"):
        body["serviceDetails"]["disk"] = {
            "name": "data", "mountPath": cfg["disk_mount"],
            "sizeGB": int(cfg["disk_gb"]),
        }

    info(f"Creating the Render web service in {cfg['region']}...")
    info(f"  build: {body['serviceDetails']['envSpecificDetails']['buildCommand']}")
    info(f"  start: {body['serviceDetails']['envSpecificDetails']['startCommand']}")
    try:
        created = request("POST", f"{RENDER_API}/services", tokens["render"], body=body)
    except ApiError as exc:
        low = exc.body.lower()
        if exc.status in (400, 404) and ("repo" in low or "repositor" in low
                                         or "not found" in low):
            action("Render cannot see your GitHub repository yet", f"""
                This is the one step with no API. Render needs its GitHub App
                installed on your account before it can read the repository.

                  1. Open  https://dashboard.render.com/settings#account-security
                  2. Under 'Git providers', click Add credential -> GitHub
                  3. Authorise it, and grant access to '{state['repo_full_name']}'
                     (or to all repositories)
                  4. Run this again — everything up to here is already done and
                     will be skipped.

                You only ever do this once per GitHub account, not per project.
            """)
            raise Abort("Waiting on the GitHub authorisation above.")
        if exc.status == 402:
            raise Abort(
                "Render returned a payment error. The 'starter' plan and a persistent\n"
                "        disk both need billing enabled on the workspace.\n"
                "        Either add a card, or re-run with:  --plan free --no-disk"
            )
        raise

    svc = created.get("service", created)
    state["render_service_id"] = svc["id"]
    state["render_service_url"] = svc.get("serviceDetails", {}).get("url", "")
    save_state(state)
    ok(f"Service created ({svc['id']})")
    return svc


def wait_for_deploy(token, service_id, minutes=20) -> bool:
    info("Waiting for the deploy. A cold build takes a few minutes...")
    deadline = time.time() + minutes * 60
    seen, empty = None, 0
    while time.time() < deadline:
        try:
            deploys = request("GET", f"{RENDER_API}/services/{service_id}"
                                     "/deploys?limit=1", token, retries=1)
        except ApiError:
            time.sleep(15)
            continue
        rows = deploys if isinstance(deploys, list) else []
        if not rows:
            empty += 1
            if empty == 4:
                warn("Render has not queued a deploy yet. Still waiting...")
            if empty >= 20:
                warn("No deploy was ever queued. Check the service in Render:")
                info(f"  https://dashboard.render.com/web/{service_id}/events")
                return False
            time.sleep(15)
            continue
        empty = 0
        d = rows[0].get("deploy", rows[0])
        status = d.get("status", "unknown")
        if status != seen:
            info(f"  deploy status: {status}")
            seen = status
        if status == "live":
            ok("Deploy is live")
            return True
        if status in ("build_failed", "update_failed", "canceled",
                      "pre_deploy_failed", "deactivated"):
            fail(f"Deploy finished as '{status}'.")
            info("  The build log says why:")
            info(f"  https://dashboard.render.com/web/{service_id}/logs")
            return False
        time.sleep(15)
    warn(f"Still building after {minutes} minutes. It may yet succeed:")
    info(f"  https://dashboard.render.com/web/{service_id}/events")
    return False


# ==========================================================================
# Domain and verification
# ==========================================================================

def setup_domain(tokens, cfg, state, service_id, default_url) -> None:
    domain = (cfg.get("domain") or "").strip()
    if not domain:
        info("No custom domain configured — skipping.")
        return
    try:
        existing = request("GET", f"{RENDER_API}/services/{service_id}"
                                  "/custom-domains?limit=20", tokens["render"])
        names = []
        for r in (existing if isinstance(existing, list) else []):
            row = r.get("customDomain", r) if isinstance(r, dict) else {}
            if isinstance(row, dict) and row.get("name"):
                names.append(row["name"])
        if domain in names:
            ok(f"{domain} is already attached")
        else:
            request("POST", f"{RENDER_API}/services/{service_id}/custom-domains",
                    tokens["render"], body={"name": domain})
            ok(f"{domain} attached to the service")
    except ApiError as exc:
        if exc.status == 409:
            ok(f"{domain} is already attached")
        else:
            warn(f"Could not attach the domain (HTTP {exc.status}). Add it from the "
                 "service's Settings > Custom Domains tab.")
            return

    target = urllib.parse.urlparse(default_url).netloc or default_url
    labels = domain.split(".")
    apex = len(labels) <= 2
    action("Add this DNS record at your registrar", f"""
        Render will not issue the TLS certificate until this resolves.

          Type:      {"ALIAS or ANAME (or A, if your registrar has neither)" if apex else "CNAME"}
          Host:      {"@" if apex else labels[0]}
          Points to: {target or "the onrender.com hostname shown in Render"}
          TTL:       3600, or the default

        Propagation is usually minutes; the certificate follows automatically.
        Watch it on the service's Settings -> Custom Domains tab.
    """)


def verify(url: str, health: str) -> bool:
    if not url:
        return False
    target = url.rstrip("/") + (health if health.startswith("/") else "/" + health)
    info(f"Checking {target} ...")
    for attempt in range(5):
        try:
            req = urllib.request.Request(target, headers={"User-Agent": "golive"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if 200 <= resp.status < 400:
                    ok(f"Live and answering at {url}")
                    return True
                warn(f"Responded HTTP {resp.status}.")
                return False
        except urllib.error.HTTPError as exc:
            # A 401/403 still proves the app is up and routing.
            if exc.code in (401, 403):
                ok(f"Live at {url} (the health path requires a sign-in)")
                return True
            warn(f"Responded HTTP {exc.code} at {health}.")
            return False
        except Exception as exc:
            if attempt < 4:
                info(f"  not answering yet ({type(exc).__name__}); waiting 20s")
                time.sleep(20)
            else:
                warn(f"Could not reach {target}: {exc}")
    return False


# ==========================================================================
# Status
# ==========================================================================

def show_status(cfg, state) -> int:
    head(f"{cfg.get('name', HERE.name)} — current state")
    if not state:
        info("Nothing deployed yet from this folder.")
        return 1
    rows = [
        ("Neon project", state.get("neon_project_id", "—")),
        ("Database built", "yes" if state.get("migrated") else "no"),
        ("Repository", state.get("repo_url", "—")),
        ("Render service", state.get("render_service_id", "—")),
        ("URL", state.get("render_service_url", "—")),
        ("Last run", state.get("updated_at", "—")),
    ]
    for label, value in rows:
        print(f"  {label:<16} {value}")
    if state.get("render_service_id"):
        print()
        print(f"  Dashboard  https://dashboard.render.com/web/"
              f"{state['render_service_id']}")
    return 0


# ==========================================================================
# Main
# ==========================================================================

def parse_args():
    p = argparse.ArgumentParser(
        prog="golive",
        description="Put a Python web app online: Neon + GitHub + Render.")
    p.add_argument("--name", help="service and repository name")
    p.add_argument("--branch", default="main")
    p.add_argument("--domain", default="", help="custom domain to attach")
    p.add_argument("--region", default="frankfurt", choices=RENDER_REGIONS)
    p.add_argument("--plan", default="starter",
                   help="Render plan: starter (always on) or free (sleeps)")
    p.add_argument("--no-disk", action="store_true",
                   help="do not attach a persistent disk")
    p.add_argument("--skip-migrate", action="store_true",
                   help="leave the database alone")
    p.add_argument("--no-wait", action="store_true",
                   help="do not wait for the build to finish")
    p.add_argument("--reconfigure", action="store_true",
                   help="ask the setup questions again")
    p.add_argument("--redeploy", action="store_true",
                   help="commit, push and trigger a new build; change nothing else")
    p.add_argument("--status", action="store_true",
                   help="show what is deployed, and change nothing")
    p.add_argument("--reset", action="store_true",
                   help="forget saved progress and start over")
    p.add_argument("--version", action="version", version=f"golive {VERSION}")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("Saved progress cleared.")

    state = load_state()

    if args.status:
        return show_status(_read_json(CONFIG_FILE), state)

    print()
    print(_c("1;36", f"  golive {VERSION}"))
    print(_c("36", "  " + "=" * 42))
    print(f"  {HERE}")
    print()
    print(_c("2", "  Creates a Neon database, a GitHub repository and a Render"))
    print(_c("2", "  service, then puts the app online. Existing resources with"))
    print(_c("2", "  the same names are reused, never duplicated."))
    print()
    print(_c("2", "  Asks for API tokens, never account passwords. Tokens are read"))
    print(_c("2", "  without echoing and are never written to disk."))

    try:
        cfg = confirm_config(HERE, args)
        if args.name:
            cfg["name"] = slug(args.name)
        if args.domain:
            cfg["domain"] = args.domain
        if args.no_disk:
            cfg["disk_gb"] = 0
        if args.plan != "starter":
            cfg["plan"] = args.plan

        total = 7 if cfg.get("database") else 5

        if args.redeploy:
            head("Redeploying")
            tokens = {"github": prompt_token("github")}
            check_tokens({**tokens, "render": prompt_token("render")}, state)
            setup_github(tokens, cfg, state)
            ok("Pushed. Render will rebuild automatically.")
            if state.get("render_service_id"):
                info(f"https://dashboard.render.com/web/"
                     f"{state['render_service_id']}/events")
            return 0

        n = 0
        n += 1
        step(n, total, "Checking this machine and your tokens")
        check_machine(cfg, HERE)
        tokens = collect_tokens(cfg)
        print()
        check_tokens(tokens, state)

        db_url = ""
        if cfg.get("database"):
            n += 1
            step(n, total, "Neon — database")
            db_url = setup_neon(tokens, cfg, state)

            n += 1
            step(n, total, "Building the database")
            run_migration(cfg, db_url, state, args.skip_migrate)

        n += 1
        step(n, total, "GitHub — source repository")
        repo_url = setup_github(tokens, cfg, state)

        n += 1
        step(n, total, "Render — web service")
        svc = setup_render(tokens, cfg, state, repo_url, db_url)
        live_url = (svc.get("serviceDetails", {}).get("url")
                    or state.get("render_service_url", ""))
        deployed = True
        if not args.no_wait:
            deployed = wait_for_deploy(tokens["render"], svc["id"])

        n += 1
        step(n, total, "Custom domain")
        setup_domain(tokens, cfg, state, svc["id"], live_url)

        n += 1
        step(n, total, "Verifying")
        reachable = verify(live_url, cfg["health_path"]) if deployed else False

        head("Done")
        print(f"  Live at        {live_url or '(pending first deploy)'}")
        if cfg.get("domain"):
            print(f"  Custom domain  https://{cfg['domain']}  (once the DNS resolves)")
        print(f"  Repository     {state.get('repo_url', '')}")
        print(f"  Render service https://dashboard.render.com/web/{svc['id']}")
        print()
        print("  From here on, any push to "
              f"{cfg['branch']} rebuilds and redeploys automatically.")
        print(f"  Or run:  python {Path(__file__).name} --redeploy")
        if not reachable:
            print()
            warn("The site has not answered yet. That is normal for a first build;")
            info("watch the Events tab in Render, then run --status to re-check.")
        print()
        return 0 if reachable else 1

    except Abort as exc:
        print()
        fail(str(exc))
        print()
        info("Nothing already completed has been undone. Fix the above and run")
        info("this again — it resumes from where it stopped.")
        print()
        return 2
    except ApiError as exc:
        print()
        fail(redact(str(exc)))
        print()
        return 2
    except KeyboardInterrupt:
        print()
        print()
        warn("Stopped. Progress is saved; run this again to resume.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
