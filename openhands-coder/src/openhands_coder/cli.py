"""localagent — one-command setup and lifecycle for the private coding agent.

Install:  pipx install local-coding-agent   (or: uv tool install local-coding-agent)
Then:     localagent init      materialize configs into ~/.config/local-coding-agent
          localagent up        start the memory stack (docker)
          localagent goose-setup   render ~/.config/goose/config.yaml
          localagent doctor    health-check everything
          localagent down      stop services

Design: the pip package is the front door; the memory stack runs in Docker;
ALL models run on AWS Bedrock (Claude / Nova) — no local inference, no GPU.
Native pieces (goose, docker) are host installs this CLI checks for and
explains. Cross-platform: macOS, Linux, and Windows.

Everything operates on a home dir (default ~/.config/local-coding-agent,
override with LCA_HOME) holding .env, docker-compose.yml, goose templates,
and service logs. Stdlib only.
"""

import argparse
import importlib.resources
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ── plumbing ──────────────────────────────────────────────────────────


def home_dir() -> str:
    return os.environ.get(
        "LCA_HOME",
        os.path.join(os.path.expanduser("~"), ".config", "local-coding-agent"),
    )


def _assets():
    return importlib.resources.files("openhands_coder") / "assets"


def load_env(home: str) -> dict:
    """Parse .env (KEY=VALUE, ${VAR} expansion against itself + os.environ)."""
    env: dict[str, str] = {}
    path = os.path.join(home, ".env")
    if not os.path.isfile(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            lookup = {**os.environ, **env}
            for var, val in lookup.items():
                value = value.replace("${%s}" % var, val)
            env[key.strip()] = value.strip()
    return env


def _http(url: str, method: str = "GET", body: dict | None = None, timeout: int = 5):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode()


def _up(url: str, timeout: int = 2) -> bool:
    try:
        return _http(url, timeout=timeout)[0] == 200
    except (urllib.error.URLError, OSError):
        return False


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _bad(msg: str) -> None:
    print(f"  ✗ {msg}")


def _bin_dir() -> str:
    return os.path.dirname(sys.executable)


def _script_path(name: str) -> str:
    """Path to a console script installed next to this interpreter.
    On Windows entry points are <name>.exe — check both spellings."""
    for candidate in (name, name + ".exe"):
        path = os.path.join(_bin_dir(), candidate)
        if os.path.isfile(path):
            return path
    return shutil.which(name) or os.path.join(_bin_dir(), name)


# ── commands ──────────────────────────────────────────────────────────


def cmd_init(_args) -> int:
    home = home_dir()
    os.makedirs(home, exist_ok=True)
    assets = _assets()
    materialize = {
        "docker-compose.yml": "docker-compose.yml",
        "openmemory-bedrock.Dockerfile": "openmemory-bedrock.Dockerfile",
        "config-template.yaml": "goose-config-template.yaml",
        "plan-and-delegate.yaml": "plan-and-delegate.yaml",
    }
    for src, dst in materialize.items():
        with importlib.resources.as_file(assets / src) as p:
            shutil.copy(p, os.path.join(home, dst))
    # Never overwrite user-owned files.
    for src, dst in {
        "env.example": ".env",
        "preferences.md": "preferences.md",
    }.items():
        target = os.path.join(home, dst)
        if not os.path.exists(target):
            with importlib.resources.as_file(assets / src) as p:
                shutil.copy(p, target)
    tdir = os.path.join(home, "repo-templates")
    os.makedirs(tdir, exist_ok=True)
    for name in ("goosehints", "AGENTS.md"):
        with importlib.resources.as_file(assets / "templates" / name) as p:
            shutil.copy(p, os.path.join(tdir, name))

    print(f"Initialized {home}")
    print("\nDependency check:")
    deps = {
        "docker": "Docker Desktop (memory stack; works on macOS/Linux/Windows)",
        "goose": "brew install block-goose-cli, or the Windows release from "
                 "github.com/block/goose (orchestrator)",
        "uvx": "https://docs.astral.sh/uv/getting-started/installation/ "
               "(runs the OpenMemory MCP bridge)",
        "aws": "AWS CLI — needed once for `aws configure` (Bedrock "
               "credentials); installers at aws.amazon.com/cli",
    }
    missing = 0
    for binary, hint in deps.items():
        if shutil.which(binary):
            _ok(binary)
        else:
            _bad(f"{binary} missing — {hint}")
            missing += 1
    print(f"\nNext: edit {home}/.env, then: localagent up && localagent goose-setup")
    return 1 if missing else 0


def cmd_up(_args) -> int:
    home = home_dir()
    env = load_env(home)
    if not env:
        print(f"No .env in {home} — run: localagent init", file=sys.stderr)
        return 1

    # 1. memory stack containers (the only services — all inference is
    #    on Bedrock, so there is nothing to run on the host). The compose
    #    file mounts ~/.aws read-only; make sure it exists so the bind
    #    mount can't fail on a machine that hasn't run `aws configure` yet.
    os.makedirs(os.path.join(os.path.expanduser("~"), ".aws"), exist_ok=True)
    subprocess.run(
        ["docker", "compose", "-f", os.path.join(home, "docker-compose.yml"),
         "--env-file", os.path.join(home, ".env"), "up", "-d", "--build"],
        check=True,
    )

    # 2. wait for the API, then pin mem0's LLM + embedder to Bedrock (the
    #    image persists this in its DB; env vars alone don't switch it)
    print("waiting for services", end="", flush=True)
    deadline = time.time() + 300
    while time.time() < deadline:
        if _up("http://localhost:8765/docs"):
            break
        print(".", end="", flush=True)
        time.sleep(5)
    else:
        print("\nTIMED OUT — check: docker compose logs openmemory-mcp")
        return 1
    print(" ready")

    dims = int(env.get("MEMORY_EMBEDDING_DIMS") or 1024)
    for section, config in {
        "llm": {"model": env.get("MEMORY_LLM_MODEL") or "us.amazon.nova-lite-v1:0",
                "temperature": 0.1, "max_tokens": 2000},
        "embedder": {"model": (env.get("MEMORY_EMBEDDER_MODEL")
                               or "amazon.titan-embed-text-v2:0"),
                     "embedding_dims": dims},
    }.items():
        _, body = _http(f"http://localhost:8765/api/v1/config/mem0/{section}",
                        "PUT", {"provider": "aws_bedrock", "config": config})
        if '"detail"' in body:
            print(f"FAILED to pin mem0 {section} config: {body}", file=sys.stderr)
            return 1
    if not _up("http://localhost:6333/collections/openmemory"):
        _http("http://localhost:6333/collections/openmemory", "PUT",
              {"vectors": {"size": dims, "distance": "Cosine"}})
        print(f"pre-created qdrant collection ({dims}-dim)")

    user = env.get("MEMORY_USER_ID", "default")
    print(f"\nMemory stack ready. MCP: http://localhost:8765/mcp/<client>/sse/{user}")
    print("UI: http://localhost:3000   Next: localagent goose-setup")
    return 0


def cmd_down(_args) -> int:
    home = home_dir()
    subprocess.run(
        ["docker", "compose", "-f", os.path.join(home, "docker-compose.yml"),
         "--env-file", os.path.join(home, ".env"), "down"],
        check=False,
    )
    print("stopped")
    return 0


def cmd_goose_setup(_args) -> int:
    home = home_dir()
    env = load_env(home)
    if not env:
        print(f"No .env in {home} — run: localagent init", file=sys.stderr)
        return 1
    if not env.get("MEMORY_NOTES_DIR"):  # absent OR left empty in .env
        env["MEMORY_NOTES_DIR"] = os.path.join(
            os.path.expanduser("~"), ".local", "share", "agent-memory")
    env["PROJECT_ROOT"] = home
    env["CODER_BIN_DIR"] = _bin_dir()
    env["PREFERENCES_FILE"] = os.path.join(home, "preferences.md")

    with open(os.path.join(home, "goose-config-template.yaml"), encoding="utf-8") as f:
        rendered = f.read()
    # Template points PREFERENCES_FILE at the repo path; CLI homes override it.
    rendered = rendered.replace("${PROJECT_ROOT}/prefs/preferences.md",
                                env["PREFERENCES_FILE"])
    for key, value in env.items():
        rendered = rendered.replace("${%s}" % key, value)

    goose_dir = os.path.join(os.path.expanduser("~"), ".config", "goose")
    os.makedirs(goose_dir, exist_ok=True)
    config_path = os.path.join(goose_dir, "config.yaml")
    if os.path.isfile(config_path):
        shutil.copy(config_path, config_path + f".bak.{int(time.time())}")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"Wrote {config_path}")

    hints = os.path.join(goose_dir, ".goosehints")
    if os.path.isfile(hints) and not os.path.islink(hints):
        shutil.copy(hints, hints + f".bak.{int(time.time())}")
        os.remove(hints)
    elif os.path.islink(hints):
        os.remove(hints)
    try:
        os.symlink(env["PREFERENCES_FILE"], hints)
        print(f"Linked {env['PREFERENCES_FILE']} -> {hints} (loaded every session)")
    except OSError:
        # Windows needs Developer Mode/admin for symlinks — fall back to a
        # copy and tell the user it won't track edits automatically.
        shutil.copy(env["PREFERENCES_FILE"], hints)
        print(f"Copied {env['PREFERENCES_FILE']} -> {hints} (loaded every "
              "session; re-run goose-setup after editing preferences)")
    print(f"\nRecipe: goose run --recipe {home}/plan-and-delegate.yaml "
          "--params task='...' repo_path=/path/to/repo")
    return 0


def cmd_doctor(_args) -> int:
    home = home_dir()
    env = load_env(home)
    user = env.get("MEMORY_USER_ID", "default")
    failures = 0

    def check(label: str, passed: bool, hint: str = "") -> None:
        nonlocal failures
        if passed:
            _ok(label)
        else:
            _bad(label + (f" — {hint}" if hint else ""))
            failures += 1

    print("[1/4] services")
    ps = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                        capture_output=True, text=True, check=False).stdout
    check("qdrant container", "mem0_store" in ps, "localagent up")
    check("openmemory container", "openmemory-mcp" in ps, "localagent up")
    aws_dir = os.path.join(os.path.expanduser("~"), ".aws")
    has_creds = bool(os.environ.get("AWS_ACCESS_KEY_ID")) or any(
        os.path.isfile(os.path.join(aws_dir, f)) for f in ("credentials", "config")
    )
    check("AWS credentials (Bedrock)", has_creds,
          "aws configure (or aws sso login)")

    print("[2/4] memory write+recall (end to end)")
    try:
        status, body = _http(
            "http://localhost:8765/api/v1/memories/", "POST",
            {"user_id": user, "text": "doctor check: user likes green tea",
             "app": "doctor", "infer": True}, timeout=120)
        # The API can answer 200 with {"error": ...} — read the body, not
        # just the status, or this check lies on machines without Bedrock
        # credentials (observed live).
        error = ""
        if status == 200:
            try:
                error = str(json.loads(body).get("error") or "")
            except (json.JSONDecodeError, AttributeError):
                error = ""
        check("episodic memory write (Bedrock round trip)",
              status == 200 and not error, error or f"HTTP {status}")
    except (urllib.error.URLError, OSError) as exc:
        check("episodic memory write (Bedrock round trip)", False, str(exc))

    print("[3/4] agent components")
    check("openhands-coder on PATH", os.path.isfile(_script_path("openhands-coder")))
    check("memory-direct on PATH", os.path.isfile(_script_path("memory-direct")))
    check("goose CLI", shutil.which("goose") is not None,
          "brew install block-goose-cli")

    print("[4/4] goose config")
    config_path = os.path.join(os.path.expanduser("~"), ".config", "goose",
                               "config.yaml")
    rendered = os.path.isfile(config_path)
    body = open(config_path, encoding="utf-8").read() if rendered else ""
    check("config rendered with both extensions",
          "openhands_coder" in body and "memory_direct" in body,
          "localagent goose-setup")

    print(f"\n{'all good' if not failures else f'{failures} failure(s)'}")
    return 1 if failures else 0


_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.localagent.up</string>
  <key>ProgramArguments</key>
  <array><string>{localagent}</string><string>up</string></array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{home}/autostart.log</string>
  <key>StandardErrorPath</key><string>{home}/autostart.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{path}</string></dict>
</dict></plist>
"""


_XDG_DESKTOP = """[Desktop Entry]
Type=Application
Name=localagent up
Exec={localagent} up
X-GNOME-Autostart-enabled=true
"""


def _autostart_windows(args, localagent_bin: str) -> int:
    bat = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                       "Microsoft", "Windows", "Start Menu", "Programs",
                       "Startup", "localagent-up.bat")
    if args.remove:
        if os.path.exists(bat):
            os.remove(bat)
        print("autostart removed")
        return 0
    os.makedirs(os.path.dirname(bat), exist_ok=True)
    with open(bat, "w", encoding="utf-8") as f:
        f.write(f'@echo off\r\nstart "" /min "{localagent_bin}" up\r\n')
    print(f"autostart installed: {bat} (services start at login)")
    return 0


def _autostart_linux(args, localagent_bin: str) -> int:
    desktop = os.path.join(os.path.expanduser("~"), ".config", "autostart",
                           "localagent.desktop")
    if args.remove:
        if os.path.exists(desktop):
            os.remove(desktop)
        print("autostart removed")
        return 0
    os.makedirs(os.path.dirname(desktop), exist_ok=True)
    with open(desktop, "w", encoding="utf-8") as f:
        f.write(_XDG_DESKTOP.format(localagent=localagent_bin))
    print(f"autostart installed: {desktop} (services start at login)")
    return 0


def cmd_autostart(args) -> int:
    """Install/remove a login-time `localagent up`: launchd on macOS, the
    Startup folder on Windows, XDG autostart on Linux."""
    localagent_bin = _script_path("localagent")
    if sys.platform == "win32":
        return _autostart_windows(args, localagent_bin)
    if sys.platform != "darwin":
        return _autostart_linux(args, localagent_bin)
    plist_path = os.path.join(os.path.expanduser("~"), "Library",
                              "LaunchAgents", "com.localagent.up.plist")
    if args.remove:
        subprocess.run(["launchctl", "unload", plist_path], check=False,
                       capture_output=True)
        if os.path.exists(plist_path):
            os.remove(plist_path)
        print("autostart removed")
        return 0
    os.makedirs(os.path.dirname(plist_path), exist_ok=True)
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(_PLIST.format(localagent=localagent_bin, home=home_dir(),
                              path=os.environ.get("PATH", "/usr/bin:/bin")))
    subprocess.run(["launchctl", "unload", plist_path], check=False,
                   capture_output=True)
    result = subprocess.run(["launchctl", "load", plist_path], check=False,
                            capture_output=True, text=True)
    if result.returncode:
        print(f"wrote {plist_path} but launchctl load failed: {result.stderr.strip()}")
        return 1
    print(f"autostart installed: {plist_path} (services start at login)")
    return 0


def cmd_demo_repo(args) -> int:
    """Materialize a bundled sample repo (stubbed function + failing tests)
    into a fresh git repo — the safe target for demoing delegated tasks."""
    samples_root = _assets() / "samples"
    available = sorted(p.name for p in samples_root.iterdir() if p.is_dir())
    if args.name not in available:
        print(f"unknown sample '{args.name}' — available: {', '.join(available)}",
              file=sys.stderr)
        return 1
    dest = os.path.abspath(args.dest or os.path.join(".", f"demo-{args.name}"))
    if os.path.exists(dest) and os.listdir(dest):
        print(f"refusing to write into non-empty directory: {dest}", file=sys.stderr)
        return 1
    with importlib.resources.as_file(samples_root / args.name) as src:
        shutil.copytree(src, dest, dirs_exist_ok=True)
    # A real git repo, so the wrapper's diff/status reporting works.
    for git_args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.name=demo", "-c", "user.email=demo@localagent",
                      "commit", "-q", "-m", "demo starting state"]):
        subprocess.run(["git", "-C", dest, *git_args], check=False,
                       capture_output=True)
    recipe = os.path.join(home_dir(), "plan-and-delegate.yaml")
    # `uv run --with pytest` needs no pre-installed pytest on the machine —
    # uv is already a stack prerequisite, python alone may lack pytest.
    verify = "uv run --with pytest pytest -q"
    print(f"sample '{args.name}' ready at: {dest}")
    print(f"starting state: cd {dest} && {verify}   (tests fail by design)")
    print("run the agent on it:")
    print(f"  goose run --recipe {recipe} \\")
    print(f"    --params task='Make all tests pass. Verify with: {verify}' \\")
    print(f"    --params repo_path={dest}")
    return 0


def cmd_report(args) -> int:
    from .audit import audit_dir
    from .report import load_events, to_csv, to_text, weekly_metrics

    rows = weekly_metrics(load_events(audit_dir()))
    print(to_csv(rows) if args.csv else to_text(rows))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="localagent",
        description="Private coding agent: Goose orchestrator + OpenHands "
                    "implementer + shared persistent memory. All models on "
                    "AWS Bedrock (Claude/Nova).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="materialize configs + check dependencies")
    sub.add_parser("up", help="start the memory stack (docker)")
    sub.add_parser("down", help="stop services")
    sub.add_parser("goose-setup", help="render Goose config + link preferences")
    sub.add_parser("doctor", help="health-check the whole setup")
    report = sub.add_parser("report", help="flywheel metrics (escalation/playbook trends)")
    report.add_argument("--csv", action="store_true", help="emit CSV instead of a table")
    demo = sub.add_parser("demo-repo",
                          help="materialize a sample repo with failing tests "
                               "(textstats, then csvstats for playbook reuse)")
    demo.add_argument("name", help="sample name (e.g. textstats, csvstats)")
    demo.add_argument("dest", nargs="?", default="",
                      help="target directory (default: ./demo-<name>)")
    auto = sub.add_parser("autostart", help="start services at login (launchd)")
    auto.add_argument("--remove", action="store_true", help="uninstall the launch agent")
    args = parser.parse_args()
    return {
        "init": cmd_init, "up": cmd_up, "down": cmd_down,
        "goose-setup": cmd_goose_setup, "doctor": cmd_doctor,
        "report": cmd_report, "autostart": cmd_autostart,
        "demo-repo": cmd_demo_repo,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
