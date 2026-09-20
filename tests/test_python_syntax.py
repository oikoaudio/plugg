"""Every Python file in the project compiles.

The test suite imports the package, so a broken module fails loudly there. The
scripts are run by hand, and one of them shipped with a syntax error that no
test noticed. Compiling them costs nothing and closes that gap.
"""
import ast
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]
SKIP = {'vendor', 'build', 'bundle', '.git', '__pycache__'}


def sources():
    for path in sorted(REPO.rglob('*.py')):
        if not any(part in SKIP for part in path.relative_to(REPO).parts):
            yield path


class SyntaxTests(unittest.TestCase):
    def test_every_python_file_compiles(self):
        found = list(sources())
        self.assertGreater(len(found), 30)
        for path in found:
            with self.subTest(path=str(path.relative_to(REPO))):
                try:
                    ast.parse(path.read_text(), filename=str(path))
                except SyntaxError as error:
                    self.fail(str(path.relative_to(REPO)) + ': ' + str(error))

    def test_the_scripts_are_covered(self):
        names = {path.name for path in sources()}
        for expected in ('build-runtime-overlay.py', 'build-powershell-forwarder.py', 'review-recipe.py'):
            self.assertIn(expected, names)


if __name__ == '__main__':
    unittest.main()
