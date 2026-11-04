"""Check the label/scoring contract before technique-conditioned inference."""
import json
from pathlib import Path
from audio_features import sha256_file


def validate_technique_sources(config,root=Path('data/techniques_v1')):
    report=json.loads((root/'report.json').read_text(encoding='utf-8'))
    if sha256_file(root/'labels.jsonl')!=config['labels_sha256']:
        raise ValueError('technique annotation file changed')
    expected=dict(report['source_hashes'])
    expected['technique_data.py']=sha256_file('technique_data.py')
    for name,digest in report['source_hashes'].items():
        if sha256_file(name)!=digest:raise ValueError(f'technique extractor changed: {name}')
    upstream_root=Path('third_party/mania_tracker')
    upstream=json.loads((upstream_root/'provenance.json').read_text(encoding='utf-8'))
    if upstream['commit']!=config['upstream_commit']:raise ValueError('upstream version mismatch')
    for entry in upstream['files']:
        if sha256_file(upstream_root/entry['path'])!=entry['sha256']:
            raise ValueError(f"upstream analyzer changed: {entry['path']}")
    return dict(extractor_sha256=expected,upstream=upstream,
                semantics=config['semantics'],labels_sha256=config['labels_sha256'])
