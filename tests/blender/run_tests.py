# SPDX-License-Identifier: GPL-3.0-or-later
"""Run synthetic integration tests in a fresh, background Blender process.

blender --background --factory-startup --python-exit-code 1 --python \
    tests/blender/run_tests.py -- --output tests/output/generality.json
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys

import bpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Write the JSON report to this path')
    arguments = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    options = parser.parse_args(arguments)

    test_directory = Path(__file__).resolve().parent
    repository = test_directory.parents[1]
    # This runner belongs to an isolated --factory-startup process. Refuse a
    # registered copy so that accidentally enabled installed code is never tested.
    if hasattr(bpy.types.Object, 'fnf_settings'):
        raise RuntimeError('Face Normal Flatten is already registered; use --factory-startup')
    for name in list(sys.modules):
        if name == 'face_normal_flatten' or name.startswith('face_normal_flatten.'):
            del sys.modules[name]
    sys.path[:0] = [str(repository), str(test_directory)]
    importlib.invalidate_caches()
    addon = importlib.import_module('face_normal_flatten')
    expected = repository / 'face_normal_flatten' / '__init__.py'
    if Path(addon.__file__).resolve() != expected:
        raise RuntimeError(f'Expected the checkout add-on at {expected}, got {addon.__file__}')

    registered = False
    try:
        addon.register()
        registered = True
        generality = importlib.import_module('test_generality')
        if Path(generality.__file__).resolve() != test_directory / 'test_generality.py':
            raise RuntimeError('The integration test module was imported from outside this checkout')
        report = generality.run(options.output)
        if not report['all_passed']:
            raise AssertionError('Synthetic Blender integration tests did not all pass')
        dynamic = importlib.import_module('test_dynamic')
        dynamic_report = dynamic.run((options.output or repository / 'tests/output/generality.json').with_name('dynamic.json'))
        if not dynamic_report['all_passed']:
            failures = [c for c in dynamic_report['cases'] if not c['passed']]
            raise AssertionError(json.dumps(failures, ensure_ascii=False))
        print(json.dumps({'status': 'passed', 'case_count': report['case_count'],
                          'passed_count': report['passed_count'], 'report': report['output_path'],
                          'dynamic_passed':dynamic_report['passed_count']},
                         ensure_ascii=False))
    finally:
        if registered:
            addon.unregister()


if __name__ == '__main__':
    main()
