import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGES = ["core","engine","terminal","dashboard","ai","data","historical","screener","backtest","backtest-engine","integration","automation","ditto"]

def test_root_files():
    for f in ["CLAUDE.md","AGENTS.md","README.md","VERSION","LICENSE",".gitignore",".env.example","flint.toml","Makefile"]:
        assert os.path.exists(os.path.join(ROOT, f)), f"Missing: {f}"

def test_packages():
    for pkg in PACKAGES:
        d = os.path.join(ROOT, "packages", pkg)
        assert os.path.isdir(d), f"Missing: {pkg}"
        assert os.path.exists(os.path.join(d, "CLAUDE.md"))
        assert os.path.exists(os.path.join(d, "AGENTS.md"))

def test_version():
    with open(os.path.join(ROOT, "VERSION")) as f:
        v = f.read().strip()
    # Strip pre-release suffix (-dev, -alpha, -beta, -rc.N) then check 3-part semver
    base = v.split("-")[0]
    assert len(base.split(".")) == 3
