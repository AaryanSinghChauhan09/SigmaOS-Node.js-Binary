"""Node.js binary distribution manager for SigmaOS-Node.js-Binary
(inspired by Linux Mint nodejs distributions).

Principles: the version manifest is the single source of truth (parse once,
select many), plan/execute separation (download, extract and symlink argv are
built pure -- self_test never touches the network or ~/.local), fail-fast on
malformed manifests, deterministic semver-descending ordering.
"""
import argparse, json, os, re, shlex, subprocess, sys

ENGINE = {
    "name": "sigma-node",
    "summary": "Node.js binary distribution manager (manifest, install, mirrors)",
    "language": "python",
    "verbs": ["list", "install-plan", "use", "mirror-plan"],
    "principles": ["Separation of Concerns", "Defensive Programming",
                   "Fail-Fast", "DRY", "KISS", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-node list --manifest index.json --lts
v22.11.0  lts=Jam   date=2024-11-20  npm=10.9.0
$ sigma-node install-plan v22.11.0 --arch x64 --mirror https://nodejs.org/dist
$ sigma-node use v22.11.0 --prefix ~/.local/share/sigma-node --shell fish
$ sigma-node mirror-plan https://npm.elemecdn.com --tool npm
"""

DEFAULT_MIRROR = "https://nodejs.org/dist"
DEFAULT_PREFIX = "~/.local/share/sigma-node"
ARCHES = ("x64", "arm64")

_VER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class NodeError(ValueError):
    pass


def norm_version(raw):
    """Normalise '22.11.0' / ' v22.11.0 ' -> 'v22.11.0'. Fail-fast otherwise."""
    if not isinstance(raw, str):
        raise NodeError(f"bad version: {raw!r}")
    m = _VER_RE.match(raw.strip())
    if not m:
        raise NodeError(f"bad version: {raw!r} (want MAJOR.MINOR.PATCH)")
    return "v%d.%d.%d" % tuple(int(g) for g in m.groups())


def parse_manifest(text):
    """Parse a Node dist index manifest (list, or {"versions": [...]})."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise NodeError(f"manifest is not valid JSON: {e}") from e
    if isinstance(data, dict):
        data = data.get("versions")
        if not isinstance(data, list):
            raise NodeError('manifest object needs a "versions" list')
    if not isinstance(data, list):
        raise NodeError("manifest must be a list of releases")
    out, seen = [], set()
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise NodeError(f"release #{i} is not an object")
        if "version" not in row:
            raise NodeError(f"release #{i} has no version")
        ver = norm_version(row["version"])
        if ver in seen:
            raise NodeError(f"duplicate release: {ver}")
        seen.add(ver)
        lts = row.get("lts", False)
        if not isinstance(lts, (bool, str)):
            raise NodeError(f"{ver}: bad lts field")
        npm = row.get("npm")
        if npm is not None and not isinstance(npm, str):
            raise NodeError(f"{ver}: bad npm field")
        out.append({"version": ver, "date": str(row.get("date", "")),
                    "lts": lts, "npm": npm})
    return out


def _semver_key(rel):
    return tuple(int(x) for x in rel["version"][1:].split("."))


def select(releases, lts_only=False, prefix=None, limit=None):
    """Filter + sort releases newest-first (semver descending)."""
    rows = list(releases)
    if lts_only:
        rows = [r for r in rows if r["lts"]]
    if prefix is not None:
        p = str(prefix).strip().lstrip("v")
        if not p:
            raise NodeError("empty version prefix")
        rows = [r for r in rows if r["version"][1:].startswith(p)]
    rows.sort(key=_semver_key, reverse=True)
    if limit is not None:
        if not isinstance(limit, int) or limit < 1:
            raise NodeError("limit must be a positive integer")
        rows = rows[:limit]
    return rows


def latest_lts(releases):
    rows = select(releases, lts_only=True, limit=1)
    return rows[0] if rows else None


def _check_mirror(mirror):
    m = str(mirror).strip().rstrip("/")
    if not m.startswith(("http://", "https://")) or len(m) < 12:
        raise NodeError(f"mirror must be an http(s) URL: {mirror!r}")
    return m


def install_plan(version, mirror=DEFAULT_MIRROR, arch="x64", prefix=DEFAULT_PREFIX,
                 tarball_dir="/tmp"):
    """Pure argv plan: mkdir -> curl -> tar -> symlink `current`."""
    ver = norm_version(version)
    m = _check_mirror(mirror)
    if arch not in ARCHES:
        raise NodeError(f"unknown arch {arch!r} (have: {', '.join(ARCHES)})")
    name = f"node-{ver}-linux-{arch}"
    url = f"{m}/{ver}/{name}.tar.xz"
    tarball = f"{tarball_dir.rstrip('/')}/{name}.tar.xz"
    steps = [
        {"argv": ["mkdir", "-p", prefix]},
        {"argv": ["curl", "-fL", "--retry", "3", "-o", tarball, url]},
        {"argv": ["tar", "-xJf", tarball, "-C", prefix]},
        {"argv": ["ln", "-sfn", f"{prefix}/{name}/bin", f"{prefix}/current"]},
    ]
    return {"version": ver, "arch": arch, "url": url,
            "sha256_url": url + ".sha256", "tarball": tarball, "steps": steps}


def use_plan(version, arch="x64", prefix=DEFAULT_PREFIX, shell="sh"):
    """Pure plan: repoint the `current` symlink + emit a shell env line."""
    ver = norm_version(version)
    if arch not in ARCHES:
        raise NodeError(f"unknown arch {arch!r} (have: {', '.join(ARCHES)})")
    if shell not in ("sh", "bash", "zsh", "fish"):
        raise NodeError(f"unknown shell {shell!r}")
    current = f"{prefix}/current"
    if shell == "fish":
        env_line = f'set -gx PATH "{current}/bin" $PATH'
    else:
        env_line = f'export PATH="{current}/bin:$PATH"'
    return {"version": ver, "prefix": prefix,
            "argv": ["ln", "-sfn", f"{prefix}/node-{ver}-linux-{arch}/bin", current],
            "verify_argv": [f"{current}/bin/node", "--version"],
            "env_line": env_line}


def mirror_plan(mirror, tool="npm"):
    """Pure plan for pointing npm (or the dist downloader) at a mirror."""
    m = _check_mirror(mirror)
    if tool == "npm":
        return {"mirror": m, "tool": tool,
                "argv": [["npm", "config", "set", "registry", m + "/"]],
                "env": []}
    if tool == "node":
        return {"mirror": m, "tool": tool, "argv": [],
                "env": [f'export NODE_MIRROR="{m}"',
                        f'export NPM_CONFIG_REGISTRY="{m}/"']}
    raise NodeError(f"unknown tool {tool!r} (npm|node)")


# --------------------------------------------------------------------------- #
#  Thin side-effecting layer (never exercised by self_test)
# --------------------------------------------------------------------------- #
def execute(steps, timeout=300):
    """Run planned argv steps in order. Returns the last CompletedProcess."""
    result = None
    for step in steps:
        result = subprocess.run(step["argv"], capture_output=True, text=True,
                                timeout=timeout)
        if result.returncode != 0:
            break
    return result


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"], description=ENGINE["summary"])
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="list releases from a version manifest")
    ls.add_argument("--manifest", required=True, help="path to index.json")
    ls.add_argument("--lts", action="store_true", help="LTS releases only")
    ls.add_argument("--prefix", default=None, help="version prefix, e.g. v20")
    ls.add_argument("--limit", type=int, default=None)
    ip = sub.add_parser("install-plan", help="build the download/extract argv")
    ip.add_argument("version")
    ip.add_argument("--mirror", default=DEFAULT_MIRROR)
    ip.add_argument("--arch", default="x64", choices=ARCHES)
    ip.add_argument("--prefix", default=DEFAULT_PREFIX)
    ip.add_argument("--tarball-dir", default="/tmp")
    up = sub.add_parser("use", help="plan switching `current` to a version")
    up.add_argument("version")
    up.add_argument("--arch", default="x64", choices=ARCHES)
    up.add_argument("--prefix", default=DEFAULT_PREFIX)
    up.add_argument("--shell", default="sh", choices=("sh", "bash", "zsh", "fish"))
    mp = sub.add_parser("mirror-plan", help="plan npm/node mirror configuration")
    mp.add_argument("mirror")
    mp.add_argument("--tool", default="npm", choices=("npm", "node"))
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "list":
            with open(args.manifest, "r", encoding="utf-8") as fh:
                releases = parse_manifest(fh.read())
            for r in select(releases, lts_only=args.lts, prefix=args.prefix,
                            limit=args.limit):
                lts = r["lts"] if isinstance(r["lts"], str) else (
                    "true" if r["lts"] else "-")
                print(f"{r['version']}  lts={lts}  date={r['date'] or '-'}  "
                      f"npm={r['npm'] or '-'}")
        elif args.cmd == "install-plan":
            plan = install_plan(args.version, args.mirror, args.arch,
                                args.prefix, args.tarball_dir)
            print(f"url {plan['url']}")
            for step in plan["steps"]:
                print(shlex.join(step["argv"]))
        elif args.cmd == "use":
            plan = use_plan(args.version, args.arch, args.prefix, args.shell)
            print(plan["env_line"])
            print(shlex.join(plan["argv"]))
            print("# verify: " + shlex.join(plan["verify_argv"]))
        elif args.cmd == "mirror-plan":
            plan = mirror_plan(args.mirror, args.tool)
            for line in plan["env"]:
                print(line)
            for argv in plan["argv"]:
                print(shlex.join(argv))
        return 0
    except (NodeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    import tempfile
    SAMPLE = """[
      {"version": "v22.11.0", "date": "2024-11-20", "lts": "Jam",   "npm": "10.9.0"},
      {"version": "v22.10.0", "date": "2024-10-16", "lts": false,   "npm": "10.9.0"},
      {"version": "v20.18.1", "date": "2024-12-11", "lts": "Iron",  "npm": "10.8.2"},
      {"version": "v18.20.4", "date": "2024-07-08", "lts": "Hydrogen","npm": "10.7.0"}
    ]"""
    # --- manifest parsing --------------------------------------------------
    rel = parse_manifest(SAMPLE)
    assert [r["version"] for r in rel] == ["v22.11.0", "v22.10.0",
                                           "v20.18.1", "v18.20.4"], rel
    assert rel[0]["lts"] == "Jam" and rel[1]["lts"] is False
    assert rel[2]["npm"] == "10.8.2"
    # dict wrapper (nodejs.org/dist/index.json shape)
    rel2 = parse_manifest('{"versions": [{"version": "21.0.0", "lts": false}]}')
    assert rel2[0]["version"] == "v21.0.0"
    for bad in ("not json", "{}", '"just a string"',
                '[{"date": "2024-01-01"}]',
                '[{"version": "22.0.0"}, {"version": "v22.0.0"}]',
                '[{"version": "22.0.0", "lts": 5}]',
                '[1, 2]'):
        try:
            parse_manifest(bad)
        except NodeError:
            pass
        else:
            raise AssertionError(f"manifest should have been rejected: {bad}")

    # --- selection (deterministic order) -----------------------------------
    assert [r["version"] for r in select(rel)] == \
        ["v22.11.0", "v22.10.0", "v20.18.1", "v18.20.4"]
    assert [r["version"] for r in select(rel, lts_only=True)] == \
        ["v22.11.0", "v20.18.1", "v18.20.4"]
    assert [r["version"] for r in select(rel, prefix="v20")] == ["v20.18.1"]
    assert [r["version"] for r in select(rel, prefix="20.18")] == ["v20.18.1"]
    assert [r["version"] for r in select(rel, limit=2)] == ["v22.11.0", "v22.10.0"]
    assert latest_lts(rel)["version"] == "v22.11.0"
    try:
        select(rel, limit=0)
    except NodeError:
        pass
    else:
        raise AssertionError("limit=0 not rejected")
    try:
        select(rel, prefix="v")
    except NodeError:
        pass
    else:
        raise AssertionError("empty prefix not rejected")

    # --- install plan (pure argv) ------------------------------------------
    plan = install_plan("22.11.0")
    assert plan["url"] == ("https://nodejs.org/dist/v22.11.0/"
                           "node-v22.11.0-linux-x64.tar.xz"), plan["url"]
    assert plan["sha256_url"].endswith(".tar.xz.sha256")
    argvs = [s["argv"] for s in plan["steps"]]
    assert argvs[0] == ["mkdir", "-p", DEFAULT_PREFIX]
    assert argvs[1][0] == "curl" and plan["url"] in argvs[1]
    assert argvs[2][0] == "tar" and "-xJf" in argvs[2]
    assert argvs[3][:2] == ["ln", "-sfn"]
    plan64 = install_plan("v22.11.0", arch="arm64", mirror="https://mirror.example/node/")
    assert plan64["url"].startswith("https://mirror.example/node/v22.11.0/node-v22.11.0-linux-arm64")
    for bad_call in ((install_plan, ("v22",)),
                     (install_plan, ("v22.11.0", "ftp://x.example")),
                     (install_plan, ("v22.11.0", "javascript:alert(1)")),
                     (install_plan, ("v22.11.0", DEFAULT_MIRROR, "riscv"))):
        try:
            bad_call[0](*bad_call[1])
        except NodeError:
            pass
        else:
            raise AssertionError(f"should have rejected: {bad_call}")

    # --- use plan -----------------------------------------------------------
    up = use_plan("v22.11.0", prefix="/opt/node", shell="fish")
    assert up["argv"] == ["ln", "-sfn", "/opt/node/node-v22.11.0-linux-x64/bin",
                          "/opt/node/current"], up["argv"]
    assert up["verify_argv"] == ["/opt/node/current/bin/node", "--version"]
    assert 'set -gx PATH "/opt/node/current/bin" $PATH' == up["env_line"]
    up = use_plan("v22.11.0", prefix="/opt/node", shell="zsh")
    assert up["env_line"].startswith('export PATH="/opt/node/current/bin:')
    try:
        use_plan("v22.11.0", shell="cmd.exe")
    except NodeError:
        pass
    else:
        raise AssertionError("unknown shell not rejected")

    # --- mirror plan --------------------------------------------------------
    mp = mirror_plan("https://npm.elemecdn.com", "npm")
    assert mp["argv"] == [["npm", "config", "set", "registry",
                           "https://npm.elemecdn.com/"]], mp["argv"]
    mn = mirror_plan("https://node.example/mirror/", "node")
    assert any("NODE_MIRROR" in line for line in mn["env"])
    assert mn["argv"] == []
    for bad in (("javascript:alert(1)", "npm"), ("https://ok.example", "pip")):
        try:
            mirror_plan(*bad)
        except NodeError:
            pass
        else:
            raise AssertionError(f"should have rejected: {bad}")

    # --- determinism + a round-trip through real files (tempfile only) ------
    assert install_plan("v20.18.1") == install_plan("v20.18.1")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "index.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE)
        with open(path, "r", encoding="utf-8") as fh:
            again = parse_manifest(fh.read())
        assert [r["version"] for r in select(again, lts_only=True)] == \
            ["v22.11.0", "v20.18.1", "v18.20.4"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
