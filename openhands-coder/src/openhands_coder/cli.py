"""localagent — one-command setup and lifecycle for the private coding agent.

Install:  pipx install local-coding-agent   (or: uv tool install local-coding-agent)
Then:     localagent init      materialize configs into ~/.config/local-coding-agent
          localagent up        start memory stack + local model servers
          localagent goose-setup   render ~/.config/goose/config.yaml
          localagent doctor    health-check everything
          localagent down      stop services

Design: the pip package is the FRONT DOOR (like Claude Code's npm package);
heavy services stay in Docker; native pieces (goose, llama.cpp, docker) are
host installs this CLI checks for and explains. Inference is NOT containerized
on macOS — Docker has no Metal passthrough.

Everything operates on a home dir (default ~/.config/local-coding-agent,
override with LCA_HOME) holding .env, docker-compose.yml, litellm.yaml,
goose templates, and service logs. Stdlib only.
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


def _spawn(cmd: list[str], log_path: str) -> None:
    """Detached background process, output to a log file (nohup-equivalent)."""
    with open(log_path, "ab") as log:
        subprocess.Popen(
            cmd, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _bad(msg: str) -> None:
    print(f"  ✗ {msg}")


def _bin_dir() -> str:
    return os.path.dirname(sys.executable)


# ── commands ──────────────────────────────────────────────────────────


def cmd_init(_args) -> int:
    home = home_dir()
    os.makedirs(home, exist_ok=True)
    assets = _assets()
    materialize = {
        "docker-compose.yml": "docker-compose.yml",
        "litellm.yaml": "litellm.yaml",
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
        "docker": "Docker Desktop or OrbStack (memory stack)",
        "llama-server": "brew install llama.cpp (local models)",
        "goose": "brew install block-goose-cli (orchestrator)",
        "uvx": "curl -LsSf https://astral.sh/uv/install.sh | sh (gateway)",
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

    # 1. local model servers + gateway
    if not _up("http://localhost:8081/health"):
        _spawn(["llama-server", "-hf", "nomic-ai/nomic-embed-text-v1.5-GGUF",
                "--embeddings", "--port", "8081", "--host", "127.0.0.1"],
               os.path.join(home, "llama-embed.log"))
        print("starting embedder on :8081 (model downloads on first run)")
    if not _up("http://localhost:8082/health"):
        _spawn(["llama-server", "-hf", "bartowski/Qwen2.5-3B-Instruct-GGUF:Q4_K_M",
                "--port", "8082", "--host", "127.0.0.1", "-c", "4096"],
               os.path.join(home, "llama-llm.log"))
        print("starting extraction LLM on :8082 (model downloads on first run)")
    if not _up("http://localhost:4000/health/liveliness"):
        _spawn(["uvx", "--from", "litellm[proxy]", "litellm", "--config",
                os.path.join(home, "litellm.yaml"), "--port", "4000",
                "--host", "127.0.0.1"], os.path.join(home, "litellm.log"))
        print("starting LiteLLM gateway on :4000")

    # 2. memory stack containers
    subprocess.run(
        ["docker", "compose", "-f", os.path.join(home, "docker-compose.yml"),
         "--env-file", os.path.join(home, ".env"), "up", "-d"],
        check=True,
    )

    # 3. wait, then pin mem0 to the local gateway + ensure 768-dim collection
    print("waiting for services", end="", flush=True)
    deadline = time.time() + 1800  # first run downloads models
    while time.time() < deadline:
        if (_up("http://localhost:8765/docs") and _up("http://localhost:8081/health")
                and _up("http://localhost:8082/health")
                and _up("http://localhost:4000/health/liveliness")):
            break
        print(".", end="", flush=True)
        time.sleep(5)
    else:
        print("\nTIMED OUT — check logs in", home)
        return 1
    print(" ready")

    _http("http://localhost:8765/api/v1/config/mem0/llm", "PUT", {
        "provider": "openai",
        "config": {"model": "qwen2.5-3b-instruct", "temperature": 0.1,
                   "max_tokens": 2000, "api_key": "local"}})
    _http("http://localhost:8765/api/v1/config/mem0/embedder", "PUT", {
        "provider": "openai",
        "config": {"model": "text-embedding-3-small", "api_key": "local",
                   "embedding_dims": 768}})
    if not _up("http://localhost:6333/collections/openmemory"):
        _http("http://localhost:6333/collections/openmemory", "PUT",
              {"vectors": {"size": 768, "distance": "Cosine"}})
        print("pre-created qdrant collection (768-dim)")

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
    subprocess.run(["pkill", "-f", "llama-server -hf"], check=False)
    subprocess.run(["pkill", "-f", "litellm --config"], check=False)
    print("stopped")
    return 0


def cmd_goose_setup(_args) -> int:
    home = home_dir()
    env = load_env(home)
    if not env:
        print(f"No .env in {home} — run: localagent init", file=sys.stderr)
        return 1
    env.setdefault("MEMORY_NOTES_DIR",
                   os.path.join(os.path.expanduser("~"), ".local", "share",
                                "agent-memory"))
    env["PROJECT_ROOT"] = home
    env["CODER_BIN_DIR"] = _bin_dir()
    env["LOCAL_LLM_BASE_URL_HOST"] = env.get("LOCAL_LLM_BASE_URL", "").removesuffix("/v1")
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
    os.symlink(env["PREFERENCES_FILE"], hints)
    print(f"Linked {env['PREFERENCES_FILE']} -> {hints} (loaded every session)")
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
    check("embedder :8081", _up("http://localhost:8081/health"), "localagent up")
    check("extraction LLM :8082", _up("http://localhost:8082/health"), "localagent up")
    check("gateway :4000", _up("http://localhost:4000/health/liveliness"), "localagent up")

    print("[2/4] memory write+recall (end to end)")
    try:
        status, _ = _http(
            "http://localhost:8765/api/v1/memories/", "POST",
            {"user_id": user, "text": "doctor check: user likes green tea",
             "app": "doctor", "infer": True}, timeout=120)
        check("episodic memory write", status == 200)
    except (urllib.error.URLError, OSError) as exc:
        check("episodic memory write", False, str(exc))

    print("[3/4] agent components")
    check("openhands-coder on PATH",
          os.path.isfile(os.path.join(_bin_dir(), "openhands-coder")))
    check("memory-direct on PATH",
          os.path.isfile(os.path.join(_bin_dir(), "memory-direct")))
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


def cmd_autostart(args) -> int:
    """Install/remove a launchd agent that runs `localagent up` at login —
    services survive reboots without manual intervention."""
    plist_path = os.path.join(os.path.expanduser("~"), "Library",
                              "LaunchAgents", "com.localagent.up.plist")
    if args.remove:
        subprocess.run(["launchctl", "unload", plist_path], check=False,
                       capture_output=True)
        if os.path.exists(plist_path):
            os.remove(plist_path)
        print("autostart removed")
        return 0
    localagent_bin = os.path.join(_bin_dir(), "localagent")
    if not os.path.isfile(localagent_bin):
        localagent_bin = shutil.which("localagent") or localagent_bin
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
                    "implementer + shared persistent memory, fully local.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="materialize configs + check dependencies")
    sub.add_parser("up", help="start memory stack + local model servers")
    sub.add_parser("down", help="stop services")
    sub.add_parser("goose-setup", help="render Goose config + link preferences")
    sub.add_parser("doctor", help="health-check the whole setup")
    report = sub.add_parser("report", help="flywheel metrics (escalation/playbook trends)")
    report.add_argument("--csv", action="store_true", help="emit CSV instead of a table")
    auto = sub.add_parser("autostart", help="start services at login (launchd)")
    auto.add_argument("--remove", action="store_true", help="uninstall the launch agent")
    args = parser.parse_args()
    return {
        "init": cmd_init, "up": cmd_up, "down": cmd_down,
        "goose-setup": cmd_goose_setup, "doctor": cmd_doctor,
        "report": cmd_report, "autostart": cmd_autostart,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
