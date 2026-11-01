const fs = require('fs');
const path = require('path');

function findPython(rootPath, activeEnvironment, platform = process.platform, exists = fs.existsSync) {
  const paths = platform === 'win32' ? path.win32 : path.posix;
  const executable = platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python'];
  const candidates = [paths.join(rootPath, '.venv', ...executable)];
  if (activeEnvironment) candidates.push(paths.join(activeEnvironment, ...executable));
  return candidates.find(candidate => exists(candidate)) || 'python';
}

module.exports = { findPython };
