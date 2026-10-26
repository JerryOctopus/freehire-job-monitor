#!/usr/bin/env python3
"""Compile every saved search page; keep exclusions and uncertain records inspectable."""
import collections
import datetime as dt
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('local_board', ROOT / 'board.py')
board_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board_module)

def has(pattern, text):
    return bool(re.search(pattern, text or '', re.I))

def internship(job):
    # Match role titles or explicit employment type, not incidental mentions of
    # prior internship experience or mentoring interns in a permanent role.
    pattern = r'\bintern(?:ship)?s?\b|实习|實習|インターン'
    if has(pattern, job.get('title', '')):
        return True
    for source in (job, job.get('enrichment', {})):
        if any(has(pattern, str(source.get(key, ''))) for key in ('employment_type', 'job_type', 'contract_type')):
            return True
    return has(r'(?:this (?:role|position) is (?:an? )?|employment type\s*[:：]\s*|job type\s*[:：]\s*)internship\b', job.get('description', ''))

def requirements(job):
    supplied = job.get('enrichment', {}).get('requirements') or []
    required = [r['text'] for r in supplied if r.get('priority') == 'required']
    if required:
        return required
    lines = job.get('description', '').splitlines()
    active, result = False, []
    for line in lines:
        if has(r'preferred qualifications|nice.to.have|加分项|歓迎|benefits|what we offer|why join|privacy', line):
            active = False
        if has(r'^.{0,20}(requirements|qualifications|what.{0,10}(need|bring|looking for)|任职|任職|岗位要求|职位要求|必須|ideal experience|who you are)', line):
            active = True
            continue
        if active and line.strip() and len(line.strip()) > 12:
            result.append(line.strip(' *-\\'))
    return result

def years(job, req):
    numeric = []
    quotes = []
    degree_alternative = False
    candidates = list(req)
    if not req:
        for line in job.get('description', '').splitlines():
            if has(r'(?:minimum|at least|must have|you have|you bring|至少|不少于|必须|要求).{0,60}\d+\s*(?:\+|[-–—]\s*\d+)?\s*(?:years?|年)', line) and has(r'experience|经验|経験', line):
                if not has(r'preferred|nice.to.have|加分|成立|founded|company.{0,15}(history|years)|leave|scholarship', line):
                    candidates.append(line)
    for line in dict.fromkeys(candidates):
        if not has(r'experience|经验|経験', line):
            continue
        nums = [int(v) for v in re.findall(r'(\d{1,2})\s*(?:[-–—~至到]\s*\d{1,2})?\s*\+?\s*(?:years?|年)', line, re.I)]
        nums = [v for v in nums if v <= 30]
        if not nums:
            continue
        if len(set(nums)) > 1 and has(r'ph\.?d|博士', line) and has(r'master|硕士|修士', line):
            degree_alternative = True
        val = min(nums) if has(r'master|硕士|修士|equivalent|or equivalent|或', line) else max(nums)
        numeric.append(val)
        quotes.append(line[:900])
    if degree_alternative:
        return None, quotes, '存在硕士/博士等不同经验路径，适用最低年限待人工确认'
    if has(r'fresh graduates? (are )?(welcome|considered)|freshers are welcome|no.{0,35}minimum years|无需.{0,15}经验|应届.*亦可', job.get('description', '')):
        return 0, quotes, 'JD明确接受新人或不设最低年限'
    if numeric:
        return max(numeric), quotes, '按JD经验要求原文初核'
    value = job.get('enrichment', {}).get('experience_years_min')
    return value, quotes, '仅结构化经验字段，正文需确认' if value is not None else 'JD未明确最低年限'

DIRECT = r'\b(?:AI|ML|LLM|NLP|RAG|MLOps|GenAI|Agentic)\b|machine.learning|data scien|applied scien|forward deployed|customer engineer|大模型|智能体|算法|机器学习|数据科学|人工智能|生成AI|生成系AI|機械学習|データサイエン'
BODY_AI = r'\bLLMs?\b|large.language.model|langchain|langgraph|generative.?ai|agentic|大模型|智能体|\bRAG\b|machine.learning'
TECH = r'engineer|developer|scientist|architect|analyst|research|technical|product manager|trainer|evaluation|test|工程|研发|开发|架构|评测|测试|研究|产品|分析|エンジニア|開発'
PURE_SALES = r'account executive|account manager|sales director|sales manager|business development|sales development|sales representative|sales associate|insurance agent|travel agent|estate agent|contact.center.agent'
TARGETS = {'cn', 'hk', 'mo', 'jp', 'sg'}
LOCAL = r'china|hong.kong|macau|macao|singapore|japan|tokyo|osaka|kyoto|beijing|shanghai|shenzhen|guangzhou|hangzhou|suzhou|chengdu|香港|澳门|中國|中国|新加坡|日本|東京|北京|上海|深圳|广州|杭州|成都'

def relevant(job):
    title, text = job['title'], job.get('description', '')
    category = job.get('enrichment', {}).get('category', '')
    if has(PURE_SALES, title) and not has(r'engineer|technical|solution|architect|售前', title):
        return False
    return bool(has(DIRECT, title) or category in {'ai_engineering', 'ml_ai', 'data_science'} or
                (has(TECH, title) and has(BODY_AI, text)) or
                (category == 'data_analytics' and has(r'A/B|causal|hypothesis.test|experimentation|因果|统计建模|实验分析', text)))

def geography(job):
    text, location = job.get('description', ''), job.get('location', '')
    local_lane = bool(set(job.get('search_lanes', [])) & {'core_local', 'supp_local', 'uncategorized_local'})
    if has(r'(?:this (?:role|position)|the role).{0,40}(?:based|located) in (?:Paris|London|Dublin|San Francisco|New York|Austin|Berlin)', text):
        return 'exclude', '正文明确岗位位于目标地区之外'
    if has(LOCAL, location):
        return 'confirmed', '职位地点字段：' + location
    if local_lane:
        return 'pending', '命中地区标签，但地点字段缺失或不一致：' + (location or '未注明')
    if has(r'mainland china.{0,30}remote|remote.{0,30}(?:mainland )?china|position is china.based|中国.{0,12}远程', location + '\n' + text):
        return 'confirmed', '正文/地点字段明确中国远程'
    restricted = r'(?:remote (?:role )?(?:is )?(?:only )?(?:within|in|from|across|based in)|must (?:be (?:based|located|resident)|reside|live)|open (?:only )?to candidates (?:based|located)|for .{0,10}residents only).{0,60}(?:united states|\bus\b|usa|canada|india|philippines|greece|europe|european union|uk|united kingdom|latam|latin america|brazil|pakistan|australia)'
    if has(restricted, text) and not has(r'worldwide|anywhere in the world|globally remote', location):
        return 'exclude', '正文有目标地区之外的远程居住限制'
    if has(r'remote.{0,20}worldwide|worldwide.{0,20}remote|anywhere in the world|location.{0,5}anywhere|全球远程', location + '\n' + text):
        return 'pending', '标注全球远程，但中国雇佣/常驻资格仍需确认'
    return 'pending', '仅远程搜索命中，未找到允许常驻中国的明确证据'

def initial_match(job, req, minimum):
    # Public distribution has no built-in candidate biography.
    # A private reviewer can replace this object with an evidence-based analysis.
    return {
        'method': '规则初核，未载入个人简历证据',
        'recommendation': '补充材料后投递',
        'summary': '已按岗位方向、年限与地区初核；个人适配尚未分析。',
        'strengths': [],
        'gaps': ['尚未提供个人简历证据，不能判断能力是否匹配'],
        'hard_gates': [job['experience_label'], job['geography_evidence']],
        'evidence_matrix': [{'jd_requirement': line, 'importance': 'JD要求',
                            'resume_evidence': ['未提供个人证据'], 'status': '待确认',
                            'risk': '需对照用户确认的简历逐项审核'} for line in req],
        'resume_version': '待选择'
    }

def main(manifest=None):
    if manifest is None:
        manifest = json.loads((ROOT / 'fullscan/manifest.json').read_text())
    assert all(l['rows_read'] == l['total'] and len(set(l['offsets'])) == len(range(0, l['total'], 20)) and not l['errors'] for l in manifest['lanes'])
    dataset = json.loads((ROOT / 'fullscan-recent.json').read_text())
    related, excluded = [], []
    for job in dataset['jobs']:
        reason = None
        if internship(job):
            reason = '实习岗位排除：职位标题或明确岗位类型为Intern/Internship/实习'
        elif not relevant(job):
            reason = '未见目标技术职责（规则初核）；原始JD保留供复核'
        req = requirements(job)
        minimum, quotes, basis = years(job, req)
        if reason is None and minimum is not None and minimum > 5:
            reason = '最低经验超过5年：%s；%s' % (minimum, basis)
        geo, geo_note = geography(job)
        if reason is None and geo == 'exclude':
            reason = geo_note
        audit = {'public_slug': job['public_slug'], 'title': job['title'], 'company': job['company'], 'location': job.get('location'), 'posted_at': job.get('posted_at'), 'url': job.get('url'), 'reason': reason, 'experience_min': minimum, 'experience_evidence': quotes, 'geography_evidence': geo_note}
        if reason:
            excluded.append(audit)
            continue
        job.update(experience_label=('最低%d年；' % minimum if minimum is not None else '') + basis,
                   experience_evidence=quotes, geography_evidence=geo_note,
                   qualification='confirmed' if minimum is not None and geo == 'confirmed' and quotes and (has(DIRECT, job['title']) or job.get('enrichment', {}).get('category') in {'ai_engineering', 'ml_ai', 'data_science'}) else 'pending',
                   review_note='完整分页检索所得。个人适配为规则初核；未确认年限、地域或资格不等同于已满足。',
                   direction=job.get('enrichment', {}).get('category', '方向待核实'))
        job['match'] = initial_match(job, req, minimum)
        related.append(job)
    # Stable IDs and application URLs deduplicate; retain every alias for saved decisions.
    related.sort(key=lambda j: (j.get('source', '') in {'whatjobs', 'whatjobs-sg'}, -(len(j.get('description', '')))))
    aliases, groups, duplicates = {}, [], []
    for job in related:
        keys = board_module.identities(job)
        digest = hashlib.sha256(re.sub(r'\s+', '', job.get('description', '')).lower().encode()).hexdigest()
        exact_key = 'exact:' + str(job.get('company', '')).lower() + ':' + str(job.get('location', '')).lower() + ':' + digest
        found = next((aliases[k] for k in keys + [exact_key] if k in aliases), None)
        if found is not None:
            target = groups[found]
            target['identity_aliases'] = sorted(set(target.get('identity_aliases', []) + keys))
            target.setdefault('duplicate_sources', []).append({'public_slug': job['public_slug'], 'url': job.get('url'), 'source': job.get('source')})
            duplicates.append({'public_slug': job['public_slug'], 'canonical_slug': target['public_slug'], 'reason': '同一职位ID/原始链接，或同公司同地点完全相同JD'})
            idx = found
        else:
            idx = len(groups)
            groups.append(job)
        for k in keys + [exact_key]:
            aliases[k] = idx
    board = board_module.Board(ROOT)
    old = board.snapshot()
    previous = {j['public_slug']: j for j in old['jobs']}
    for j in groups:
        p = previous.get(j['public_slug'])
        if p and p.get('match') and not p['match'].get('method', '').startswith('规则'):
            j['match'] = p['match']
        j['first_seen_at'] = p.get('first_seen_at') if p else manifest['started_at']
        j['last_checked_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    stats = {'read_records': dataset['rows_read'], 'unique_records': dataset['unique_jobs'], 'older_than_14_days': dataset['old'], 'recent_records': len(dataset['jobs']),
             'internship_excluded': sum('实习岗位排除' in x['reason'] for x in excluded),
             'direction_excluded': sum('未见目标' in x['reason'] for x in excluded), 'experience_excluded': sum('最低经验超过' in x['reason'] for x in excluded),
             'geography_excluded': sum('远程居住限制' in x['reason'] or '目标地区之外' in x['reason'] for x in excluded), 'duplicate_candidates': len(duplicates),
             'candidates': len(groups), 'confirmed_search_conditions': sum(j['qualification'] == 'confirmed' for j in groups), 'pending': sum(j['qualification'] == 'pending' for j in groups),
             'human_assessed': sum(not j['match'].get('method', '').startswith('规则') for j in groups)}
    note = '本次%d路查询全部分页已完成：%d页、%d条读取记录，去重后%d条。近14天%d条；形成%d个候选（检索条件已核对%d，待核实%d）。规则初核与人工分析分开标明；这代表本次搜索方案的完整结果，不代表全网无遗漏。' % (len(manifest['lanes']), sum(len(l['offsets']) for l in manifest['lanes']), stats['read_records'], stats['unique_records'], stats['recent_records'], stats['candidates'], stats['confirmed_search_conditions'], stats['pending'])
    rank = {'建议投递': 0, '补充材料后投递': 1, '谨慎投递': 2, '暂不建议投递': 3}
    groups.sort(key=lambda j: (rank.get(j['match']['recommendation'], 4), -int(j['qualification'] == 'confirmed'), -dt.datetime.fromisoformat(j['posted_at'].replace('Z', '+00:00')).timestamp()), reverse=False)
    output = {'jobs': groups, 'coverage_note': note, 'coverage': manifest, 'statistics': stats, 'as_of': manifest['started_at'], 'full_pagination_complete': True}
    board.publish(output)
    active = board.snapshot()
    active['jobs'] = [j for j in active['jobs'] if j['status'] == 'active']
    board_module.atomic_json(ROOT / 'complete-candidates.json', active)
    board_module.atomic_json(ROOT / 'screening-audit.json', {'statistics': stats, 'excluded_recent': excluded, 'duplicate_candidates': duplicates, 'coverage': manifest})
    print(json.dumps(stats, ensure_ascii=False))
    return output

if __name__ == '__main__':
    main()
