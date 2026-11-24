"""Execute a check and inspect target-module provenance inside the same interpreter.
The report is diagnostic evidence, never a semantic correctness certificate.
"""
import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import runpy
import sys
import traceback


def execute(workspace, mode, args, modules):
    root = Path(workspace).resolve()
    os.chdir(root)
    sys.path.insert(0, str(root))
    if (root / "src").is_dir():
        sys.path.insert(0, str(root / "src"))
    report = {"mode": mode, "args": args, "workspace": str(root), "python": sys.executable,
              "exit_code": 1, "collected_tests": None, "script_assert_nodes": None,
              "modules": [], "coverage": "declared_not_proven", "accepted": False}
    captured = io.StringIO()
    try:
        if mode == "pytest":
            import pytest

            class Counts:
                collected = 0
                def pytest_collection_finish(self, session):
                    self.collected = len(session.items)

            plugin = Counts()
            report["exit_code"] = int(pytest.main(args, plugins=[plugin]))
            report["collected_tests"] = plugin.collected
        elif mode == "unittest":
            # The native runner exposes counts directly, without guessing from an exit code.
            import unittest
            program = unittest.TestProgram(module=None, argv=["unittest", *args], exit=False)
            report["collected_tests"] = program.result.testsRun
            report["exit_code"] = 0 if program.result.wasSuccessful() else 1
        elif mode == "django":
            runner = root / "tests/runtests.py"
            if not runner.is_file():
                raise ValueError("django mode requires the repository's tests/runtests.py")
            sys.path.insert(0, str(runner.parent))
            sys.argv = [str(runner), *args]
            with redirect_stdout(captured), redirect_stderr(captured):
                runpy.run_path(str(runner), run_name="__main__")
            report["exit_code"] = 0
        elif mode == "script":
            if not args:
                raise ValueError("script mode needs a relative script path")
            script = (root / args[0]).resolve()
            if not script.is_relative_to(root) or not script.is_file():
                raise ValueError("script must be a real file inside the current workspace")
            tree = ast.parse(script.read_text())
            report["script_assert_nodes"] = sum(isinstance(n, ast.Assert) for n in ast.walk(tree))
            if report["script_assert_nodes"] == 0:
                raise ValueError("script requires explicit assertions; import/print-only checks are not accepted")
            sys.argv = [str(script), *args[1:]]
            sys.path.insert(0, str(script.parent))
            runpy.run_path(str(script), run_name="__main__")
            report["exit_code"] = 0
        else:
            raise ValueError("unsupported mode")
    except SystemExit as exc:
        report["exit_code"] = exc.code if isinstance(exc.code, int) else 1
    except BaseException as exc:
        traceback.print_exc()
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if mode == "django":
            output = captured.getvalue()
            print(output, end="")
            count = re.search(r"Ran (\d+) tests?", output)
            report["collected_tests"] = int(count.group(1)) if count else 0
        for name in modules:
            module = sys.modules.get(name)
            file = getattr(module, "__file__", None) if module else None
            path = Path(file).resolve() if file else None
            report["modules"].append({"name": name, "loaded": module is not None,
                                      "path": str(path) if path else None,
                                      "inside_workspace": bool(path and path.is_relative_to(root))})
        real_check = (report["collected_tests"] or 0) > 0 if mode != "script" else (report["script_assert_nodes"] or 0) > 0
        report["accepted"] = (report["exit_code"] == 0 and real_check and bool(modules)
                              and all(m["loaded"] and m["inside_workspace"] for m in report["modules"]))
        report["limits"] = ["Assertions may be incomplete or incorrect; semantic coverage is not proven.",
                            "Only declared target modules are checked; this is not an execution sandbox.",
                            "An assert AST node does not prove the assertion executed on every branch."]
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--request", required=True)
    p.add_argument("--report", required=True)
    opts = p.parse_args()
    request = json.loads(Path(opts.request).read_text())
    report = execute(request["workspace"], request["mode"], request["args"], request["modules"])
    Path(opts.report).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
