"""Collect installed dependency versions and available upstream license texts."""
from importlib import metadata
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'build' / 'licenses'
DEST.mkdir(parents=True, exist_ok=True)
python_packages = []
for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
    name = distribution.metadata['Name']
    python_packages.append({'name': name, 'version': distribution.version,
                            'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License', '')})
    for relative in distribution.files or []:
        if any(word in relative.name.lower() for word in ('license', 'copying', 'copyright', 'notice')):
            source = distribution.locate_file(relative)
            if source.is_file():
                target = DEST / 'python' / name / str(relative).replace('../', '')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
node_packages = []
lock = json.loads((ROOT/'frontend/package-lock.json').read_text())
for relative, info in lock['packages'].items():
    if not relative:
        continue
    name = relative.split('node_modules/')[-1]
    node_packages.append({'name': name, 'version': info.get('version'), 'license': info.get('license'), 'development': info.get('dev',False)})
    folder = ROOT/'frontend'/relative
    for source in folder.glob('*'):
        if source.is_file() and any(word in source.name.lower() for word in ('license', 'copying', 'copyright', 'notice')):
            target = DEST/'npm'/relative/source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source,target)
(DEST/'dependencies.json').write_text(json.dumps({'python': python_packages, 'npm': node_packages},indent=2)+'\n')
shutil.copy2(ROOT/'THIRD_PARTY_NOTICES.md',DEST/'THIRD_PARTY_NOTICES.md')
print(f'Collected notices for {len(python_packages)} Python and {len(node_packages)} npm distributions.')
