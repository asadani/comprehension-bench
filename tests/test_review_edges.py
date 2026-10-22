import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from comprehension_bench.core import StudyError, validate_ledger, new_ledger, start_attempt
from comprehension_bench.cli import main

ROOT=Path(__file__).resolve().parents[1]
class ReviewEdges(unittest.TestCase):
    def test_missing_observation_fields_fail_cleanly_before_summary(self):
        study=json.loads((ROOT/'fixtures/study.json').read_text())
        participant=study['participants'][0]
        ledger=start_attempt(study,new_ledger(study),participant['id'],participant['condition_id'],study['tasks'][0]['id'],'first','2026-10-22T10:00:00Z','example-attempt')
        for missing in ['answer','submitted_at']:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as folder:
                malformed=copy.deepcopy(ledger)
                del malformed['attempts'][0][missing]
                with self.assertRaises(StudyError): validate_ledger(study,malformed)
                path=Path(folder)/'ledger.json';path.write_text(json.dumps(malformed))
                errors=io.StringIO()
                with contextlib.redirect_stderr(errors):
                    code=main(['summarize',str(ROOT/'fixtures/study.json'),'--ledger',str(path),'--out',str(Path(folder)/'summary.json')])
                self.assertEqual(code,2)
                self.assertNotIn('Traceback',errors.getvalue())
                self.assertFalse((Path(folder)/'summary.json').exists())
