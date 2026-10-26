"""Generate synthetic checkpoints and compile them. Never overwrite real data."""
import datetime as dt
import json
from pathlib import Path
import finalize_fullscan

ROOT = Path(__file__).resolve().parent


def make_scan(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    plan = json.loads((ROOT / 'search-plan-v2.json').read_text())
    jobs = []
    for slug, title, years, age in [
        ('demo-agent', 'Applied AI Engineer', 1, 1),
        ('demo-data', 'Data Scientist', 3, 2),
        ('demo-intern', 'AI Agent Intern', 0, 1),
        ('demo-senior', 'LLM Engineer', 8, 1),
        ('demo-expired', 'AI Engineer', 1, 30),
    ]:
        jobs.append({
            'public_slug': slug, 'title': title, 'company': 'Example Company (虚构演示)',
            'location': 'Shanghai, China', 'url': 'https://example.com/jobs/' + slug,
            'description': 'Requirements\nAt least %d years of Python and LLM experience.' % years,
            'posted_at': (now - dt.timedelta(days=age)).isoformat(),
            'enrichment': {'category': 'ai_engineering'}
        })
    lanes = []
    for lane in plan['lanes']:
        rows = jobs if lane['id'] == 'core_local' else []
        total = len(rows)
        lanes.append({'id': lane['id'], 'total': total, 'rows_read': total,
                      'offsets': [0] if total else [], 'errors': []})
        if rows:
            page = {'id': lane['id'], 'args': {'offset': 0, 'limit': 20},
                    'offset': 0, 'total': total, 'jobs': rows, 'fetched_at': now.isoformat()}
            (root / (lane['id'] + '-0000.json')).write_text(json.dumps(page, ensure_ascii=False))
    manifest = {'started_at': now.isoformat(), 'cutoff': (now - dt.timedelta(days=14)).isoformat(), 'lanes': lanes}
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False))
    return root


if __name__ == '__main__':
    if (ROOT / 'jobs.json').exists() or (ROOT / 'decisions.sqlite3').exists():
        raise SystemExit('检测到已有本地数据；请在新的克隆目录体验演示，避免覆盖真实清单。')
    finalize_fullscan.main(make_scan(ROOT / 'runs' / 'demo'))
    print('虚构演示已生成。运行 python3 board.py serve 查看。')
