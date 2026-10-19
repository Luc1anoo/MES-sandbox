import {test} from 'node:test';
import assert from 'node:assert/strict';
import {cardRows} from './cardRows.js';

test('new and previously created cards without versions remain visible', () => {
  const cards = [1, 2].map(id => ({id, code: `C${id}`, name: 'Etch', versions: []}));
  const rows = cardRows(cards);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(row => row.card_id), [1, 2]);
  assert.deepEqual(rows.map(row => row.key), ['card-1', 'card-2']);
  assert.equal(rows[0].id, null);
});

test('first version replaces placeholder and retains its parent card', () => {
  const version = {id: 7, version: '1.0', status: 'Draft', recipes: [], inspections: []};
  const [row] = cardRows([{id: 2, code: 'ETCH', name: 'Etch', versions: [version]}]);
  assert.equal(row.key, 'version-7');
  assert.equal(row.card_id, 2);
  assert.equal(row.id, 7);
  assert.equal(row.status, 'Draft');
});

test('mixed cards preserve every version and have distinct row keys', () => {
  const rows = cardRows([
    {id: 1, versions: []},
    {id: 2, versions: [{id: 1}, {id: 2}]},
  ]);
  assert.equal(rows.length, 3);
  assert.equal(new Set(rows.map(row => row.key)).size, 3);
});
