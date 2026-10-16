import assert from 'node:assert/strict';
import test from 'node:test';
import { backendOrigin } from './dashboard-origin.ts';

test('production accepts HTTPS and only the in-server backend over HTTP', () => {
  assert.equal(backendOrigin('http://api:8000', 'production'), 'http://api:8000');
  assert.equal(backendOrigin('http://localhost:8000/', 'production'), 'http://localhost:8000');
  assert.equal(backendOrigin('https://stride.aibolt.ai/', 'production'), 'https://stride.aibolt.ai');
  for (const unsafe of ['http://stride.aibolt.ai', 'http://134744072:8000', 'http://0x7f000001', 'http://backend:8000', 'ftp://api']) {
    assert.equal(backendOrigin(unsafe, 'production'), null, unsafe);
  }
});

test('missing or odd origins are refused', () => {
  for (const bad of [undefined, '', '  ', 'not a url', 'https://user:pw@stride.aibolt.ai', 'https://stride.aibolt.ai/api', 'https://stride.aibolt.ai?x=1']) {
    assert.equal(backendOrigin(bad, 'production'), null, String(bad));
  }
});

test('local development may use plain HTTP', () => {
  assert.equal(backendOrigin('http://127.0.0.1:8000', 'development'), 'http://127.0.0.1:8000');
});
