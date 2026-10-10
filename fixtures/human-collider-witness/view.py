"""Generate paired interactive Morphbench views of the exact installed witness files.

No fitting, file editing, game launch, VFS assumption or alternate geometry parser.
Use the installed Morphbench Python runtime (or a compatible source environment).
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod', type=Path, required=True, help='Installed human witness mod directory')
    parser.add_argument('--bench', type=Path, required=True, help='Morphbench directory containing mb.py')
    parser.add_argument('--out', type=Path, required=True, help='New external viewer directory')
    args = parser.parse_args()
    args.mod = args.mod.resolve()
    args.bench = args.bench.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((Path(__file__).parent/'artifact/manifest.json').read_text(encoding='utf-8'))
    expected = {row['path'].removeprefix('mod/'): row['sha256']
                for row in manifest['files'] if row['path'].startswith('mod/')}
    inputs = []
    for relative, checksum in expected.items():
        actual = args.mod/relative
        if digest(actual) != checksum:
            raise ValueError('Installed fixture differs from its manifest: '+str(actual))
        inputs.append({'path':str(actual), 'sha256':checksum})
    body = args.mod/'meshes/test_morphbench_human/body/femalebody_1.nif'
    results = {}
    for case in ('control', 'marker'):
        skeleton = args.mod/f'meshes/test_morphbench_human/{case}/skeleton_female.nif'
        hkx = skeleton.with_suffix('.hkx')
        common = [str(body), '--tri', '', '--skeleton', str(skeleton), '--hkx', str(hkx)]
        destination = args.out/(case+'.html')
        subprocess.run([sys.executable, str(args.bench/'mb.py'), 'web', *common,
                        '--out', str(destination), '--view', 'front', '--colliders'],
                       cwd=args.bench, check=True)
        output = subprocess.run([sys.executable, str(args.bench/'mb.py'), 'colliders', *common,
                                 '--json'], cwd=args.bench, check=True, capture_output=True,
                                 text=True, encoding='utf-8')
        results[case] = json.loads(output.stdout)
    (args.out/'colliders.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    # Both embedded pages are the stock interactive Morphbench presenter. This wrapper
    # adds only human labels and links; it never computes or transforms their geometry.
    (args.out/'index.html').write_text('''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Morphbench — контроль и левое бедро ×3</title>
<style>body{background:#1a1c20;color:#eee;font:16px system-ui;margin:16px}
a{color:#90cfff}main{display:grid;grid-template-columns:1fr 1fr;gap:12px}
iframe{width:100%;height:85vh;border:1px solid #555}h1{font-size:22px}h2{font-size:18px}
@media(max-width:1000px){main{grid-template-columns:1fr}}</style>
<h1>Morphbench: человеческий контроль и маркер</h1>
<p>Те же файлы тела, скелетов и HKX, что установлены в тестовом моде.
Капсулы включены. На виде спереди левое бедро находится справа на экране.
Поза инструмента исходная; игровой кадр может содержать анимацию.</p>
<main><section><h2>CONTROL FIT ×1 — обычные капсулы</h2>
<a href="control.html" target="_blank">Открыть контроль отдельно</a>
<iframe title="Morphbench CONTROL FIT x1" src="control.html"></iframe></section>
<section><h2>MARKER LEFT ×3 — увеличено левое бедро</h2>
<a href="marker.html" target="_blank">Открыть маркер отдельно</a>
<iframe title="Morphbench MARKER LEFT x3" src="marker.html"></iframe></section></main>
</html>''', encoding='utf-8')
    outputs = [{'path':str(p), 'sha256':digest(p)} for p in sorted(args.out.iterdir()) if p.is_file()]
    proof = {'installedMod':str(args.mod), 'bench':str(args.bench), 'bodyWeightPercent':100,
             'inputsVerifiedAgainstFixtureManifest':inputs, 'outputs':outputs,
             'skeletonMapping':{case:str(args.mod/f'meshes/test_morphbench_human/{case}/skeleton_female.nif')
                                for case in ('control','marker')},
             'morphsApplied':False, 'collidersVisible':True, 'gameLaunched':False}
    (args.out/'viewer-manifest.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'viewer':str(args.out/'index.html'), 'exactInstalledInputs':len(inputs)}))


if __name__ == '__main__':
    main()
