import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.core.registry import ToolRegistry
from app.core.security import approved_install_command, compare_versions
from app.services.storage import Storage


def test_registry_loads():
    r=ToolRegistry(Path(__file__).parents[1]/"data/tools.json"); assert len(r.tools)==6; assert r.get("ngspice").category=="Circuit Simulation"

def test_version_compare():
    assert compare_versions("v1.2.0", "1.3.0")=="Update Available"; assert compare_versions("1.3.0", "1.3.0")=="Up to Date"; assert compare_versions(None,"1.0")=="Unknown Version"

def test_install_is_allowlisted():
    r=ToolRegistry(Path(__file__).parents[1]/"data/tools.json"); t=r.get("ngspice"); cmd=approved_install_command(t,"plan9"); assert cmd is None

def test_storage(tmp_path):
    s=Storage(tmp_path); s.log("test","Git","success","hello"); assert s.recent()[0]["message"]=="hello"; s.backup({"theme":"dark"},tmp_path/"b.json"); assert s.restore(tmp_path/"b.json")["theme"]=="dark"
