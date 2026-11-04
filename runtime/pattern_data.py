"""Exact-timestamp chord events, causal history, and exhaustive event chunks."""
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re

import numpy as np
from torch.utils.data import Dataset

from audio_features import FeatureStore, sha256_file

CONTEXT = 32
CORE = 96
AUDIO_OFFSETS = np.array([-20, -5, 0, 5, 20])
EVENT_DTYPE = np.dtype([('time', '<f8'), ('heads', 'u1'), ('holds', 'u1'),
                        ('duration', '<f4', (7,)), ('state', '<f4', (14,)), ('shared', '?')])


def dan_style(row):
    name = ' '.join(str(row.get(k, '')) for k in ('title', 'version', 'osu_path'))
    return int(bool(re.search(r'(?<![A-Za-z])dan(?![A-Za-z])|\u6bb5\u4f4d', name, re.I)))


def encode_events(notes):
    times, inverse = np.unique([n[0] for n in notes], return_inverse=True)
    events = np.zeros(len(times), dtype=EVENT_DTYPE)
    events['time'] = times
    for i, (start, end, lane, kind) in zip(inverse, notes):
        bit = 1 << lane
        if events['heads'][i] & bit:
            raise ValueError('duplicate lane at exact timestamp')
        events['heads'][i] |= bit
        if kind == 'hold':
            events['holds'][i] |= bit
            events['duration'][i, lane] = np.log1p((end - start) / 1000)
    for lane in range(7):
        present = (events['heads'] & (1 << lane)) != 0
        previous = np.r_[-1, np.maximum.accumulate(np.where(present, np.arange(len(times)), -1))[:-1]]
        previous_time = times[np.maximum(previous, 0)]
        age = np.where(previous >= 0, (times - previous_time) / 1000, 60.)
        ends = times + np.expm1(events['duration'][:, lane].astype(float)) * 1000
        previous_end = np.r_[-np.inf, np.maximum.accumulate(np.where(present, ends, -np.inf))[:-1]]
        remaining = np.maximum(0., previous_end - times) / 1000
        # Float32 log-duration round trips can leave a few microseconds at release.
        remaining[remaining < .0001] = 0
        if np.any(present & (remaining > 0)):
            raise ValueError('overlapping source objects in one lane')
        events['state'][:, lane] = np.log1p(age)
        events['state'][:, 7 + lane] = np.log1p(remaining)
    for i in np.flatnonzero([int(m).bit_count() >= 2 for m in events['holds']]):
        selected = [(events['holds'][i] & (1 << k)) != 0 for k in range(7)]
        durations = np.expm1(events['duration'][i, selected].astype(float))
        events['shared'][i] = np.ptp(durations) <= .0011
    return events


def prepare(root=Path('data/patterns_v1'), features=Path('data/features')):
    root, features = Path(root), Path(features)
    signatures = {s: sha256_file(features / 'splits' / (s + '.jsonl')) for s in ('train', 'validation', 'test')}
    if root.exists():
        report = json.loads((root / 'report.json').read_text(encoding='utf-8'))
        if report['source_sha256'] != signatures or report['builder_sha256'] != sha256_file(__file__):
            raise ValueError('pattern cache mismatch; choose a fresh root')
        return report
    (root / 'events').mkdir(parents=True)
    report = {'source_sha256': signatures, 'builder_sha256': sha256_file(__file__),
              'features': str(features.resolve()), 'splits': {}, 'ln_upper_limit_s': None,
              'style_policy': 'All downloaded ready charts retained; dan names are a separate input condition.'}
    for split in signatures:
        rows = [json.loads(s) for s in (features / 'splits' / (split + '.jsonl')).read_text(encoding='utf-8').splitlines()]
        chunks, count, objects = [], 0, 0
        for ci, row in enumerate(rows):
            with gzip.open(row['chart_file'], 'rt', encoding='utf-8') as f:
                notes = json.load(f)['notes']
            events = encode_events(notes)
            path = root / 'events' / (row['chart_id'] + '.npy')
            np.save(path, events, allow_pickle=False)
            row.update(event_file=str(path.resolve()), event_count=len(events), dan_style=dan_style(row))
            chunks.extend((ci, start) for start in range(0, len(events), CORE))
            count += len(events)
            objects += len(notes)
            if (ci + 1) % 1000 == 0:
                print(f'{split}: {ci+1}/{len(rows)} charts packed', flush=True)
        (root / (split + '.json')).write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        np.save(root / (split + '_chunks.npy'), np.array(chunks, dtype=np.int32), allow_pickle=False)
        report['splits'][split] = {'charts': len(rows), 'events': count, 'objects': objects,
                                   'chunks': len(chunks), 'dan_charts': sum(r['dan_style'] for r in rows)}
    report['status'] = 'complete'
    (root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def audio_at_events(feature, times, mean, std):
    frames = np.floor(np.asarray(times) / 10 + .5).astype(np.int64)
    indices = frames[:, None] + AUDIO_OFFSETS
    valid = (indices >= 0) & (indices < len(feature))
    x = (np.asarray(feature[np.clip(indices, 0, len(feature)-1)], dtype=np.float32) - mean) / std
    x[~valid] = 0
    return x.reshape(len(times), -1)


def event_inputs(events):
    n = len(events)
    prev_heads = np.r_[0, events['heads'][:-1]].astype(np.int64)
    prev_holds = np.r_[0, events['holds'][:-1]].astype(np.int64)
    prev_duration = np.vstack([np.zeros((1, 7)), events['duration'][:-1]]).astype(np.float32)
    times = events['time']
    previous_gap = np.r_[0, np.diff(times)] / 1000
    next_gap = np.r_[np.diff(times), 0] / 1000
    next2_gap = np.r_[times[2:] - times[:-2], np.zeros(min(2, n))] / 1000
    numbers = np.concatenate([events['state'], prev_duration,
                              np.log1p(np.stack([previous_gap, next_gap, next2_gap], axis=1))], axis=1).astype(np.float32)
    return prev_heads, prev_holds, numbers


class PatternDataset(Dataset):
    def __init__(self, root='data/patterns_v1', split='train'):
        self.root = Path(root)
        self.report = json.loads((self.root / 'report.json').read_text(encoding='utf-8'))
        self.rows = json.loads((self.root / (split + '.json')).read_text(encoding='utf-8'))
        self.chunks = np.load(self.root / (split + '_chunks.npy'), allow_pickle=False)
        self.store = FeatureStore(self.report['features'])

    def __len__(self):
        return len(self.chunks)

    @lru_cache(maxsize=16)
    def chart(self, ci):
        events = np.load(self.rows[ci]['event_file'], allow_pickle=False)
        return events, event_inputs(events)

    @lru_cache(maxsize=8)
    def feature(self, path):
        return np.load(path, mmap_mode='r', allow_pickle=False)

    def __getitem__(self, index):
        ci, start = (int(v) for v in self.chunks[index])
        row = self.rows[ci]
        events, inputs = self.chart(ci)
        first, end = max(0, start - CONTEXT), min(len(events), start + CORE)
        size = end - first
        total = CONTEXT + CORE
        feature = self.feature(str(self.store.root / row['feature_file']))
        audio = np.zeros((total, 640), dtype=np.float32)
        audio[:size] = audio_at_events(feature, events['time'][first:end], self.store.mean, self.store.std)
        sample = {'audio': audio}
        for key, array in zip(('prev_heads', 'prev_holds', 'numbers'), inputs):
            out = np.zeros((total,) + array.shape[1:], dtype=array.dtype)
            out[:size] = array[first:end]
            sample[key] = out
        for key in ('heads', 'holds', 'duration', 'shared'):
            array = events[key]
            out = np.zeros((total,) + array.shape[1:], dtype=np.float32 if key == 'duration' else np.int64)
            out[:size] = array[first:end]
            sample[key] = out
        mask = np.zeros(total, dtype=bool)
        mask[start-first:size] = True
        sample.update(mask=mask, stars=np.float32(row['star_rating']), keys=row['key_count'],
                      style=row['dan_style'], chunk_id=index, core_events=int(mask.sum()))
        return sample


if __name__ == '__main__':
    print(json.dumps(prepare(), indent=2))
