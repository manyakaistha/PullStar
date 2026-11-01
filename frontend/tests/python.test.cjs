const { test } = require('node:test');
const assert = require('node:assert/strict');
const { findPython } = require('../electron/python.cjs');

test('Windows launches the project environment from Scripts/python.exe', () => {
  const expected = 'C:\\Projects\\StarAligner\\.venv\\Scripts\\python.exe';
  assert.equal(findPython('C:\\Projects\\StarAligner', null, 'win32', path => path === expected), expected);
});
test('macOS and Linux prefer the project environment', () => {
  for (const platform of ['darwin', 'linux']) {
    assert.equal(findPython('/project', '/active', platform, () => true), '/project/.venv/bin/python');
  }
});
test('an active environment is used when the project environment is absent', () => {
  assert.equal(findPython('/project', '/active', 'linux', path => path === '/active/bin/python'), '/active/bin/python');
  assert.equal(findPython('/project', null, 'linux', () => false), 'python');
});
