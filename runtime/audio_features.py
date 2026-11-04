"""Shared audio frontend for training caches and future audio-only inference."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.fft import rfft
from scipy.signal import resample_poly
from scipy.sparse import csr_matrix
import soundfile as sf


@dataclass(frozen=True)
class FeatureSpec:
    sample_rate: int = 24000
    hop_length: int = 240
    n_fft: int = 1024
    n_mels: int = 128
    f_min: float = 0.0
    f_max: float = 12000.0
    power_floor: float = 1e-10
    dtype: str = 'float16'
    mel_scale: str = 'htk'
    filter_normalization: str = 'unit_discrete_sum'
    window: str = 'periodic_hann'
    fft_normalization: str = 'divide_by_window_sum_before_power'
    center: bool = True
    pad_mode: str = 'constant_zero'
    resampler: str = 'scipy_resample_poly_kaiser_5'
    downmix: str = 'channel_mean'

    @property
    def hop_ms(self):
        return self.hop_length * 1000 / self.sample_rate

    def validate(self):
        if self.sample_rate <= 0 or self.hop_length <= 0 or self.n_fft <= 0 or self.n_fft % 2:
            raise ValueError('sample_rate/hop must be positive and FFT size must be positive/even')
        if not 0 <= self.f_min < self.f_max <= self.sample_rate / 2 or self.n_mels < 1:
            raise ValueError('invalid Mel frequency range')
        if self.power_floor <= 0 or not math.isfinite(self.power_floor):
            raise ValueError('invalid power floor')
        supported = FeatureSpec()
        for field in ('dtype', 'mel_scale', 'filter_normalization', 'window', 'fft_normalization',
                      'center', 'pad_mode', 'resampler', 'downmix'):
            if getattr(self, field) != getattr(supported, field):
                raise ValueError(f'unsupported feature setting: {field}')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_mono(path):
    """Decode in bounded blocks; hash original interleaved PCM before downmixing."""
    with sf.SoundFile(path) as f:
        sr, channels, expected = f.samplerate, f.channels, len(f)
        if expected <= 0:
            raise ValueError('empty audio')
        waveform = np.empty(expected, dtype=np.float32)
        digest = hashlib.sha256(f'{sr}:{channels}:'.encode())
        offset = 0
        for block in f.blocks(blocksize=65536, dtype='float32', always_2d=True):
            if not np.isfinite(block).all() or offset + len(block) > expected:
                raise ValueError('invalid decoded audio')
            digest.update(block.astype('<f4', copy=False).tobytes())
            waveform[offset:offset + len(block)] = block.mean(axis=1, dtype=np.float32)
            offset += len(block)
        if offset != expected:
            raise ValueError(f'partial audio decode: {offset}/{expected}')
    return waveform, sr, {'pcm_sha256': digest.hexdigest(), 'source_frames': expected,
                          'source_sample_rate': sr, 'source_channels': channels,
                          'duration_s': expected / sr}


def resample_audio(waveform, source_rate, spec=FeatureSpec()):
    spec.validate()
    if source_rate <= 0 or waveform.ndim != 1 or not len(waveform):
        raise ValueError('expected nonempty mono audio and positive source rate')
    if not np.isfinite(waveform).all():
        raise ValueError('audio contains non-finite values')
    if source_rate == spec.sample_rate:
        return np.asarray(waveform, dtype=np.float32)
    divisor = math.gcd(source_rate, spec.sample_rate)
    result = resample_poly(waveform, spec.sample_rate // divisor, source_rate // divisor,
                           window=('kaiser', 5.0), padtype='constant')
    return np.asarray(result, dtype=np.float32)


def mel_filterbank(spec=FeatureSpec()):
    spec.validate()
    mel = lambda hz: 2595 * np.log10(1 + np.asarray(hz) / 700)
    edges = 700 * (10 ** (np.linspace(mel(spec.f_min), mel(spec.f_max), spec.n_mels + 2) / 2595) - 1)
    frequencies = np.fft.rfftfreq(spec.n_fft, 1 / spec.sample_rate)
    left = (frequencies[None, :] - edges[:-2, None]) / (edges[1:-1] - edges[:-2])[:, None]
    right = (edges[2:, None] - frequencies[None, :]) / (edges[2:] - edges[1:-1])[:, None]
    weights = np.maximum(0, np.minimum(left, right))
    sums = weights.sum(axis=1)
    if np.any(sums == 0):
        raise ValueError('empty Mel band: increase FFT size or reduce n_mels')
    weights /= sums[:, None]
    return weights.astype(np.float32)


def expected_shape(source_frames, source_rate, spec=FeatureSpec()):
    samples = (source_frames * spec.sample_rate + source_rate - 1) // source_rate
    return (1 + samples // spec.hop_length, spec.n_mels)


def iter_log_mel(waveform, spec=FeatureSpec(), block_frames=2048):
    """Yield (first_frame, float32[T,M]). Frame i is centered at i*hop_ms.

    Waveform must already be mono at spec.sample_rate. Chunking changes only
    computation batches, never the STFT grid or window context.
    """
    spec.validate()
    if waveform.ndim != 1 or len(waveform) == 0 or block_frames < 1:
        raise ValueError('invalid waveform or block_frames')
    if not np.isfinite(waveform).all():
        raise ValueError('non-finite waveform')
    padded = np.pad(waveform, (spec.n_fft // 2, spec.n_fft // 2), mode='constant')
    frames = np.lib.stride_tricks.sliding_window_view(padded, spec.n_fft)[::spec.hop_length]
    window = (.5 - .5 * np.cos(2 * np.pi * np.arange(spec.n_fft) / spec.n_fft)).astype(np.float32)
    bank = csr_matrix(mel_filterbank(spec))
    scale = float(window.sum())
    for start in range(0, len(frames), block_frames):
        spectrum = rfft(frames[start:start + block_frames] * window, axis=1, workers=1) / scale
        power = spectrum.real ** 2 + spectrum.imag ** 2
        mel_power = (bank @ power.T).T
        values = 10 * np.log10(np.maximum(mel_power, spec.power_floor))
        if not np.isfinite(values).all():
            raise ValueError('non-finite Mel features')
        yield start, values.astype(np.float32, copy=False)


def feature_moments(array, block_frames=8192):
    """Float64 moments of the actual stored values, not unquantized features."""
    count = len(array)
    total = np.zeros(array.shape[1], dtype=np.float64)
    squares = total.copy()
    for start in range(0, count, block_frames):
        block = np.asarray(array[start:start + block_frames], dtype=np.float64)
        if not np.isfinite(block).all():
            raise ValueError('non-finite cached feature')
        total += block.sum(axis=0)
        squares += np.square(block).sum(axis=0)
    return count, total, squares


class FeatureStore:
    """Read fixed frame windows; padding is zero AFTER training normalization."""
    def __init__(self, root):
        self.root = Path(root)
        config = json.loads((self.root / 'feature_config.json').read_text(encoding='utf-8'))
        if config['status'] != 'complete':
            raise ValueError('feature build is incomplete')
        self.spec = FeatureSpec(**config['spec'])
        self.spec.validate()
        self.index = {r['audio_id']: r for r in map(json.loads, (self.root / 'audio_index.jsonl').read_text(encoding='utf-8').splitlines())}
        stats = json.loads((self.root / 'normalization.json').read_text(encoding='utf-8'))
        self.mean = np.asarray(stats['mean'], dtype=np.float32)
        self.std = np.asarray(stats['std'], dtype=np.float32)

    def read_window(self, audio_id, start_frame, frame_count, normalize=True):
        if not isinstance(start_frame, int) or not isinstance(frame_count, int) or frame_count < 1:
            raise ValueError('integer frame indices and positive frame_count are required')
        entry = self.index[audio_id]
        array = np.load(self.root / entry['feature_file'], mmap_mode='r', allow_pickle=False)
        output = np.zeros((frame_count, self.spec.n_mels), dtype=np.float32)
        valid = np.zeros(frame_count, dtype=bool)
        first, last = max(0, start_frame), min(len(array), start_frame + frame_count)
        if first < last:
            target = slice(first - start_frame, last - start_frame)
            block = np.asarray(array[first:last], dtype=np.float32)
            output[target] = (block - self.mean) / self.std if normalize else block
            valid[target] = True
        return {'features': output, 'valid_mask': valid,
                'frame_times_ms': (start_frame + np.arange(frame_count)) * self.spec.hop_ms}
