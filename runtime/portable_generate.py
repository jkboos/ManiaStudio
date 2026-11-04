"""Relocatable wrapper around the frozen generation snapshots."""
import argparse
import json
import os
from pathlib import Path
import sys

RUNTIME = Path(__file__).resolve().parent
APP = RUNTIME.parent
sys.path.insert(0, str(APP))
os.chdir(RUNTIME)
os.environ['PATH'] = str(APP/'bin') + os.pathsep + os.environ.get('PATH', '')
from studio.domain import profile_string


def stage(value):
    print(json.dumps({'studio_stage': value}), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('job', type=Path)
    args = p.parse_args()
    job = args.job.resolve()
    config = json.loads((job/'request.json').read_text(encoding='utf-8'))
    request = config['request']
    frozen = json.loads((APP/'frozen_backend.json').read_text(encoding='utf-8'))
    stage('analyzing')
    policy = json.loads((APP/'runtime_policy.json').read_text(encoding='utf-8'))
    if policy['decoder'] == 'control':
        from control_generate import generate as generate_control
        from studio.exporting import package_result
        generate_control(Path(config['audio_path']), job/'generated', request['keys'], request['stars'], profile_string(request))
        stage('validating')
        stage('packaging')
        package_result(job/'generated', job/'export', request,
                       Path(config['background_path']) if config.get('background_path') else None,
                       dict(version=policy['version']),
                       Path(config['video_path']) if config.get('video_path') else None)
        stage('complete')
        return
    import generate_output_adapter as generate
    import repair_output_adapter as repair
    from technique_output_adapter import load_adapter
    from studio.exporting import package_result

    def portable_loader(path, device):
        model, saved = load_adapter(path, device)
        # Only relocate data metadata in memory. Model weights/config files and
        # hash-bound model code remain byte-identical to the frozen snapshot.
        saved['config']['data_report']['features'] = str(RUNTIME/'data/features')
        return model, saved

    generate.load_pattern_checkpoint = portable_loader
    repair.load_pattern_checkpoint = portable_loader
    params = frozen['parameters']
    policy = json.loads((APP/'runtime_policy.json').read_text(encoding='utf-8'))
    policy_report = None
    if policy['decoder'] == 'audio_ln_plan':
        from generation_policy import install
        policy_report = install(generate, request['keys'], request['stars'], profile_string(request))
    elif policy['decoder'] != 'legacy':
        raise ValueError('Unknown inference decoder policy')
    sys.argv = ['generate_output_adapter.py', config['audio_path'], '--keys', str(request['keys']),
                '--stars', str(request['stars']), '--techniques', profile_string(request),
                '--strength', str(params['strength']), '--selection', params['selection'],
                '--star-tolerance', str(params['star_tolerance']), '--technique-slack', str(params['technique_slack']),
                '--seed', str(params['seed']), '--output', str(job/'generated')]
    generate.main()
    if policy_report:
        report_path = job/'generated/generation_report.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report['inference_policy'] = policy_report
        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    stage('validating')
    sys.argv = ['repair_output_adapter.py', str(job/'generated'), '--output', str(job/'checked')]
    repair.main()
    stage('packaging')
    package_result(job/'checked', job/'export', request,
                   Path(config['background_path']) if config.get('background_path') else None,
                   dict(frozen,version=policy['version']) if policy_report else frozen,
                   Path(config['video_path']) if config.get('video_path') else None)
    stage('complete')


if __name__ == '__main__':
    main()
