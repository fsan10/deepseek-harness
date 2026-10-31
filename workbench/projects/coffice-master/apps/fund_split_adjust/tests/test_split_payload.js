const assert = require('node:assert/strict');
const { buildAddedSplitPayload } = require('../static/split_payload.js');

const rows = [
  { split_amount: '100.00', expense_type_id: 1, account_entry_id: 2, remark: '首行', adjusted_diff: 0, is_adjusted: false },
  { split_amount: '100.00', expense_type_id: 1, account_entry_id: 2, remark: '末行', adjusted_diff: 0, is_adjusted: false },
];
const splits = buildAddedSplitPayload(rows);
assert.equal(splits.length, 3);
assert.deepEqual(splits.map(row => row.amount), ['100.00', '50.00', null]);
assert.equal(splits[1].remark, '末行');
assert.equal(splits[2].remark, '');
assert.equal(buildAddedSplitPayload([{ ...rows[0], is_adjusted: true, adjusted_diff: 10 }, rows[1]]).length, 3);
assert.throws(() => buildAddedSplitPayload([rows[0]]), /请先拆分/);
console.log('增加拆分行前端兼容载荷测试通过');
