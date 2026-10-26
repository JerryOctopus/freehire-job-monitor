#!/usr/bin/env python3
"""Rebuild complete candidate and audit artifacts from durable page checkpoints."""
import datetime as dt
import argparse
import json
from pathlib import Path
import compile_fullscan

ROOT = Path(__file__).resolve().parent

def main(scan=None):
    scan = Path(scan) if scan else ROOT / 'fullscan'
    manifest = json.loads((scan / 'manifest.json').read_text())
    cutoff = dt.datetime.fromisoformat(manifest['cutoff'].replace('Z', '+00:00'))
    seen, rows = {}, 0
    for p in sorted(scan.glob('*-*.json')):
        page = json.loads(p.read_text())
        if 'jobs' not in page:
            continue
        rows += len(page['jobs'])
        for job in page['jobs']:
            key = job['public_slug']
            previous = seen.get(key)
            lanes = set(previous.get('search_lanes', [])) if previous else set()
            lanes.add(page['id'])
            job['search_lanes'] = sorted(lanes)
            if not previous or len(job.get('description', '')) >= len(previous.get('description', '')):
                seen[key] = job
            else:
                previous['search_lanes'] = sorted(lanes)
    recent, old, closed, unknown = [], 0, 0, 0
    for job in seen.values():
        if job.get('closed_at'):
            closed += 1
            continue
        try:
            date = dt.datetime.fromisoformat(job.get('posted_at', '').replace('Z', '+00:00'))
        except (ValueError, TypeError):
            date = None
        if date and date < cutoff:
            old += 1
            continue
        if not date:
            unknown += 1
        recent.append(job)
    compile_fullscan.board_module.atomic_json(ROOT / 'fullscan-recent.json', {'jobs': recent, 'rows_read': rows, 'unique_jobs': len(seen), 'old': old, 'closed': closed, 'unknown_dates': unknown, 'cutoff': manifest['cutoff']})
    compiled = compile_fullscan.main(manifest)
    audit = json.loads((ROOT / 'screening-audit.json').read_text())
    records = {}
    for key, job in seen.items():
        record = {field: job.get(field) for field in ['public_slug', 'title', 'company', 'location', 'posted_at', 'url']}
        record.update(outcome='超过14天', reason='posted_at早于本轮检索起点往前14天：' + manifest['cutoff'])
        records[key] = record
    for record in audit['excluded_recent']:
        reason = record['reason']
        outcome = '实习排除' if '实习岗位排除' in reason else '经验排除' if '最低经验超过' in reason else '地区排除' if '目标地区之外' in reason or '远程居住限制' in reason else '方向排除'
        records[record['public_slug']].update(outcome=outcome, reason=reason)
    for record in audit['duplicate_candidates']:
        records[record['public_slug']].update(outcome='重复', reason=record['reason'] + '；合并到' + record['canonical_slug'])
    for job in compiled['jobs']:
        if job['public_slug'] in records:
            records[job['public_slug']].update(outcome='候选' if job['qualification'] == 'confirmed' else '待核实', reason=job['experience_label'] + '；' + job['geography_evidence'])
    assert len(records) == audit['statistics']['unique_records']
    assert sum(r['outcome'] in {'候选', '待核实'} for r in records.values()) == audit['statistics']['candidates']
    compile_fullscan.board_module.atomic_json(ROOT / 'audit-index.json', {'statistics': audit['statistics'], 'records': list(records.values()), 'as_of': manifest['started_at']})
    print(json.dumps({'audit_records': len(records), 'candidate_count': audit['statistics']['candidates'], 'all_pages_complete': all(l['rows_read'] == l['total'] for l in manifest['lanes'])}, ensure_ascii=False))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan-dir', help='本次独立运行的分页目录；默认使用原始全量基线目录')
    main(parser.parse_args().scan_dir)
