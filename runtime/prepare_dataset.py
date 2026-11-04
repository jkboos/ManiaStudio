"""Build audited mania chart data. Source .osu/audio files are never modified."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import random
import sys
import time
import unicodedata

import numpy as np
import rosu_pp_py as rosu
import soundfile as sf

SCHEMA_VERSION = 1


def digest_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('non-finite number')
    return value


def parse_chart(path):
    """Times are absolute audio milliseconds, lanes zero-based, LN tails inclusive.

    A new note at precisely the previous LN tail is allowed. Sorting preserves
    simultaneous notes; no snapping, shifting, truncation, or repair is done.
    """
    sections = defaultdict(list)
    section = ''
    text = Path(path).read_text(encoding='utf-8-sig')
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        else:
            sections[section].append((line_no, line))
    info = {}
    for name in ('General', 'Metadata', 'Difficulty'):
        info[name] = dict(line.split(':', 1) for _, line in sections[name] if ':' in line)
        info[name] = {k.strip(): v.strip() for k, v in info[name].items()}
    if int(info['General'].get('Mode', 0)) != 3:
        raise ValueError('not native mania')
    keys = finite(info['Difficulty'].get('CircleSize', 0))
    if keys not in (4, 7):
        raise ValueError('key_count must be 4 or 7')
    keys = int(keys)
    notes, timing = [], []
    errors, warnings = Counter(), Counter()
    samples = set()
    for line_no, line in sections['HitObjects']:
        try:
            fields = line.split(',')
            x, start, flags = finite(fields[0]), finite(fields[2]), int(fields[3])
            if not 0 <= x <= 512:
                raise ValueError('x outside playfield')
            is_hold = bool(flags & 128)
            if flags & 10 or not (is_hold or flags & 1):
                raise ValueError('unsupported hitobject type')
            end = finite(fields[5].split(':')[0]) if is_hold else start
            if is_hold and end <= start:
                errors['non_positive_ln_duration'] += 1
            if start < 0:
                warnings['negative_start_time'] += 1
            sample_field = ':'.join(fields[5].split(':')[1:]) if is_hold else (fields[5] if len(fields) > 5 else '')
            sample_parts = sample_field.split(':', 4)
            if len(sample_parts) == 5 and sample_parts[4]:
                samples.add(sample_parts[4])
            notes.append([start, end, min(int(x * keys / 512), keys - 1), 'hold' if is_hold else 'tap'])
        except (ValueError, IndexError):
            errors['malformed_hitobject'] += 1
    if not notes:
        errors['empty_chart'] += 1
    if any(a[0] > b[0] for a, b in zip(notes, notes[1:])):
        warnings['objects_reordered'] += 1
    notes.sort(key=lambda n: (n[0], n[2], n[1], n[3]))
    previous = {}
    signatures = set()
    for start, end, lane, kind in notes:
        signature = (start, end, lane, kind)
        if signature in signatures:
            errors['duplicate_object'] += 1
        signatures.add(signature)
        if lane in previous:
            prev_start, prev_end = previous[lane]
            if start == prev_start or start < prev_end:
                errors['same_lane_overlap'] += 1
        old_end = previous.get(lane, (start, end))[1]
        previous[lane] = (start, max(old_end, end))
    for line_no, line in sections['TimingPoints']:
        try:
            fields = line.split(',')
            offset, beat_length = finite(fields[0]), finite(fields[1])
            uninherited = int(fields[6]) if len(fields) > 6 else 1
            meter = int(fields[2]) if len(fields) > 2 else 4
            if uninherited not in (0, 1) or (uninherited and beat_length <= 0) or meter <= 0:
                raise ValueError('invalid timing point')
            timing.append({'time_ms': offset, 'beat_length_ms': beat_length,
                           'uninherited': bool(uninherited), 'meter': meter, 'raw': line})
        except (ValueError, IndexError):
            errors['malformed_timing_point'] += 1
    timing.sort(key=lambda t: t['time_ms'])
    if not any(t['uninherited'] for t in timing):
        errors['missing_bpm_timing'] += 1
    return {'schema_version': SCHEMA_VERSION, 'key_count': keys,
            'note_columns': ['start_ms', 'end_ms', 'lane', 'type'], 'notes': notes,
            'timing_points': timing, 'metadata': info['Metadata'],
            'general': info['General'], 'difficulty': info['Difficulty'],
            'custom_samples': sorted(samples), 'errors': dict(errors), 'warnings': dict(warnings)}


def chart_stats(chart):
    notes = chart['notes']
    if not notes:
        return {}
    starts = [n[0] for n in notes]
    end = max(n[1] for n in notes)
    duration = (end - starts[0]) / 1000
    # Sliding half-open [start, start + 1000) windows, all chord notes count.
    right = 0
    peak = 0
    for left, start in enumerate(starts):
        while right < len(starts) and starts[right] < start + 1000:
            right += 1
        peak = max(peak, right - left)
    ln_count = sum(n[3] == 'hold' for n in notes)
    bpms = [60000 / t['beat_length_ms'] for t in chart['timing_points'] if t['uninherited']]
    return {'note_count': len(notes) - ln_count, 'ln_count': ln_count,
            'object_count': len(notes), 'ln_ratio': ln_count / len(notes),
            'first_note_ms': starts[0], 'last_end_ms': end, 'chart_duration_s': duration,
            'mean_nps': len(notes) / duration if duration > 0 else None,
            'peak_nps_1s': peak, 'bpm_min': min(bpms) if bpms else None,
            'bpm_max': max(bpms) if bpms else None,
            'timing_point_count': len(chart['timing_points']),
            'custom_sample_count': len(chart['custom_samples'])}


def audit_audio(path):
    result = {'audio_path': path}
    try:
        result['file_sha256'] = digest_file(path)
        with sf.SoundFile(path) as f:
            sample_rate, channels, expected = f.samplerate, f.channels, len(f)
            h = hashlib.sha256(f'{sample_rate}:{channels}:'.encode())
            frames, active, peak = 0, 0, 0.0
            for block in f.blocks(blocksize=65536, dtype='float32', always_2d=True):
                if not np.isfinite(block).all():
                    raise ValueError('non-finite decoded samples')
                h.update(block.astype('<f4', copy=False).tobytes())
                amplitude = np.max(np.abs(block), axis=1)
                frames += len(block)
                active += int(np.count_nonzero(amplitude > 1e-4))
                if len(block):
                    peak = max(peak, float(amplitude.max()))
            if not frames or frames != expected:
                raise ValueError(f'decoded frame count mismatch: {frames}/{expected}')
            result.update(sample_rate=sample_rate, channels=channels, frames=frames,
                          duration_s=frames / sample_rate, pcm_sha256=h.hexdigest(),
                          peak_amplitude=peak, active_sample_fraction=active / frames)
        result['status'] = 'ok'
    except Exception as exc:
        result.update(status='error', error=f'{type(exc).__name__}: {exc}')
    return result


class UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a, b):
        self.parent[self.find(b)] = self.find(a)


def group_and_split(records, seed):
    """Conservative transitive grouping; metadata may group different recordings."""
    uf, seen = UnionFind(len(records)), {}
    for i, record in enumerate(records):
        tokens = [('path', record['audio_path'].casefold())]
        for field in ('audio_sha256', 'pcm_sha256'):
            if record.get(field):
                tokens.append((field, record[field]))
        set_id = record.get('beatmap_set_id', '')
        if str(set_id).isdigit() and int(set_id) > 0:
            tokens.append(('set', str(set_id)))
        artist, title = normalized(record.get('artist', '')), normalized(record.get('title', ''))
        if artist and title:
            tokens.append(('song', artist, title))
        for token in tokens:
            if token in seen:
                uf.union(i, seen[token])
            else:
                seen[token] = i
    members = defaultdict(list)
    for i, r in enumerate(records):
        members[uf.find(i)].append(r)
    for group in members.values():
        group_id = hashlib.sha256('\n'.join(sorted(r['chart_id'] for r in group)).encode()).hexdigest()[:20]
        for r in group:
            r['song_group_id'] = group_id
    duplicates = {}
    for r in sorted(records, key=lambda r: r['chart_id']):
        if r['status'] != 'ready':
            continue
        key = (r['pcm_sha256'], r['chart_sha256'])
        if key in duplicates:
            r.update(status='duplicate', duplicate_of=duplicates[key])
        else:
            duplicates[key] = r['chart_id']
    group_ids = sorted({r['song_group_id'] for r in records if r['status'] == 'ready'})
    random.Random(seed).shuffle(group_ids)
    n = len(group_ids)
    # Guarantee all splits for >=3 groups. Approximate 80/10/10 by group count.
    n_test = max(1, round(n * .1)) if n >= 3 else 0
    n_val = max(1, round(n * .1)) if n >= 3 else 0
    n_train = n - n_test - n_val
    split_map = {g: ('train' if i < n_train else 'validation' if i < n_train + n_val else 'test')
                 for i, g in enumerate(group_ids)}
    for r in records:
        r['split'] = split_map.get(r['song_group_id'], '') if r['status'] == 'ready' else ''


def summarize(records, audio):
    ready = [r for r in records if r['status'] == 'ready']
    distribution = {}
    for keys in (4, 7):
        rr = [r for r in ready if r['key_count'] == keys]
        stars = sorted(r['star_rating'] for r in rr)
        distribution[str(keys)] = {
            'ready_charts': len(rr), 'splits': dict(Counter(r['split'] for r in rr)),
            'star_bins_floor': dict(sorted(Counter(str(math.floor(s)) for s in stars).items(), key=lambda v: int(v[0]))),
            'star_percentiles': dict(zip(['min', 'p10', 'p50', 'p90', 'max'], np.percentile(stars, [0, 10, 50, 90, 100]).tolist())) if stars else {},
            'no_ln': sum(r['ln_count'] == 0 for r in rr),
            'ln_at_least_half': sum(r['ln_ratio'] >= .5 for r in rr)}
    return {'input_charts': len(records), 'audio_paths': len(audio),
            'audio_status': dict(Counter(a['status'] for a in audio.values())),
            'unique_pcm_audio': len({a['pcm_sha256'] for a in audio.values() if a['status'] == 'ok'}),
            'chart_status': dict(Counter(r['status'] for r in records)),
            'errors': dict(Counter(e for r in records for e in r['errors'])),
            'review_reasons': dict(Counter(e for r in records for e in r['review_reasons'])),
            'warnings': dict(Counter(e for r in records for e in r['warnings'])),
            'ready_song_groups': len({r['song_group_id'] for r in ready}),
            'split_groups': {s: len({r['song_group_id'] for r in ready if r['split'] == s}) for s in ('train', 'validation', 'test')},
            'by_key_count': distribution,
            'limitations': ['Exact file/decoded PCM hashes do not identify all re-encodes, edits or rate changes.',
                           'Artist+title and positive beatmap set IDs conservatively group recordings; unrelated versions may be grouped.',
                           'Playable timing and musical quality still require listening and human review.',
                           'No Mel features, beat tracker, or trained model is included. Audio is referenced, not copied.']}


def verify_build(records):
    split_by_group, split_by_pcm = {}, {}
    charts_seen = set()
    for r in records:
        if r['status'] != 'ready':
            assert not r['split']
            continue
        assert r['chart_file'] and not r['errors'] and not r['review_reasons']
        assert math.isfinite(r['star_rating']) and r['star_rating'] >= 0
        assert r['split'] in ('train', 'validation', 'test')
        for cache, field in ((split_by_group, 'song_group_id'), (split_by_pcm, 'pcm_sha256')):
            key = r[field]
            assert key not in cache or cache[key] == r['split'], f'leakage: {field}'
            cache[key] = r['split']
        key = (r['pcm_sha256'], r['chart_sha256'])
        assert key not in charts_seen, 'duplicate training chart'
        charts_seen.add(key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('mania_dataset.csv'))
    parser.add_argument('--output', type=Path, default=Path('data/processed'))
    parser.add_argument('--limit', type=int, default=0, help='First N CSV rows for a smoke run; 0 means all')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--min-objects', type=int, default=50)
    parser.add_argument('--max-duration', type=float, default=900, help='Chart seconds; longer charts go to review')
    args = parser.parse_args()
    if args.workers < 1 or args.limit < 0 or args.min_objects < 1 or args.max_duration <= 0:
        parser.error('invalid numeric argument')
    with args.input.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not {'osu_path', 'audio_path', 'key_count', 'note_count', 'ln_count'} <= set(reader.fieldnames or []):
            parser.error('input CSV is missing required fields')
        rows = list(reader)
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        parser.error('empty dataset')
    if args.output.exists():
        parser.error('output already exists; choose a new --output directory to preserve prior builds')
    args.output.mkdir(parents=True)
    (args.output / 'charts').mkdir()
    (args.output / 'splits').mkdir()
    started = time.monotonic()
    config = {'schema_version': SCHEMA_VERSION, 'status': 'building',
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'input_path': str(args.input.resolve()), 'input_sha256': digest_file(args.input),
              'builder_sha256': digest_file(__file__), 'python': sys.version,
              'packages': {p: importlib.metadata.version(p) for p in ('rosu-pp-py', 'numpy', 'soundfile')},
              'libsndfile_version': sf.__libsndfile_version__,
              'difficulty': {'mods': 0, 'clock_rate': 1.0, 'lazer': False},
              'seed': args.seed, 'limit': args.limit, 'workers': args.workers,
              'min_objects': args.min_objects, 'max_chart_duration_s': args.max_duration,
              'audio_end_tolerance_ms': 250, 'split_group_ratios': [.8, .1, .1]}
    write_json(args.output / 'dataset_config.json', config)
    # Resolve CSV paths relative to the CSV directory, never relative to the output.
    for row in rows:
        for field in ('osu_path', 'audio_path'):
            path = Path(row[field])
            row[field] = str((args.input.resolve().parent / path).resolve())
    audio_paths = sorted({row['audio_path'] for row in rows})
    audio = {}
    print(f'Checking {len(audio_paths)} audio files with {args.workers} workers...', flush=True)
    last_progress = time.monotonic()
    with (args.output / 'audio_audit.jsonl').open('w', encoding='utf-8') as log:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(audit_audio, p): p for p in audio_paths}
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                audio[result['audio_path']] = result
                log.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + '\n')
                log.flush()
                if time.monotonic() - last_progress >= 5 or i == len(audio_paths):
                    print(f'Audio {i}/{len(audio_paths)} ({time.monotonic() - started:.1f}s)', flush=True)
                    last_progress = time.monotonic()
    records = []
    for i, row in enumerate(rows, 1):
        path = Path(row['osu_path'])
        chart_id = hashlib.sha256(str(path).casefold().encode('utf-8')).hexdigest()[:24]
        r = dict(row, chart_id=chart_id, status='excluded', errors=[], warnings=[], review_reasons=[], chart_file='')
        try:
            chart = parse_chart(path)
            r.update(chart_stats(chart))
            r['key_count'] = chart['key_count']
            meta = chart['metadata']
            r.update(title=meta.get('Title', ''), artist=meta.get('Artist', ''), creator=meta.get('Creator', ''),
                     version=meta.get('Version', ''), beatmap_set_id=meta.get('BeatmapSetID', ''), beatmap_id=meta.get('BeatmapID', ''))
            r['errors'].extend(chart['errors'])
            r['warnings'].extend(chart['warnings'])
            r['osu_sha256'] = digest_file(path)
            signature = json.dumps([chart['key_count'], chart['notes']], separators=(',', ':'))
            r['chart_sha256'] = hashlib.sha256(signature.encode()).hexdigest()
            if int(row['key_count']) != chart['key_count']:
                r['errors'].append('csv_key_count_mismatch')
            if r.get('note_count') != int(row['note_count']) or r.get('ln_count') != int(row['ln_count']):
                r['errors'].append('csv_object_count_mismatch')
            referenced_audio = (path.parent / chart['general'].get('AudioFilename', '').replace('\\', '/')).resolve()
            if referenced_audio != Path(row['audio_path']):
                r['errors'].append('csv_audio_path_mismatch')
            a = audio[row['audio_path']]
            r['audio_sha256'] = a.get('file_sha256', '')
            r['pcm_sha256'] = a.get('pcm_sha256', '')
            if a['status'] != 'ok':
                r['errors'].append('audio_decode_failed')
            else:
                r['audio_duration_s'] = a['duration_s']
                if a['peak_amplitude'] <= 1e-6:
                    r['errors'].append('silent_audio')
                elif a['active_sample_fraction'] < .1:
                    r['review_reasons'].append('mostly_silent_audio')
                if r.get('last_end_ms', 0) > a['duration_s'] * 1000 + 250:
                    r['review_reasons'].append('notes_beyond_audio')
            if r.get('object_count', 0) < args.min_objects:
                r['review_reasons'].append('too_few_objects')
            if r.get('chart_duration_s', 0) > args.max_duration:
                r['review_reasons'].append('long_chart')
            if 'negative_start_time' in r['warnings']:
                r['review_reasons'].append('negative_start_time')
            if not r['errors']:
                beatmap = rosu.Beatmap(path=str(path))
                if beatmap.is_suspicious():
                    r['review_reasons'].append('rosu_suspicious')
                else:
                    if beatmap.n_objects != r['object_count'] or beatmap.n_holds != r['ln_count']:
                        r['errors'].append('rosu_object_count_mismatch')
                    stars = rosu.Difficulty(**config['difficulty']).calculate(beatmap).stars
                    if not math.isfinite(stars) or stars < 0:
                        r['errors'].append('invalid_star_rating')
                    else:
                        r['star_rating'] = stars
            r['status'] = 'excluded' if r['errors'] else 'review' if r['review_reasons'] else 'ready'
            chart['chart_id'] = chart_id
            chart['source_osu_path'] = str(path)
            chart['audio_path'] = row['audio_path']
            chart['audit'] = {k: r[k] for k in ('status', 'errors', 'warnings', 'review_reasons')}
            chart['star_rating'] = r.get('star_rating')
            r['chart_file'] = f'charts/{chart_id}.json.gz'
            # Fixed gzip timestamp makes the chart payload reproducible.
            payload = json.dumps(chart, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
            (args.output / r['chart_file']).write_bytes(gzip.compress(payload, mtime=0))
        except Exception as exc:
            r['status'] = 'excluded'
            r['errors'].append('chart_processing_failed')
            r['error_detail'] = f'{type(exc).__name__}: {exc}'
        records.append(r)
        if i % 250 == 0 or i == len(rows):
            print(f'Charts {i}/{len(rows)} ({time.monotonic() - started:.1f}s)', flush=True)
    group_and_split(records, args.seed)
    verify_build(records)
    fields = list(dict.fromkeys(k for r in records for k in r))
    with (args.output / 'manifest.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        for r in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in r.items()})
    for split in ('train', 'validation', 'test'):
        with (args.output / 'splits' / f'{split}.jsonl').open('w', encoding='utf-8') as f:
            for r in records:
                if r['split'] == split:
                    f.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n')
    report = summarize(records, audio)
    report['elapsed_seconds'] = round(time.monotonic() - started, 2)
    report['verification'] = 'passed: group isolation, exact PCM isolation, duplicate chart exclusion, ready-row validity'
    write_json(args.output / 'report.json', report)
    config.update(status='complete', completed_at_utc=datetime.now(timezone.utc).isoformat())
    write_json(args.output / 'dataset_config.json', config)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
