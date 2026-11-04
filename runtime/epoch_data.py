"""Explicit full-training-set segment index with auditable note coverage."""
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path

import numpy as np
from torch.utils.data import Dataset

from audio_features import FeatureStore, sha256_file
from mania_frames import FrameSpec

NOTE_DTYPE = np.dtype([('frame', '<i4'), ('lane', 'u1'), ('hold', '?'), ('duration', '<f4')])


def encode_chart(notes):
    """Retain all objects; report any one-frame collision displacement explicitly."""
    packed = np.zeros(len(notes), dtype=NOTE_DTYPE)
    previous = [-1] * 7
    adjustments = []
    for i, (start, end, lane, kind) in enumerate(notes):
        nominal = int(math.floor(start / 10 + .5))
        frame = max(nominal, previous[lane] + 1)
        if frame - nominal > 1:
            raise ValueError('collision needs more than one frame; cannot silently encode it')
        if frame != nominal:
            adjustments.append({'object_index': i, 'source_start_ms': start, 'lane': lane,
                                'nominal_frame': nominal, 'training_frame': frame,
                                'error_ms': frame * 10 - start})
        previous[lane] = frame
        packed[i] = (frame, lane, kind == 'hold', math.log1p((end - start) / 1000) if kind == 'hold' else 0.)
    packed.sort(order=['frame', 'lane'])
    return packed, adjustments


def prepare_epoch_index(features, output):
    features, output = Path(features), Path(output)
    source = features / 'splits' / 'train.jsonl'
    fingerprint = sha256_file(source)
    if output.exists():
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        if report['status'] != 'complete' or report['source_train_sha256'] != fingerprint or report['builder_sha256'] != sha256_file(__file__):
            raise ValueError('existing epoch index differs; choose a new directory')
        return report
    output.mkdir(parents=True)
    (output / 'labels').mkdir()
    rows = [json.loads(s) for s in source.read_text(encoding='utf-8').splitlines()]
    segments, metadata, adjustments = [], [], []
    object_count, ln_count, frames = 0, 0, 0
    for chart_index, row in enumerate(rows):
        if row['split'] != 'train' or row['status'] != 'ready':
            raise ValueError('only ready training rows may enter the epoch')
        with gzip.open(row['chart_file'], 'rt', encoding='utf-8') as f:
            chart = json.load(f)
        if chart['chart_id'] != row['chart_id'] or len(chart['notes']) != row['object_count']:
            raise ValueError('source chart does not match training manifest')
        labels, changed = encode_chart(chart['notes'])
        for item in changed:
            adjustments.append(dict(item, chart_id=row['chart_id'], osu_path=row['osu_path']))
        count = max(row['feature_frames'], int(labels['frame'].max()) + 1)
        path = output / 'labels' / (row['chart_id'] + '.npy')
        np.save(path, labels, allow_pickle=False)
        metadata.append(dict(row, label_file=str(path.resolve()), supervision_frames=count,
                             label_sha256=sha256_file(path)))
        segments.extend((chart_index, start) for start in range(0, count, 400))
        object_count += len(labels)
        ln_count += int(labels['hold'].sum())
        frames += count
        if (chart_index + 1) % 1000 == 0:
            print(f'Indexed {chart_index+1}/{len(rows)} charts', flush=True)
    index_path = output / 'segments.npy'
    np.save(index_path, np.asarray(segments, dtype=np.int32), allow_pickle=False)
    (output / 'charts.json').write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
    report = {'status': 'complete', 'charts': len(rows), 'segments': len(segments),
              'source_train_sha256': fingerprint, 'features_path': str(features.resolve()),
              'builder_sha256': sha256_file(__file__), 'segments_sha256': sha256_file(index_path),
              'charts_sha256': sha256_file(output / 'charts.json'),
              'supervision_frames': frames, 'supervision_hours': frames * .01 / 3600,
              'objects': object_count, 'ln_objects': ln_count, 'collision_adjustments': adjustments,
              'core_frames': 400, 'context_frames': 200,
              'definition': 'Every training-chart frame is supervised once; the final core is masked to its real length. All note heads are included.'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'collision_adjustments'}, indent=2), flush=True)
    return report


class FullEpochDataset(Dataset):
    def __init__(self, root, seed=2026):
        self.root = Path(root)
        self.report = json.loads((self.root / 'report.json').read_text(encoding='utf-8'))
        self.rows = json.loads((self.root / 'charts.json').read_text(encoding='utf-8'))
        self.segments = np.load(self.root / 'segments.npy', allow_pickle=False)
        self.order = np.random.default_rng(seed).permutation(len(self.segments))
        self.store = FeatureStore(self.report['features_path'])
        self.spec = FrameSpec()

    def __len__(self):
        return len(self.segments)

    @lru_cache(maxsize=32)
    def labels(self, chart_index):
        return np.load(self.rows[chart_index]['label_file'], mmap_mode='r', allow_pickle=False)

    @lru_cache(maxsize=16)
    def features(self, path):
        return np.load(path, mmap_mode='r', allow_pickle=False)

    def __getitem__(self, ordered_index):
        segment_id = int(self.order[ordered_index])
        chart_index, core = (int(v) for v in self.segments[segment_id])
        row = self.rows[chart_index]
        first = core - self.spec.context_frames
        labels = self.labels(chart_index)
        begin, end = np.searchsorted(labels['frame'], [first - 2, first + self.spec.frames + 2])
        selected = labels[begin:end]
        local = selected['frame'].astype(np.int64) - first
        lanes = selected['lane'].astype(np.int64)
        valid_heads = (local >= 0) & (local < self.spec.frames)
        onset, heads, hold, duration = [np.zeros((self.spec.frames, 7), dtype=np.float32) for _ in range(4)]
        positions = (local[valid_heads], lanes[valid_heads])
        heads[positions] = 1
        hold[positions] = selected['hold'][valid_heads]
        duration[positions] = selected['duration'][valid_heads]
        for delta, value in ((-2, .15), (-1, .6), (0, 1.), (1, .6), (2, .15)):
            at = local + delta
            valid = (at >= 0) & (at < self.spec.frames)
            np.maximum.at(onset, (at[valid], lanes[valid]), value)
        count = min(self.spec.core_frames, row['supervision_frames'] - core)
        loss_mask = np.zeros(self.spec.frames, dtype=bool)
        loss_mask[self.spec.context_frames:self.spec.context_frames + count] = True
        feature = self.features(str(self.store.root / row['feature_file']))
        x = np.zeros((self.spec.frames, 128), dtype=np.float32)
        valid = np.zeros(self.spec.frames, dtype=bool)
        a, b = max(0, first), min(len(feature), first + self.spec.frames)
        if a < b:
            x[a-first:b-first] = (np.asarray(feature[a:b], dtype=np.float32) - self.store.mean) / self.store.std
            valid[a-first:b-first] = True
        if not valid.any():
            raise ValueError('fully padded audio context cannot be trained')
        core_objects = int(((selected['frame'] >= core) & (selected['frame'] < core + count)).sum())
        return {'features': x, 'valid': valid, 'onset': onset, 'heads': heads, 'hold': hold,
                'duration': duration, 'any_onset': onset.max(axis=1), 'loss_mask': loss_mask,
                'stars': np.float32(row['star_rating']), 'keys': row['key_count'],
                'segment_id': segment_id, 'chart_index': chart_index, 'core_objects': core_objects,
                'core_frames': count}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features', type=Path, default=Path('data/features'))
    parser.add_argument('--output', type=Path, default=Path('data/epoch_v2'))
    args = parser.parse_args()
    prepare_epoch_index(args.features, args.output)
