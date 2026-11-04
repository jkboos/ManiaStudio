"""Validate generated files independently; report difficulty error separately."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from audio_features import sha256_file
from osu_export import calculated_stars, validate_notes
from prepare_dataset import parse_chart


def validate(root):
    report = json.loads((root / 'generation_report.json').read_text(encoding='utf-8'))
    if report['status'] != 'complete':
        raise ValueError('generation did not finish')
    path = root / report['osu_file']
    chart = parse_chart(path)
    if chart['errors'] or chart['key_count'] != report['keys']:
        raise ValueError(f'invalid chart: {chart["errors"]}')
    validate_notes(chart['notes'], chart['key_count'])
    if not chart['notes']:
        raise ValueError('empty chart')
    if max(n[1] for n in chart['notes']) > report['audio_duration_s'] * 1000:
        raise ValueError('notes extend beyond audio')
    taps = sum(n[3] == 'tap' for n in chart['notes'])
    holds = sum(n[3] == 'hold' for n in chart['notes'])
    if taps != report['note_count'] or holds != report['ln_count']:
        raise ValueError('object count mismatch')
    audio = root / chart['general']['AudioFilename']
    if sha256_file(audio) != report['audio_sha256']:
        raise ValueError('packaged audio differs from input')
    timing = chart['timing_points']
    if len(timing) != 1 or not timing[0]['uninherited']:
        raise ValueError('expected fixed BPM with no SV changes')
    with zipfile.ZipFile(root / report['osz_file']) as z:
        if z.testzip() is not None or set(z.namelist()) != {path.name, audio.name}:
            raise ValueError('invalid .osz archive')
        if z.read(path.name) != path.read_bytes() or hashlib.sha256(z.read(audio.name)).hexdigest() != report['audio_sha256']:
            raise ValueError('archive contents differ')
    stars = calculated_stars(path.read_text(encoding='utf-8'))
    if abs(stars - report['actual_stars']) > 1e-9:
        raise ValueError('star rating mismatch')
    result = {'structure_valid': True, 'keys': chart['key_count'], 'taps': taps, 'holds': holds,
              'target_stars': report['target_stars'], 'actual_stars': stars,
              'absolute_star_error': abs(stars - report['target_stars']),
              'fixed_bpm': 60000 / timing[0]['beat_length_ms'], 'offset_ms': timing[0]['time_ms'],
              'timing_accuracy_verified': False, 'playability_verified': False,
              'checks': ['note/LN structure and lane overlap', 'objects within audio duration',
                         'one BPM point, no SV changes', 'audio identity and .osz integrity',
                         'rosu-pp-py difficulty recalculation']}
    (root / 'validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    validate(parser.parse_args().root)
