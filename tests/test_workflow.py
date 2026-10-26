import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import board
import compile_fullscan
import finalize_fullscan
import demo


class WorkflowTests(unittest.TestCase):
    def test_decisions_survive_alias_refresh_and_age_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = board.Board(tmp)
            jobs = [{'public_slug': 'one', 'url': 'https://example.com/jobs/1?utm_source=test'},
                    {'public_slug': 'two', 'url': 'https://example.com/jobs/2'}]
            b.publish({'jobs': jobs})
            b.decide('slug:one', 'applied')
            b.decide('slug:two', 'dismissed')
            b.publish({'jobs': [{'public_slug': 'new-slug', 'url': 'https://example.com/jobs/1'}]})
            state = board.Board(tmp).snapshot()['jobs']
            self.assertEqual({j['status'] for j in state}, {'applied', 'dismissed'})
            self.assertFalse(any(j['status'] == 'active' for j in state))

    def test_pipeline_audits_exclusions_and_rejects_missing_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_compile, old_finalize = compile_fullscan.ROOT, finalize_fullscan.ROOT
            compile_fullscan.ROOT = finalize_fullscan.ROOT = root
            try:
                scan = demo.make_scan(root / 'runs' / 'test')
                with contextlib.redirect_stdout(io.StringIO()):
                    finalize_fullscan.main(scan)
                jobs = json.loads((root / 'jobs.json').read_text())['jobs']
                self.assertEqual({j['public_slug'] for j in jobs}, {'demo-agent', 'demo-data'})
                audit = json.loads((root / 'audit-index.json').read_text())
                outcomes = {r['public_slug']: r['outcome'] for r in audit['records']}
                self.assertEqual(outcomes['demo-intern'], '实习排除')
                self.assertEqual(outcomes['demo-senior'], '经验排除')
                self.assertEqual(outcomes['demo-expired'], '超过14天')
                before = (root / 'jobs.json').read_bytes()
                manifest = json.loads((scan / 'manifest.json').read_text())
                manifest['lanes'][0]['rows_read'] -= 1
                with self.assertRaises(AssertionError):
                    compile_fullscan.main(manifest)
                self.assertEqual((root / 'jobs.json').read_bytes(), before)
            finally:
                compile_fullscan.ROOT, finalize_fullscan.ROOT = old_compile, old_finalize


if __name__ == '__main__':
    unittest.main()
