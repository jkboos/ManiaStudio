"""Exercise PowerShell interpreter selection without running an installer."""
from pathlib import Path
import subprocess
import pytest

APP=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('script',['Start.ps1','Setup.ps1'])
@pytest.mark.parametrize('checkout,local_venv,expected',[
    (True,False,'parent'),
    (True,True,'local'),
    (False,False,'bundled'),
    (False,True,'bundled'),
])
def test_existing_python_selection(tmp_path,script,checkout,local_venv,expected):
    app=tmp_path/'App with spaces';app.mkdir()
    paths={'bundled':app/'python/python.exe','parent':tmp_path/'.venv/Scripts/python.exe',
           'local':app/'.venv/Scripts/python.exe'}
    for kind,path in paths.items():
        if kind=='local' and not local_venv:continue
        path.parent.mkdir(parents=True,exist_ok=True);path.touch()
    if checkout:(app/'.git').mkdir()
    source=(APP/script).read_text(encoding='utf-8')
    # Run the actual selection code; stop before invoking Python or installing.
    marker='Push-Location -LiteralPath $appRoot' if script=='Start.ps1' else '& $python -m studio.dependencies install'
    prefix=source.split(marker)[0]
    probe=app/'probe.ps1'
    probe.write_text(prefix+'\nWrite-Output $python\n',encoding='utf-8')
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(probe)],
                          capture_output=True,text=True,check=True,timeout=15)
    assert Path(result.stdout.strip()).resolve()==paths[expected].resolve()
