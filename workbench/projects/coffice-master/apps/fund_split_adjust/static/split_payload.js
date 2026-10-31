(function exposeFundSplitPayload(root, factory) {
  const helpers = factory();
  if (typeof module === 'object' && module.exports) module.exports = helpers;
  root.FundSplitPayload = helpers;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createFundSplitPayload() {
  function splitPayloadRow(row, amount, remark = row.remark) {
    return {
      amount,
      expense_type_id: row.expense_type_id,
      account_entry_id: row.account_entry_id,
      remark: remark || '',
    };
  }

  function buildAddedSplitPayload(rows) {
    if (rows.length < 2) throw new Error('请先拆分当前流水');
    const last = rows.at(-1);
    const cents = Math.round(Number(last.split_amount || 0) * 100);
    if (cents < 2) throw new Error('最后一条拆分金额不足0.02，无法继续增加子行');
    const firstHalf = (Math.floor(cents / 2) / 100).toFixed(2);
    const splits = rows.slice(0, -1).map(row => splitPayloadRow(row, row.split_amount));
    splits.push(splitPayloadRow(last, firstHalf), splitPayloadRow(last, null, ''));
    return splits;
  }

  return { buildAddedSplitPayload };
}));
