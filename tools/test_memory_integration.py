"""Create a synthetic held-out task and verify memory across real CLI processes.

The output is private test state outside the release. Never uses personal data.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'plugins/df-agent/skills/df-agent/scripts'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workdir', type=Path, required=True)
    args = parser.parse_args()
    area = args.workdir.resolve()
    if area.exists() or area.is_relative_to(ROOT):
        raise ValueError('Use a new directory outside the repository')
    area.mkdir(parents=True)
    log = []

    def run(script, store, *arguments):
        grants = []
        if arguments[0] not in {'status', 'retrieve', 'list', 'history', 'summary'}:
            grants = ['--task-id', 'synthetic-memory-integration', '--write-root', str(area),
                      '--allow-operation', 'memory' if script == 'memory.py' else 'feedback']
            if arguments[0] == 'suggest':
                grants += ['--allow-operation', 'output']
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(SCRIPTS / script),
                                  '--store', str(store), *grants, *map(str, arguments)],
                                 text=True, encoding='utf-8', capture_output=True, timeout=30)
        if process.returncode:
            raise RuntimeError(process.stderr or process.stdout)
        value = json.loads(process.stdout)
        log.append({'script': script, 'command': arguments[0], 'status': value.get('status', 'ok')})
        return value

    def write(name, value):
        path = area / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
        return path

    memory, feedback = area / 'memory-state', area / 'feedback-state'
    run('memory.py', memory, 'init')
    run('feedback.py', feedback, 'init')
    source = 'Synthetic accepted prior project convention. No held-out numbers.'
    digest = hashlib.sha256(source.encode()).hexdigest()
    record = {'id': 'pilot-feedback-01', 'scope': 'project', 'owner': 'pilot-person', 'project': 'pilot-alpha',
              'workflow': 'fund_flows', 'task_id': 'prior-task', 'run_id': 'prior-final',
              'outcome': 'accepted', 'user_feedback': '采用这个展示约定，记住用于本项目后续汇报。',
              'reason': '管理层阅读顺序统一。',
              'selected_excerpt': '本项目资金流汇报：先给申购、赎回、净流入三列的产品汇总表；输入金额为人民币元，汇报展示为千元，保留两位小数。赎回字段为正数，净流入等于申购减赎回。不要仅凭净流入推断投资者获利。',
              'observed_at': '2026-11-16T01:00:00Z',
              'artifact_refs': [{'uri': 'synthetic:prior-report', 'sha256': digest, 'locator': 'approved presentation convention'}],
              'source_refs': [], 'criteria': []}
    input_path = write('selected-feedback.json', record)
    run('feedback.py', feedback, 'record', '--input', input_path, '--explicit-feedback')
    candidate_path = area / 'selected-candidate.json'
    run('feedback.py', feedback, 'suggest', '--scope', 'project', '--owner', 'pilot-person', '--project', 'pilot-alpha',
        '--id', 'pilot-feedback-01', '--key', 'fund-flow.presentation', '--output', candidate_path)
    run('memory.py', memory, 'candidate', '--input', candidate_path)
    before = run('memory.py', memory, 'retrieve', '--owner', 'pilot-person', '--project', 'pilot-alpha')
    assert before['records'] == []
    run('memory.py', memory, 'publish', '--id', 'fb-pilot-feedback-01', '--owner', 'pilot-person', '--project', 'pilot-alpha',
        '--reviewer', 'synthetic-reviewer', '--reason', 'Synthetic user explicitly accepted this convention', '--approve')

    def seed(rid, project, content, publish=True):
        item = {'id': rid, 'scope': 'project', 'owner': 'pilot-person', 'project': project,
                'key': 'fund-flow.other', 'content': content, 'kind': 'lesson',
                'provenance': [{'source': 'synthetic:review', 'locator': rid, 'version': 'fixture-1',
                                'observed_at': '2026-11-16T01:00:00Z', 'kind': 'synthetic'}]}
        path = write(rid + '-candidate.json', item)
        run('memory.py', memory, 'candidate', '--input', path)
        if publish:
            run('memory.py', memory, 'publish', '--id', rid, '--owner', 'pilot-person', '--project', project,
                '--reviewer', 'synthetic-reviewer', '--reason', 'Synthetic scope-isolation fixture', '--approve')

    seed('other-project', 'pilot-beta', '另一项目要求金额展示为百万元。')
    seed('unreviewed', 'pilot-alpha', '未审核草稿建议把赎回加到净流入。', publish=False)
    after = run('memory.py', memory, 'retrieve', '--owner', 'pilot-person', '--project', 'pilot-alpha')
    assert [item['id'] for item in after['records']] == ['fb-pilot-feedback-01']
    assert run('memory.py', memory, 'retrieve', '--owner', 'someone-else', '--project', 'pilot-alpha')['records'] == []
    write('retrieved.json', after)
    (area / 'heldout.csv').write_text('date,product,subscription_cny,redemption_cny\n2026-11-15,SYN-X,18500,2400\n2026-11-15,SYN-Y,7200,9300\n2026-11-16,SYN-X,3100,1900\n2026-11-16,SYN-Y,4800,600\n', 'utf-8')
    write('integration-evidence.json', {'status': 'passed', 'synthetic_only': True, 'checks': {
        'feedback_to_candidate': True, 'candidate_invisible': True, 'reviewed_persistence': True,
        'other_project_excluded': True, 'unreviewed_excluded': True, 'other_owner_excluded': True},
        'separate_cli_processes': len(log), 'calls': log, 'business_value_measured': False})
    print(json.dumps({'status': 'passed', 'checks': 6, 'separate_cli_processes': len(log), 'workdir': str(area)}))


if __name__ == '__main__':
    main()
