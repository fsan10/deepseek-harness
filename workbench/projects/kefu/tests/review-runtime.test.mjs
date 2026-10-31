import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { resolveReviewRuntime } from "../lib/review-runtime.ts";

test("uses kefu's own environment while retaining the shared source directory", () => {
  const projectRoot = path.resolve("kefu-fixture");
  const runtime = resolveReviewRuntime({ projectRoot, platform: "win32", environment: { MOCK_COFFICE_ROOT: "D:\\shared-login-source" } });
  assert.equal(runtime.python, path.join(projectRoot, ".venv", "Scripts", "python.exe"));
  assert.equal(runtime.workerPython, path.join(projectRoot, ".venv", "Scripts", "pythonw.exe"));
  assert.equal(runtime.root, "D:\\shared-login-source");
  assert.equal(runtime.projectRoot, projectRoot);
});

test("derives the windowless executable from an explicit interpreter's directory", () => {
  const interpreter = path.resolve("custom-kefu-env", "Scripts", "python.exe");
  const runtime = resolveReviewRuntime({ platform: "win32", environment: { REVIEWS_PYTHON: interpreter } });
  assert.equal(runtime.python, interpreter);
  assert.equal(runtime.workerPython, path.join(path.dirname(interpreter), "pythonw.exe"));
});

test("uses the local bin/python on non-Windows hosts", () => {
  const projectRoot = path.resolve("kefu-fixture");
  const runtime = resolveReviewRuntime({ projectRoot, platform: "linux", environment: {} });
  assert.equal(runtime.python, path.join(projectRoot, ".venv", "bin", "python"));
  assert.equal(runtime.workerPython, runtime.python);
});
