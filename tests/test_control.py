import json
from pathlib import Path
import sys
import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP/'runtime'))
from control_generate import choose_candidate
from server import create_app


def test_candidate_choice_does_not_penalize_ln_or_short_gap_flags():
    candidates = [dict(candidate=0, actual_stars=6.1, ln_count=200, flagged_heads=14),
                  dict(candidate=1, actual_stars=5.7, ln_count=0, flagged_heads=0)]
    assert choose_candidate(candidates, 6., .5)['candidate'] == 0


def test_no_silent_out_of_range_export():
    with pytest.raises(ValueError, match='3.20'):
        choose_candidate([dict(candidate=0, actual_stars=3.2)], 4., .5)
    with pytest.raises(ValueError):
        choose_candidate([], 4., .5)


def test_control_identity_and_config(tmp_path):
    import hashlib
    manifest = json.loads((APP/'control_backend.json').read_text())
    for file_key, hash_key in [('checkpoint', 'checkpoint_sha256'), ('decoder', 'decoder_sha256')]:
        assert hashlib.sha256((APP/'runtime'/manifest[file_key]).read_bytes()).hexdigest() == manifest[hash_key]
    app = create_app(tmp_path, run_worker=False)
    config = app.test_client().get('/api/config').json
    assert config['backend_version'] == 'studio-control-1'
