const state={imports:[],batchId:"",statement:null,expenses:[],accounts:[],typePageItems:[],accountPageItems:[],selected:new Set(),expandedOds:new Set(),page:"statement",popoverAction:null,assignContext:null,logOperatorOptions:[],logOperatorSelections:[],logOperatorContext:null,pageSize:10,pages:{statement:1,types:1,accounts:1,imports:1,logs:1}};
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const escapeHtml=value=>String(value??"").replace(/[&<>'"]/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[ch]));
const money=value=>new Intl.NumberFormat("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value||0));
const currency=value=>`${Number(value)<0?'-':''}¥${money(Math.abs(Number(value||0)))}`;
const dateTime=value=>{if(!value)return"—";const d=new Date(value),pad=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`};
const decoded=value=>{try{return decodeURIComponent(String(value??""))}catch{return String(value??"")}};
const operator=()=>$("#operatorInput").value.trim()||"财务用户";

function syncSelectTitle(select){
  if(!(select instanceof HTMLSelectElement))return;
  [...select.options].forEach(option=>{option.title=(option.textContent||"").trim()});
  const selected=select.options[select.selectedIndex];
  select.title=selected?(selected.textContent||"").trim():"";
}
function enhanceNativeSelects(){
  const syncWithin=root=>{
    if(root instanceof HTMLSelectElement)syncSelectTitle(root);
    else if(root?.querySelectorAll)root.querySelectorAll('select').forEach(syncSelectTitle);
  };
  syncWithin(document);
  document.addEventListener('change',event=>syncSelectTitle(event.target));
  document.addEventListener('mouseover',event=>syncSelectTitle(event.target));
  document.addEventListener('focusin',event=>syncSelectTitle(event.target));
  new MutationObserver(mutations=>mutations.forEach(mutation=>{
    syncWithin(mutation.target);
    mutation.addedNodes.forEach(syncWithin);
  })).observe(document.body,{childList:true,subtree:true});
}

async function api(path,options={}){
  const headers={"X-Operator":encodeURIComponent(operator()),...(options.headers||{})};
  if(options.body && !(options.body instanceof FormData)){headers["Content-Type"]="application/json";options.body=JSON.stringify(options.body)}
  const response=await fetch(path,{...options,headers});
  const payload=await response.json().catch(()=>({message:`HTTP ${response.status}`}));
  if(!response.ok||payload.code!==0)throw new Error(payload.message||"请求失败");
  return payload.data;
}
function toast(message,type="success"){if(window.showAppToast&&window.hasOpenEditor?.())return window.showAppToast(message,type);$("#toast").textContent=message;$("#toast").className=`toast show ${type}`;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("#toast").className="toast",2800)}
function setBusy(button,busy,text="处理中…"){if(!button)return;if(busy){button.dataset.label=button.textContent;button.textContent=text;button.disabled=true}else{button.textContent=button.dataset.label||button.textContent;button.disabled=false}}
function qs(values){const params=new URLSearchParams();Object.entries(values).forEach(([k,v])=>{if(v!==""&&v!=null)params.set(k,v)});return params.toString()}
function renderPager(id,pagination,onChange){
  const root=$(`#${id}`);if(!root)return;
  const total=Number(pagination?.total||0),size=Number(pagination?.page_size||state.pageSize),current=Number(pagination?.page||1),pages=Math.max(1,Math.ceil(total/size));
  const start=Math.max(1,Math.min(current-2,pages-4)),end=Math.min(pages,start+4),buttons=[];
  for(let page=start;page<=end;page++)buttons.push(`<button type="button" data-page="${page}" class="${page===current?'active':''}" ${page===current?'aria-current="page"':''}>${page}</button>`);
  root.innerHTML=`<button type="button" data-page="${current-1}" ${current<=1?'disabled':''} aria-label="上一页">‹</button>${buttons.join('')}<button type="button" data-page="${current+1}" ${current>=pages?'disabled':''} aria-label="下一页">›</button><span>第 ${current} / ${pages} 页</span>`;
  root.querySelectorAll('[data-page]:not([disabled])').forEach(button=>button.onclick=()=>onChange(Number(button.dataset.page)));
}
function collectionItems(payload){return Array.isArray(payload)?payload:(Array.isArray(payload?.items)?payload.items:[])}
function normalizePagedCollection(payload,page,pageSize){
  if(Array.isArray(payload)){
    const total=payload.length,pages=Math.max(1,Math.ceil(total/pageSize)),current=Math.min(Math.max(1,page),pages),start=(current-1)*pageSize;
    return {items:payload.slice(start,start+pageSize),pagination:{page:current,page_size:pageSize,total}};
  }
  const items=collectionItems(payload),pagination=payload?.pagination||{};
  return {items,pagination:{page:Number(pagination.page||page||1),page_size:Number(pagination.page_size||pageSize),total:Number(pagination.total??items.length)}};
}

function switchPage(page){
  const meta={
    statement:["资金流水编辑","墨客咖时（南京）生物科技有限公司"],
    types:["费用类型管理","管理流水拆分的一级费用分类"],
    accounts:["入账管理","管理流水拆分后的入账科目"],
    imports:["导入记录","银行流水导入历史与文件管理"],
    logs:["操作日志","系统操作审计记录与变更追踪"]
  };
  if(!meta[page])page="statement";
  state.page=page;
  $$('.nav-item[data-page]').forEach(x=>{const active=x.dataset.page===page;x.classList.toggle('active',active);active?x.setAttribute('aria-current','page'):x.removeAttribute('aria-current')});
  $$('.page').forEach(x=>x.classList.remove('active'));
  $(`#${page}Page`).classList.add('active');
  $("#pageTitle").textContent=meta[page][0];
  $("#pageSubtitle").textContent=meta[page][1];
  $(".page-heading").classList.toggle('stacked',page!=="statement");
  $$('.page-actions').forEach(x=>x.hidden=true);
  const pageActions=$(`#${page}Actions`);
  if(pageActions)pageActions.hidden=false;
  if(page==="types")loadTypes();
  if(page==="accounts")loadAccounts();
  if(page==="imports")loadImports(true);
  if(page==="logs")loadLogs();
  history.replaceState(null,'',`#${page}`);
}

async function loadReferenceData(){const [expenses,accounts]=await Promise.all([api('/api/expense-types?is_active=true'),api('/api/account-entries?is_active=true')]);state.expenses=collectionItems(expenses);state.accounts=collectionItems(accounts);renderTypeFilters()}
function renderTypeFilters(){
  const options=state.expenses.map(x=>`<option value="${x.id}">${escapeHtml(x.name)}</option>`).join('');
  $("#accountTypeFilter").innerHTML='<option value="">全部</option>'+options;
  const statementFilter=$("#expenseTypeFilter");
  if(statementFilter){const current=statementFilter.value;statementFilter.innerHTML='<option value="">全部费用类型</option><option value="unassigned">未分配</option>'+options;statementFilter.value=current}
}

async function loadImports(renderPage=false){
  const catalog=await api('/api/import/records?'+qs({page_size:200}));state.imports=catalog.items;
  $("#batchSelect").innerHTML=state.imports.length?state.imports.map(x=>`<option value="${x.batch_id}">${x.batch_id} · ${escapeHtml(x.file_name)}</option>`).join(''):'<option value="">暂无导入批次</option>';
  if(!state.batchId&&state.imports.length)state.batchId=state.imports[0].batch_id;if(state.batchId&&!state.imports.some(x=>x.batch_id===state.batchId))state.batchId=state.imports[0]?.batch_id||"";$("#batchSelect").value=state.batchId;
  if(renderPage){const data=await api('/api/import/records?'+qs({page:state.pages.imports,page_size:state.pageSize,date_from:$("#importDateFrom")?.value,date_to:$("#importDateTo")?.value,keyword:$("#importKeyword")?.value,status:$("#importStatus")?.value}));renderImports(data)}if(state.batchId&&state.page==="statement")await loadStatement();
}
function renderImports(data){
  const items=data.items,all=state.imports;
  const rows=all.reduce((s,x)=>s+Number(x.record_count||0),0);
  const totalAmount=all.reduce((s,x)=>s+Number(x.total_debit||0)+Number(x.total_credit||0),0);
  const now=new Date(),monthCount=all.filter(x=>{const d=new Date(x.created_at);return d.getFullYear()===now.getFullYear()&&d.getMonth()===now.getMonth()}).length;
  $("#importCards").innerHTML=`<article><div class="metric-label">累计导入</div><strong>${all.length}<span class="unit">次</span></strong></article><article><div class="metric-label">累计流水</div><strong>${rows}<span class="unit">条</span></strong></article><article><div class="metric-label">累计金额</div><strong>¥${money(totalAmount)}</strong></article><article><div class="metric-label">本月导入</div><strong>${monthCount}<span class="unit">次</span></strong></article>`;
  $("#importBody").innerHTML=items.length?items.map(x=>`<tr><td><strong>${x.batch_id}</strong></td><td>${escapeHtml(x.file_name)}</td><td>${dateTime(x.created_at)}</td><td class="center">${x.record_count}</td><td class="amount">¥${money(Number(x.total_debit||0)+Number(x.total_credit||0))}</td><td>${x.date_from||'—'} ~ ${x.date_to||'—'}</td><td><span class="status-badge ${x.status==='success'?'success':'warning'}">${x.status==='success'?'成功':'失败'}</span></td><td>${escapeHtml(decoded(x.operator))}</td><td><div class="row-actions"><button data-open-batch="${x.batch_id}">查看</button><button data-download="${x.batch_id}">下载源表</button></div></td></tr>`).join(''):'<tr><td colspan="9" class="empty">暂无导入记录</td></tr>';
  $("#importTotal").textContent=`共 ${data.pagination.total} 条`;renderPager('importPager',data.pagination,page=>{state.pages.imports=page;loadImports(true)});
  $$('[data-open-batch]').forEach(b=>b.onclick=()=>{state.batchId=b.dataset.openBatch;switchPage('statement');$("#batchSelect").value=state.batchId;loadStatement()});
  $$('[data-download]').forEach(b=>b.onclick=()=>location.href=`/api/import/records/${b.dataset.download}/download`);
}

async function loadStatement(){if(!state.batchId){renderEmptyStatement();return}const query=qs({page:state.pages.statement,page_size:state.pageSize,date_from:$("#dateFrom").value,date_to:$("#dateTo").value,expense_type_id:$("#expenseTypeFilter").value,keyword:$("#statementKeyword").value});state.statement=await api(`/api/statement/${state.batchId}?${query}`);state.selected.clear();renderStatement()}
function renderEmptyStatement(){$("#statementBody").innerHTML='<tr><td colspan="13" class="empty">请先导入银行流水</td></tr>';$("#statementTotal").textContent='共 0 条';renderPager('statementPager',{total:0,page:1,page_size:state.pageSize},()=>{})}
function searchableAssign(field,row,disabled=false){
  const isExpense=field==='expense_type_id';
  const value=isExpense?row.expense_type_name:row.account_entry_name;
  return `<div class="assign-combobox"><button type="button" class="assign-trigger" role="combobox" aria-expanded="false" data-id="${row.split_id}" data-field="${field}" data-expense-id="${row.expense_type_id||''}" data-value="${isExpense?row.expense_type_id||'':row.account_entry_id||''}" ${disabled?'disabled':''}><span class="assign-value ${value?'':'empty'}">${escapeHtml(value||'待分配')}</span><svg><use href="#i-down"/></svg></button></div>`;
}
function updateExpandAllButton(){
  const splitParents=(state.statement?.rows||[]).filter(x=>x.split_rows.length>1);
  const expanded=splitParents.length>0&&splitParents.every(x=>state.expandedOds.has(x.ods_id));
  $("#expandAll").classList.toggle('expanded',expanded);
  $("#expandAll span").textContent=expanded?'全部收起':'全部展开';
  $("#expandAll").disabled=splitParents.length===0;
}
function adjustedAmountStack(current,original,diff){
  const direction=diff>0?'increase':'decrease',label=diff>0?'↑多':'↓少';
  return `<div class="amount-adjustment" title="当前金额 ${money(current)}；原始金额 ${money(original)}；${diff>0?'增加':'减少'} ${money(Math.abs(diff))}"><strong class="adjusted-current">${money(current)}</strong><span class="adjusted-source">原始 <s>${money(original)}</s></span><span class="adjusted-diff ${direction}">${label} ${money(Math.abs(diff))}</span></div>`;
}
function parentAmountDisplay(rows,visible,sourceAmount){
  if(!visible)return '—';
  const diff=rows.reduce((sum,item)=>sum+Number(item.adjusted_diff||0),0);
  if(Math.abs(diff)<.005)return money(sourceAmount);
  const original=rows.reduce((sum,item)=>sum+Number(item.original_amount||0),0);
  return adjustedAmountStack(original+diff,original,diff);
}
function splitAmountDisplay(child,visible){
  if(!visible)return '—';
  return `<strong class="split-current-amount">${money(child.adjusted_amount)}</strong>`;
}
function renderStatement(){
  closeAssignDropdown(false);closeLogOperatorDropdown();window.DateRange.close();
  const data=state.statement,summary=data.summary;const batch=state.imports.find(x=>x.batch_id===state.batchId);$("#batchMeta").textContent=batch?`${batch.file_name} · ${batch.date_from} 至 ${batch.date_to} · ${batch.is_submitted?'已提交':'编辑中'}`:state.batchId;
  const pending=Number(summary.pending_amount||0),hasPending=Math.abs(pending)>0.01;
  $("#summaryCards").classList.toggle('four',hasPending);
  $("#summaryCards").innerHTML=`<article><div class="metric-label">流水总笔数</div><strong>${summary.total_count}<span class="unit">条</span></strong></article><article class="debit"><div class="metric-label">借方合计</div><strong>¥${money(summary.total_debit)}</strong></article><article class="credit"><div class="metric-label">贷方合计</div><strong>¥${money(summary.total_credit)}</strong></article>${hasPending?`<article class="pending ${pending<0?'negative':''}"><div class="metric-label">待分配金额</div><strong>${currency(pending)} <span class="pending-tag">待调配</span></strong></article>`:''}`;
  $("#allocationAlert").hidden=!hasPending;$("#allocationAlert").classList.toggle('negative',pending<0);$("#allocationAlert strong").textContent=currency(pending);
  const adjustedRows=data.rows.flatMap(x=>x.split_rows).filter(x=>Number(x.adjusted_diff)!==0);const sourceAdjust=adjustedRows.at(-1),netAdjust=adjustedRows.reduce((sum,x)=>sum+Number(x.adjusted_diff),0);
  const direction=netAdjust>0?'上升':'下降',instruction=pending>0?'加到其他行':'从其他行扣减';
  $("#allocationDetail").textContent=sourceAdjust?`流水 ${sourceAdjust.transaction_time||'—'}${adjustedRows.length>1?` 等${adjustedRows.length}笔流水调账抵扣后`:' 已调账'}${direction} ¥${money(Math.abs(netAdjust))}，需${instruction}，请使用一键调配或手工调账进行分配`:'请在其他行使用一键调配或手工调账进行分配';
  $("#submitBatch").disabled=summary.is_submitted||!summary.is_balanced||Number(summary.unassigned_count)>0;$("#submitBatch").textContent=summary.is_submitted?'已提交':'提交';
  $("#withdrawSubmit").hidden=!summary.is_submitted;
  $("#submitHelper").hidden=!$("#submitBatch").disabled||summary.is_submitted;$("#submitHelper").textContent=!summary.is_balanced?'待分配金额不为0，无法提交':'存在未分类流水，无法提交';
  const html=[],allocateDisabled=!hasPending||summary.is_submitted;
  data.rows.forEach(parent=>{
    const rows=parent.split_rows,row=rows[0],isSplit=rows.length>1,expanded=isSplit&&state.expandedOds.has(parent.ods_id),debit=Number(row.debit_amount||0)!==0,credit=Number(row.credit_amount||0)!==0,parentDiff=rows.reduce((sum,item)=>sum+Number(item.adjusted_diff||0),0),adjusted=Math.abs(parentDiff)>=.005,parentCurrent=rows.reduce((sum,item)=>sum+Number(item.adjusted_amount||0),0);
    if(!isSplit)state.expandedOds.delete(parent.ods_id);
    html.push(`<tr class="${expanded?'split-parent ':''}${adjusted?'adjusted':''}"><td class="check"><input class="row-check" type="checkbox" value="${row.split_id}" ${state.selected.has(Number(row.split_id))?'checked':''} ${summary.is_submitted?'disabled':''}></td><td class="center">${isSplit?`<button class="expand-button ${expanded?'expanded':''}" data-expand="${parent.ods_id}" aria-label="${expanded?'收起拆分行':'展开拆分行'}"><svg><use href="#i-right"/></svg></button>`:''}</td><td>${row.transaction_time||'—'}</td><td>${row.transaction_date}</td><td>${escapeHtml(row.transaction_type||'未标注')}</td><td><div class="account-name-text" title="${escapeHtml(row.account_name||'')}">${escapeHtml(row.account_name||'—')}</div></td><td class="amount debit-amount">${parentAmountDisplay(rows,debit,Number(row.debit_amount||0))}</td><td class="amount credit-amount">${parentAmountDisplay(rows,credit,Number(row.credit_amount||0))}</td><td class="amount">${row.balance!=null?money(row.balance):'—'}</td><td>${isSplit?`<span class="split-parent-label">已拆分${rows.length}项</span>`:searchableAssign('expense_type_id',row,summary.is_submitted)}</td><td>${isSplit?'—':searchableAssign('account_entry_id',row,summary.is_submitted)}</td><td><input class="summary-input" data-summary="${row.split_id}" value="${escapeHtml(row.summary||'')}" placeholder="—" title="原始摘要：${escapeHtml(row.source_summary||'—')}" ${summary.is_submitted?'disabled':''}></td><td><div class="row-actions"><button data-split="${parent.ods_id}" data-count="${rows.length}">${expanded?'收起':'拆分'}</button><span>|</span>${isSplit?`<button class="adjust" data-adjust-parent="${parent.ods_id}" data-amount="${parentCurrent}">调账</button>`:`<button class="adjust" data-adjust="${row.split_id}" data-amount="${row.adjusted_amount}">调账</button>`}${adjusted?`<span>|</span><button class="restore" ${isSplit?`data-restore-parent="${parent.ods_id}"`:`data-restore="${row.split_id}"`} ${summary.is_submitted?'disabled':''}>复原</button>`:''}<span>|</span><button class="allocate" data-allocate="${rows[0].split_id}" ${allocateDisabled?'disabled':''}>一键调配</button></div></td></tr>`);
    if(!expanded)return;
    rows.forEach((child,index)=>{
      const auto=index===rows.length-1;
      html.push(`<tr class="split-child ${Number(child.adjusted_diff)?'adjusted':''}"><td></td><td class="center child-corner"><svg><use href="#i-corner"/></svg></td><td>拆分${index+1}${auto?'<span class="auto-badge">自动分配</span>':''}</td><td></td><td>${escapeHtml(child.transaction_type||'—')}</td><td><div class="account-name-text" title="${escapeHtml(child.account_name||'')}">${escapeHtml(child.account_name||'—')}</div></td><td class="amount debit-amount">${splitAmountDisplay(child,debit)}</td><td class="amount credit-amount">${splitAmountDisplay(child,credit)}</td><td></td><td>${searchableAssign('expense_type_id',child,summary.is_submitted)}</td><td>${searchableAssign('account_entry_id',child,summary.is_submitted)}</td><td><input class="summary-input" data-summary="${child.split_id}" value="${escapeHtml(child.summary||'')}" placeholder="—" title="原始摘要：${escapeHtml(child.source_summary||'—')}" ${summary.is_submitted?'disabled':''}></td><td><div class="row-actions">${auto?'':`<button class="adjust" data-adjust-child="${child.split_id}" data-amount="${child.adjusted_amount}">调账</button>${Math.abs(Number(child.adjusted_diff||0))>=.005?`<span>|</span><button class="restore" data-restore-child="${child.split_id}" ${summary.is_submitted?'disabled':''}>复原</button>`:''}<span>|</span>`}<button class="allocate" data-allocate="${child.split_id}" ${allocateDisabled?'disabled':''}>一键调配</button><span>|</span><button class="danger" data-delete-child="${child.split_id}" data-ods="${parent.ods_id}" ${rows.length<=2?'disabled title="至少保留两条拆分子行"':''}>删除</button></div></td></tr>`);
    });
    const amounts=rows.map(x=>money(x.adjusted_amount));const mother=parentCurrent;
    html.push(`<tr class="split-summary"><td colspan="9"><div class="split-summary-content"><svg><use href="#i-check"/></svg><span>拆分合计：</span><span class="split-equation">${amounts.join(' + ')} = ${money(mother)}</span><span class="split-mother">= 母行金额 ${money(mother)}</span></div></td><td colspan="4"><div class="split-summary-actions"><button class="mini-button add" data-add-split="${parent.ods_id}"><svg><use href="#i-plus"/></svg>增加拆分行</button><button class="mini-button cancel" data-cancel-split="${parent.ods_id}">取消拆分</button></div></td></tr>`);
  });
  $("#statementBody").innerHTML=html.join('')||'<tr><td colspan="13" class="empty">没有匹配的流水</td></tr>';$("#statementTotal").textContent=`共 ${data.pagination.total} 条`;renderPager('statementPager',data.pagination,page=>{state.pages.statement=page;loadStatement()});
  bindStatementActions();updateSelectionBar();updateExpandAllButton();
}
function bindStatementActions(){
  $$('.row-check').forEach(x=>x.onchange=()=>{x.checked?state.selected.add(Number(x.value)):state.selected.delete(Number(x.value));updateSelectionBar()});
  $$('.assign-trigger').forEach(x=>{x.onmousedown=e=>e.stopPropagation();x.onclick=e=>{e.stopPropagation();openAssignDropdown(x)}});
  $$('[data-summary]').forEach(x=>x.onchange=async()=>{try{await api(`/api/statement/${state.batchId}/summary`,{method:'PUT',body:{split_id:Number(x.dataset.summary),summary:x.value}});toast('摘要已保存')}catch(e){toast(e.message,'error')}});
  $$('[data-expand]').forEach(x=>x.onclick=()=>toggleSplit(Number(x.dataset.expand)));
  $$('[data-split]').forEach(x=>x.onclick=()=>startOrToggleSplit(Number(x.dataset.split),Number(x.dataset.count)));
  $$('[data-add-split]').forEach(x=>x.onclick=()=>addSplitRow(Number(x.dataset.addSplit)));
  $$('[data-delete-child]').forEach(x=>x.onclick=()=>deleteSplitChild(Number(x.dataset.ods),Number(x.dataset.deleteChild)));
  $$('[data-split-amount]:not([readonly])').forEach(x=>x.onchange=()=>saveSplitAmounts(Number(x.dataset.ods)));
  $$('[data-adjust]').forEach(x=>x.onclick=()=>openAdjust(Number(x.dataset.adjust),x.dataset.amount));
  $$('[data-adjust-parent]').forEach(x=>x.onclick=()=>openParentAdjust(Number(x.dataset.adjustParent),x.dataset.amount));
  $$('[data-adjust-child]').forEach(x=>x.onclick=()=>openChildAdjust(Number(x.dataset.adjustChild),x.dataset.amount));
  $$('[data-restore]').forEach(x=>x.onclick=()=>restoreAmount({split_id:Number(x.dataset.restore)},'该行'));
  $$('[data-restore-parent]').forEach(x=>x.onclick=()=>restoreAmount({ods_id:Number(x.dataset.restoreParent)},'拆分母行',Number(x.dataset.restoreParent)));
  $$('[data-restore-child]').forEach(x=>x.onclick=()=>restoreAmount({split_id:Number(x.dataset.restoreChild)},'拆分子项'));
  $$('[data-allocate]').forEach(x=>x.onclick=()=>oneClick(Number(x.dataset.allocate)));
  $$('[data-cancel-split]').forEach(x=>x.onclick=()=>cancelSplit(Number(x.dataset.cancelSplit)));
}
function updateSelectionBar(){const count=state.selected.size;$("#selectionBar").hidden=!count;$("#selectedCount").textContent=count;$("#selectAll").checked=count>0&&count===$$('.row-check:not(:disabled)').length}
function hideTablePopover(){const pop=$("#tablePopover");pop.hidden=true;pop.className='table-popover';pop.innerHTML='';state.popoverAction=null}
function showTablePopover(kind,html,onConfirm){const pop=$("#tablePopover");pop.className=`table-popover ${kind}`;pop.innerHTML=html;pop.hidden=false;state.popoverAction=onConfirm;pop.querySelector('[data-popover-cancel]').onclick=()=>{hideTablePopover();renderStatement()};pop.querySelector('[data-popover-confirm]').onclick=async()=>{const button=pop.querySelector('[data-popover-confirm]');try{setBusy(button,true);await onConfirm();hideTablePopover()}catch(e){toast(e.message,'error')}finally{setBusy(button,false)}}}

function assignItems(trigger){
  if(trigger.dataset.field==='expense_type_id')return state.expenses;
  const expenseId=Number(trigger.dataset.expenseId||0);
  return expenseId?state.accounts.filter(x=>(x.expense_types||[]).some(t=>Number(t.id)===expenseId)):[];
}
function placeFloating(drop,trigger,preferredWidth){
  const rect=trigger.getBoundingClientRect(),width=Math.min(preferredWidth,window.innerWidth-16);drop.style.width=`${width}px`;
  const measured=drop.offsetHeight||280,left=Math.max(8,Math.min(rect.left,window.innerWidth-width-8));
  const below=rect.bottom+6,top=below+measured<=window.innerHeight-8?below:Math.max(8,rect.top-measured-6);
  drop.style.left=`${left}px`;drop.style.top=`${top}px`;
}
function renderAssignOptions(query=''){
  const context=state.assignContext;if(!context)return;const normalized=query.trim().toLowerCase();
  const items=context.items.filter(x=>!normalized||x.name.toLowerCase().includes(normalized));
  $("#assignOptions").innerHTML=items.length?items.map(x=>`<button type="button" class="assign-option ${Number(context.trigger.dataset.value)===Number(x.id)?'active':''}" data-assign-option="${x.id}"><span>${escapeHtml(x.name)}</span></button>`).join(''):`<div class="assign-empty">${context.requiresExpense?'请先选择费用类型':query?`未找到「${escapeHtml(query)}」，按 Enter 创建`:'当前费用类型下暂无入账选项'}</div>`;
  $$('[data-assign-option]').forEach(button=>{button.onmousedown=e=>e.preventDefault();button.onclick=()=>{const item=context.items.find(x=>Number(x.id)===Number(button.dataset.assignOption));closeAssignDropdown(false);assignResolved(context.trigger,item)}});
}
function openAssignDropdown(trigger){
  if(state.assignContext?.trigger===trigger){closeAssignDropdown(false);return}
  if(state.assignContext){const query=$("#assignSearch").value.trim(),missing=query&&!state.assignContext.items.some(x=>x.name===query);closeAssignDropdown(missing);if(missing)return}
  window.DateRange.close();hideTablePopover();
  const drop=$("#assignDropdown"),search=$("#assignSearch"),items=assignItems(trigger),requiresExpense=trigger.dataset.field==='account_entry_id'&&!Number(trigger.dataset.expenseId||0);state.assignContext={trigger,items,requiresExpense};
  trigger.setAttribute('aria-expanded','true');search.value='';search.disabled=requiresExpense;search.placeholder=requiresExpense?'请先选择费用类型':'查找或创建选项';drop.hidden=false;renderAssignOptions();placeFloating(drop,trigger,250);if(!requiresExpense)setTimeout(()=>search.focus(),0);
}
function closeAssignDropdown(promptMissing=false){
  const context=state.assignContext;if(!context)return;const search=$("#assignSearch"),query=search.value.trim();
  context.trigger?.setAttribute('aria-expanded','false');$("#assignDropdown").hidden=true;state.assignContext=null;
  if(promptMissing&&!context.requiresExpense&&query&&!context.items.some(x=>x.name===query))showAutoAdd(context.trigger,query);
}
function assignResolved(input,item){
  const ids=state.selected.size?[...state.selected]:[Number(input.dataset.id)],field=input.dataset.field,label=field==='expense_type_id'?'费用类型':'入账';
  const apply=async()=>{const result=await api(`/api/statement/${state.batchId}/batch-assign`,{method:'POST',body:{split_ids:ids,field,value:item.id}}),cleared=Number(result.cleared_account_count||0);toast(field==='expense_type_id'&&cleared?`费用类型已更新，${cleared} 行不匹配的入账已清空`:`已更新 ${ids.length} 行`);await Promise.all([loadReferenceData(),loadStatement()])};
  if(ids.length>1){showTablePopover('batch-confirm',`<div class="popover-message"><span class="popover-icon warning">!</span><div class="popover-copy"><p>已选中 <em>${ids.length}</em> 行，确认批量修改${label}为「<em class="highlight">${escapeHtml(item.name)}</em>」？</p>${field==='expense_type_id'?'<p class="popover-hint">不属于新费用类型的入账将自动清空。</p>':''}</div></div><div class="popover-actions"><button class="mini-button" data-popover-cancel>取消</button><button class="mini-button primary button" data-popover-confirm>确定修改</button></div>`,apply);return}
  apply().catch(e=>{toast(e.message,'error');renderStatement()});
}
function showAutoAdd(input,name){
  closeAssignDropdown(false);
  const isExpense=input.dataset.field==='expense_type_id',label=isExpense?'费用类型':'入账',title=isExpense?'自动添加新类型':'自动添加新入账';
  showTablePopover('auto-add',`<div class="popover-message"><span class="popover-icon"><svg><use href="#i-plus"/></svg></span><div class="popover-copy"><strong>${title}</strong><p>${label}「<em>${escapeHtml(name)}</em>」不存在，是否自动添加到${isExpense?'类型管理':'入账管理'}？</p></div></div><div class="popover-actions"><button class="mini-button" data-popover-cancel>取消</button><button class="mini-button primary button" data-popover-confirm>确定添加</button></div>`,async()=>{let created;if(isExpense){created=await api('/api/expense-types',{method:'POST',body:{name}})}else{const expenseId=Number(input.dataset.expenseId);if(!expenseId)throw new Error('请先选择费用类型');created=await api('/api/account-entries',{method:'POST',body:{name,expense_type_ids:[expenseId]}})}await loadReferenceData();await api(`/api/statement/${state.batchId}/batch-assign`,{method:'POST',body:{split_ids:state.selected.size?[...state.selected]:[Number(input.dataset.id)],field:input.dataset.field,value:created.id}});toast(`${label}已创建并应用`);await loadStatement()})
}

/* 日期范围改用共享组件 /identity-assets/date-range.js；打开前先关掉本页其它浮层。 */
window.DateRangeHooks={beforeOpen(){closeAssignDropdown(true);hideTablePopover()}};
function openModal(title,kicker,body,onConfirm){$("#modalTitle").textContent=title;$("#modalKicker").textContent=kicker;$("#modalBody").innerHTML=body;const dialog=$("#modal"),button=$("#modalConfirm");button.onclick=async event=>{event.preventDefault();try{setBusy(button,true);await onConfirm();dialog.close();}catch(error){toast(error.message,'error')}finally{setBusy(button,false)}};dialog.showModal()}
function toggleSplit(odsId){state.expandedOds.has(odsId)?state.expandedOds.delete(odsId):state.expandedOds.add(odsId);renderStatement()}
async function startOrToggleSplit(odsId,currentCount){if(currentCount>1){toggleSplit(odsId);return}const parent=state.statement.rows.find(x=>x.ods_id===odsId),row=parent?.split_rows[0];if(!row)return;try{await api(`/api/statement/${state.batchId}/split`,{method:'POST',body:{ods_id:odsId,splits:[{amount:null,expense_type_id:row.expense_type_id,account_entry_id:row.account_entry_id,remark:row.remark},{amount:null,expense_type_id:row.expense_type_id,account_entry_id:row.account_entry_id,remark:''}]}});state.expandedOds.add(odsId);toast('已展开拆分行');await loadStatement()}catch(e){toast(e.message,'error')}}
async function addSplitRowWithLegacyApi(odsId){
  const parent=state.statement?.rows.find(x=>Number(x.ods_id)===Number(odsId)),rows=parent?.split_rows||[],splits=FundSplitPayload.buildAddedSplitPayload(rows);
  await api(`/api/statement/${state.batchId}/split`,{method:'POST',body:{ods_id:odsId,splits}});
}
async function addSplitRow(odsId){try{try{await api(`/api/statement/${state.batchId}/add-split-row`,{method:'POST',body:{ods_id:odsId}})}catch(error){if(!String(error.message).includes('接口不存在'))throw error;await addSplitRowWithLegacyApi(odsId)}state.expandedOds.add(odsId);toast('已增加拆分行');await loadStatement()}catch(e){toast(e.message,'error')}}
async function saveSplitAmounts(odsId){const parent=state.statement.rows.find(x=>x.ods_id===odsId);if(!parent)return;const inputs=$$(`[data-split-amount][data-ods="${odsId}"]`);const values=new Map(inputs.map(x=>[Number(x.dataset.splitAmount),x.value.replace(/,/g,'')]));try{await api(`/api/statement/${state.batchId}/split`,{method:'POST',body:{ods_id:odsId,splits:parent.split_rows.map((row,index)=>({amount:index===parent.split_rows.length-1?null:(values.get(row.split_id)||row.split_amount),expense_type_id:row.expense_type_id,account_entry_id:row.account_entry_id,remark:row.remark}))}});state.expandedOds.add(odsId);toast('拆分金额已保存');await loadStatement()}catch(e){toast(e.message,'error');renderStatement()}}
async function deleteSplitChild(odsId,splitId){const parent=state.statement.rows.find(x=>x.ods_id===odsId);if(!parent||parent.split_rows.length<=2)return;const kept=parent.split_rows.filter(x=>x.split_id!==splitId);try{await api(`/api/statement/${state.batchId}/split`,{method:'POST',body:{ods_id:odsId,splits:kept.map((row,index)=>({amount:index===kept.length-1?null:row.split_amount,expense_type_id:row.expense_type_id,account_entry_id:row.account_entry_id,remark:row.remark}))}});state.expandedOds.add(odsId);await loadStatement()}catch(e){toast(e.message,'error')}}
function calculateAmountExpression(rawValue,baseAmount){
  const raw=String(rawValue??'').replace(/,/g,'').replace(/[×xX]/g,'*').replace(/÷/g,'/').replace(/\s+/g,'');
  if(!raw)throw new Error('请输入调账金额');
  const base=Number(baseAmount),expression=/^[+\-*/]/.test(raw)?`${base}${raw}`:raw;
  if(!/^\d+(?:\.\d+)?(?:[+\-*/]\d+(?:\.\d+)?)*$/.test(expression))throw new Error('请输入金额，或使用 + - * / 进行计算');
  const numbers=expression.split(/[+\-*/]/).map(Number),operators=expression.match(/[+\-*/]/g)||[],values=[numbers[0]],lowOperators=[];
  operators.forEach((operator,index)=>{const value=numbers[index+1];if(operator==='*'||operator==='/'){if(operator==='/'&&value===0)throw new Error('除数不能为0');values[values.length-1]=operator==='*'?values.at(-1)*value:values.at(-1)/value}else{lowOperators.push(operator);values.push(value)}});
  const result=lowOperators.reduce((total,operator,index)=>operator==='+'?total+values[index+1]:total-values[index+1],values[0]);
  if(!Number.isFinite(result)||result<=0)throw new Error('调账后金额必须大于0');
  return Math.round((result+Number.EPSILON)*100)/100;
}
function setupAmountCalculator(baseAmount){
  const input=$("#adjustAmount"),preview=$("#amountCalculatorPreview");
  const update=()=>{try{const result=calculateAmountExpression(input.value,baseAmount);preview.textContent=`= ${money(result)}`;preview.classList.remove('error');return result}catch(error){preview.textContent=error.message;preview.classList.add('error');return null}};
  const commit=()=>{const result=update();if(result!=null)input.value=result.toFixed(2)};
  input.oninput=update;input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();commit()}};input.onblur=()=>{if(/[+\-*/×÷xX]/.test(input.value))commit()};
  update();setTimeout(()=>{input.focus();input.select()},0);
}
function openAmountAdjust({title,kicker,label,current,ruleTitle,ruleText,onSubmit}){
  const base=Number(current);
  openModal(title,kicker,`<div class="form-grid"><label class="full"><span>${label}</span><input id="adjustAmount" type="text" inputmode="decimal" value="${base}" autocomplete="off" autofocus><small class="amount-calculator-help">支持直接输入金额，或使用 +100、-50、*1.2、/2 计算</small><strong class="amount-calculator-preview" id="amountCalculatorPreview"></strong></label><div class="full import-rule"><strong>${ruleTitle}</strong><span>${ruleText}</span></div></div>`,async()=>{const amount=calculateAmountExpression($("#adjustAmount").value,base);await onSubmit(amount)});
  setupAmountCalculator(base);
}
function openAdjust(splitId,current){openAmountAdjust({title:'手工调账',kicker:'ADJUST AMOUNT',label:'调账后金额',current,ruleTitle:'平衡规则',ruleText:'调账不会修改 ODS，也不会改变拆分基准金额；待分配金额按全部调账差额带符号合计计算。',onSubmit:async amount=>{await api(`/api/statement/${state.batchId}/adjust`,{method:'POST',body:{split_id:splitId,new_amount:amount}});toast('调账已保存');await loadStatement()}})}
function openParentAdjust(odsId,current){openAmountAdjust({title:'母行调账',kicker:'ADJUST PARENT AMOUNT',label:'母行调账后总金额',current,ruleTitle:'均分规则',ruleText:'调账后的母行总金额将平均分配到全部拆分子项；之后仍可对任一子项单独调账。',onSubmit:async amount=>{await api(`/api/statement/${state.batchId}/adjust-parent`,{method:'POST',body:{ods_id:odsId,new_amount:amount}});state.expandedOds.add(odsId);toast('母行调账已均分到子项');await loadStatement()}})}
function openChildAdjust(splitId,current){openAmountAdjust({title:'子项调账',kicker:'ADJUST CHILD AMOUNT',label:'子项金额',current,ruleTitle:'自动分配规则',ruleText:'母行总金额保持不变；当前子项的增减金额由最后一个自动分配子项反向补足。',onSubmit:async amount=>{await api(`/api/statement/${state.batchId}/adjust-child`,{method:'POST',body:{split_id:splitId,new_amount:amount}});toast('子项金额已更新，自动分配项已同步');await loadStatement()}})}
async function restoreAmount(payload,label,parentOdsId=null){if(!confirm(`确认将${label}恢复到原始金额？`))return;try{await api(`/api/statement/${state.batchId}/restore`,{method:'POST',body:payload});if(parentOdsId)state.expandedOds.add(parentOdsId);toast('金额已复原');await loadStatement()}catch(e){toast(e.message,'error')}}
async function oneClick(splitId){const pending=Number(state.statement?.summary?.pending_amount||0),action=pending>0?'加到':'从';if(!confirm(`确认将当前待调配金额 ${currency(pending)} ${action}该行${pending>0?'':'扣减'}，使总额恢复平衡？`))return;try{await api(`/api/statement/${state.batchId}/allocate-one-click`,{method:'POST',body:{target_split_id:splitId}});toast('一键调配完成，待分配金额已平衡');await loadStatement()}catch(e){toast(e.message,'error')}}
async function cancelSplit(odsId){try{await api(`/api/statement/${state.batchId}/split/cancel`,{method:'POST',body:{ods_id:odsId}});state.expandedOds.delete(odsId);toast('已取消拆分');await loadStatement()}catch(e){toast(e.message,'error')}}

async function loadTypes(){const payload=await api('/api/expense-types?'+qs({page:state.pages.types,page_size:state.pageSize,keyword:$("#typeKeyword").value,is_active:$("#typeStatus").value})),data=normalizePagedCollection(payload,state.pages.types,state.pageSize);state.pages.types=data.pagination.page;state.typePageItems=data.items;$("#typeBody").innerHTML=data.items.map(x=>`<tr><td><strong>${x.code}</strong></td><td><strong>${escapeHtml(x.name)}</strong></td><td>${escapeHtml(x.description||'—')}</td><td class="center">${x.account_count}</td><td class="center">${x.sort_order}</td><td><span class="status-badge ${x.is_active?'success':'off'}">${x.is_active?'启用':'停用'}</span></td><td>${dateTime(x.created_at)}</td><td><div class="row-actions management-actions"><button data-edit-type="${x.id}"><svg><use href="#i-edit"/></svg>编辑</button><button class="${x.is_active?'status-disable':'status-enable'}" data-toggle-type="${x.id}"><svg><use href="#i-power"/></svg>${x.is_active?'停用':'启用'}</button><button class="danger" data-delete-type="${x.id}"><svg><use href="#i-trash"/></svg>删除</button></div></td></tr>`).join('')||'<tr><td colspan="8" class="empty">暂无费用类型</td></tr>';$("#typeTotal").textContent=`共 ${data.pagination.total} 条`;renderPager('typePager',data.pagination,page=>{state.pages.types=page;loadTypes()});$$('[data-edit-type]').forEach(b=>b.onclick=()=>editType(state.typePageItems.find(x=>x.id===Number(b.dataset.editType))));$$('[data-toggle-type]').forEach(b=>b.onclick=()=>toggleType(Number(b.dataset.toggleType)));$$('[data-delete-type]').forEach(b=>b.onclick=()=>deleteType(Number(b.dataset.deleteType)))}
function typeForm(x={}){return `<div class="form-grid"><label class="full"><span><b class="required">*</b> 类型名称</span><input id="typeName" maxlength="100" placeholder="请输入类型名称" value="${escapeHtml(x.name||'')}" required></label><label class="full"><span>类型说明</span><textarea id="typeDescription" rows="2" placeholder="请输入类型说明">${escapeHtml(x.description||'')}</textarea></label><label class="full sort-field"><span>排序</span><input id="typeSort" type="number" min="1" value="${x.sort_order??9}"></label><label class="switch-field"><span>启用</span><span class="switch-control"><input id="typeActive" name="is_active" type="checkbox" ${x.is_active!==false?'checked':''}><span class="switch-track"></span></span></label></div>`}
function editType(x){openModal(x?'编辑费用类型':'新增费用类型','EXPENSE TYPE',typeForm(x),async()=>{const active=$("#typeActive").checked;const body={name:$("#typeName").value,description:$("#typeDescription").value,sort_order:$("#typeSort").value?Number($("#typeSort").value):undefined,...(!x?{is_active:active}:{})};await api(x?`/api/expense-types/${x.id}`:'/api/expense-types',{method:x?'PUT':'POST',body});if(x&&active!==x.is_active)await api(`/api/expense-types/${x.id}/toggle-status`,{method:'PUT',body:{}});toast(x?'费用类型已更新':'费用类型已创建');await Promise.all([loadTypes(),loadReferenceData()])})}
async function toggleType(id){try{await api(`/api/expense-types/${id}/toggle-status`,{method:'PUT',body:{}});toast('状态已更新');await Promise.all([loadTypes(),loadReferenceData()])}catch(e){toast(e.message,'error')}}
async function deleteType(id){if(!confirm('确认删除该费用类型？已被引用的数据不会允许删除。'))return;try{await api(`/api/expense-types/${id}`,{method:'DELETE'});toast('费用类型已删除');await loadTypes()}catch(e){toast(e.message,'error')}}

async function loadAccounts(){const payload=await api('/api/account-entries?'+qs({page:state.pages.accounts,page_size:state.pageSize,keyword:$("#accountKeyword").value,expense_type_id:$("#accountTypeFilter").value,is_active:$("#accountStatus").value})),data=normalizePagedCollection(payload,state.pages.accounts,state.pageSize);state.pages.accounts=data.pagination.page;state.accountPageItems=data.items;$("#accountBody").innerHTML=data.items.map(x=>`<tr><td><strong>${x.code}</strong></td><td><strong>${escapeHtml(x.name)}</strong></td><td><div class="tag-list">${(x.expense_types||[]).map(t=>`<span class="tag">${escapeHtml(t.name)}</span>`).join('')}</div></td><td>${escapeHtml(x.description||'—')}</td><td class="center">${x.sort_order}</td><td><span class="status-badge ${x.is_active?'success':'off'}">${x.is_active?'启用':'停用'}</span></td><td>${dateTime(x.created_at)}</td><td><div class="row-actions management-actions"><button data-edit-account="${x.id}"><svg><use href="#i-edit"/></svg>编辑</button><button class="${x.is_active?'status-disable':'status-enable'}" data-toggle-account="${x.id}"><svg><use href="#i-power"/></svg>${x.is_active?'停用':'启用'}</button><button class="danger" data-delete-account="${x.id}"><svg><use href="#i-trash"/></svg>删除</button></div></td></tr>`).join('')||'<tr><td colspan="8" class="empty">暂无入账科目</td></tr>';$("#accountTotal").textContent=`共 ${data.pagination.total} 条`;renderPager('accountPager',data.pagination,page=>{state.pages.accounts=page;loadAccounts()});$$('[data-edit-account]').forEach(b=>b.onclick=()=>editAccount(state.accountPageItems.find(x=>x.id===Number(b.dataset.editAccount))));$$('[data-toggle-account]').forEach(b=>b.onclick=()=>toggleAccount(Number(b.dataset.toggleAccount)));$$('[data-delete-account]').forEach(b=>b.onclick=()=>deleteAccount(Number(b.dataset.deleteAccount)))}
function accountForm(x={}){const selected=new Set((x.expense_types||[]).map(t=>Number(t.id)));return `<div class="form-grid"><label><span>入账科目名称</span><input id="accountName" maxlength="100" value="${escapeHtml(x.name||'')}" required></label><label><span>排序</span><input id="accountSort" type="number" value="${x.sort_order??''}"></label><label class="full"><span>允许费用类型（首个为默认）</span><div class="check-list">${state.expenses.map(t=>`<label><input type="checkbox" name="accountType" value="${t.id}" ${selected.has(t.id)?'checked':''}><span>${escapeHtml(t.name)}</span></label>`).join('')}</div></label><label class="full"><span>说明</span><textarea id="accountDescription">${escapeHtml(x.description||'')}</textarea></label></div>`}
function editAccount(x){openModal(x?'编辑入账科目':'新增入账科目','ACCOUNT ENTRY',accountForm(x),async()=>{const expense_type_ids=$$('input[name="accountType"]:checked').map(c=>Number(c.value));const body={name:$("#accountName").value,description:$("#accountDescription").value,sort_order:$("#accountSort").value?Number($("#accountSort").value):undefined,expense_type_ids};await api(x?`/api/account-entries/${x.id}`:'/api/account-entries',{method:x?'PUT':'POST',body});toast(x?'入账科目已更新':'入账科目已创建');await Promise.all([loadAccounts(),loadReferenceData()])})}
async function toggleAccount(id){try{await api(`/api/account-entries/${id}/toggle-status`,{method:'PUT',body:{}});toast('状态已更新');await Promise.all([loadAccounts(),loadReferenceData()])}catch(e){toast(e.message,'error')}}
async function deleteAccount(id){if(!confirm('确认删除该入账科目？已被流水引用时不会允许删除。'))return;try{await api(`/api/account-entries/${id}`,{method:'DELETE'});toast('入账科目已删除');await loadAccounts()}catch(e){toast(e.message,'error')}}

function logReference(field,value){if(value==null||value==='')return'—';if(field==='expense_type_id')return state.expenses.find(x=>x.id===Number(value))?.name||`费用类型 #${value}`;if(field==='account_entry_id')return state.accounts.find(x=>x.id===Number(value))?.name||`入账 #${value}`;if(field==='is_active')return value?'启用':'停用';return String(value)}
function logTarget(x){
  const type=x.operation_type;
  if(type==='submit')return'全表数据提交';
  if(type==='withdraw_submit')return'撤回全表数据提交';
  if(type==='type_create')return'新增费用类型';if(type==='type_update')return'编辑费用类型';if(type==='type_toggle')return'启停费用类型';if(type==='type_delete')return'删除费用类型';
  if(type==='account_create')return'新增入账';if(type==='account_update')return'编辑入账';if(type==='account_toggle')return'启停入账';if(type==='account_delete')return'删除入账';
  if(x.target_type==='split_row'&&x.target_id){const row=state.statement?.rows.flatMap(p=>p.split_rows).find(r=>r.split_id===x.target_id);if(row)return`流水 ${row.transaction_time||'—'} ${row.transaction_date} ${row.transaction_type||''}`}
  if(x.target_type==='statement'&&x.target_id){const row=state.statement?.rows.find(p=>p.ods_id===x.target_id)?.split_rows[0];if(row)return`流水 ${row.transaction_time||'—'} ${row.transaction_date} ${row.transaction_type||''}`}
  return x.target_description||x.target_type||'—';
}
function diffLine(label,oldValue,newValue){return `<div class="log-detail-line"><span class="log-detail-label">${escapeHtml(label)}: </span><span class="log-old">${escapeHtml(oldValue??'—')}</span><span class="log-arrow"> → </span><span class="log-new">${escapeHtml(newValue??'—')}</span></div>`}
function formatLogDetail(x){
  const d=x.change_detail||{},type=x.operation_type;
  if(['adjust','child_adjust','restore'].includes(type)&&Array.isArray(d.fields))return d.fields.map(f=>diffLine(f.field_key==='adjusted_amount'?'金额':f.field_key==='child_amount'?'子项金额':f.field_key==='auto_amount'?'自动分配金额':f.field_key,logReference(f.field_key,f.old_value),logReference(f.field_key,f.new_value))).join('');
  if(type==='split'&&Array.isArray(d.amounts))return `拆分为${d.amounts.length}行: <span class="split-equation">${d.amounts.map(money).join(' + ')}</span>`;
  if(type==='split'&&d.amount)return `增加拆分行，新增金额: <span class="split-equation">${money(d.amount)}</span>`;
  if(type==='cancel_split')return'取消拆分并恢复为一条原始流水';
  if(type==='batch_assign'){const label=d.field==='expense_type_id'?'费用类型':'入账',value=logReference(d.field,d.value),cleared=Number(d.cleared_account_count||0);return `批量修改${d.split_ids?.length||0}行，${label}: <span class="log-new">${escapeHtml(value)}</span>${cleared?`<br>自动清空 ${cleared} 行不匹配的入账`:''}`}
  if(type==='one_click_allocate')return `${diffLine('待调配金额',currency(d.old_balance),currency(0))}${diffLine('目标行调整差额','—',currency(d.new_diff))}`;
  if(type==='submit')return `提交${d.dwd_rows||0}条流水，待分配金额: <span class="text-amount">¥0.00</span>`;
  if(type==='withdraw_submit')return `撤回原因: <span class="log-new">${escapeHtml(d.reason||'—')}</span>`;
  if(type==='import')return `导入${d.ods_rows||0}条流水，生成${d.dwd_rows||0}条拆分明细，来源工作表: <span class="log-new">${escapeHtml(d.source_sheet||'—')}</span>${d.organized_sheet?` → <span class="log-new">${escapeHtml(d.organized_sheet)}</span>`:''}`;
  if(type==='summary')return `摘要: <span class="log-new">${escapeHtml(d.summary||'—')}</span>`;
  if(type==='remark')return `摘要: <span class="log-new">${escapeHtml(d.remark||'—')}</span>`;
  if(type==='type_create'&&d.new)return `新增类型: <span class="log-new">${escapeHtml(d.new.name||'—')}</span> <span class="log-detail-label">(${escapeHtml(d.new.code||'')})</span>`;
  if(type==='type_update'&&d.new)return `更新类型: <span class="log-new">${escapeHtml(d.new.name||'—')}</span>，排序 ${escapeHtml(d.new.sort_order??'—')}`;
  if(type==='type_toggle')return `状态调整为: <span class="log-new">${d.is_active?'启用':'停用'}</span>`;
  if(type==='type_delete')return'删除费用类型';
  if(type==='account_create'){const names=(d.expense_type_ids||[]).map(id=>logReference('expense_type_id',id));return `新增入账，所属费用类型: <span class="log-new">${escapeHtml(names.join('、')||'—')}</span>`}
  if(type==='account_update'){const lines=[];if(d.name)lines.push(`入账名称: <span class="log-new">${escapeHtml(d.name)}</span>`);if(d.description)lines.push(`入账说明: <span class="log-new">${escapeHtml(d.description)}</span>`);if(d.sort_order!=null)lines.push(`排序: <span class="log-new">${escapeHtml(d.sort_order)}</span>`);if(d.expense_type_ids)lines.push(`费用类型: <span class="log-new">${escapeHtml(d.expense_type_ids.map(id=>logReference('expense_type_id',id)).join('、'))}</span>`);return lines.join('<br>')||'入账信息已更新'}
  if(type==='account_toggle')return `状态调整为: <span class="log-new">${d.is_active?'启用':'停用'}</span>`;
  if(type==='account_delete')return'删除入账科目';
  return escapeHtml(x.target_description||'已完成操作');
}
function logOperatorSummary(){const selected=state.logOperatorSelections;if(!selected.length)return'全部操作人';return selected.length===1?selected[0]:`${selected[0]} 等 ${selected.length} 项`}
function renderLogOperatorLabel(){$("#logOperator").value=state.logOperatorSelections.join(',');$("#logOperatorLabel").textContent=logOperatorSummary()}
function renderLogOperatorOptions(query=''){
  const normalized=query.trim().toLowerCase(),items=state.logOperatorOptions.filter(value=>!normalized||value.toLowerCase().includes(normalized));
  $("#logOperatorOptions").innerHTML=items.length?items.map(value=>{const selected=state.logOperatorContext?.selected.includes(value)??state.logOperatorSelections.includes(value);return `<button type="button" class="assign-option ${selected?'active':''}" data-log-operator="${escapeHtml(value)}"><input type="checkbox" tabindex="-1" ${selected?'checked':''}><span>${escapeHtml(value)}</span></button>`}).join(''):'<div class="assign-empty">未找到匹配的操作人</div>';
  $("#logOperatorSelectedSummary").textContent=(state.logOperatorContext?.selected||state.logOperatorSelections).length?`已选择 ${(state.logOperatorContext?.selected||state.logOperatorSelections).length} 项`:'未选择';
}
function closeLogOperatorDropdown(){const context=state.logOperatorContext;context?.trigger?.setAttribute('aria-expanded','false');$("#logOperatorDropdown").hidden=true;state.logOperatorContext=null}
function openLogOperatorDropdown(){
  const trigger=$("#logOperatorTrigger");if(state.logOperatorContext){closeLogOperatorDropdown();return}
  closeAssignDropdown(false);window.DateRange.close();hideTablePopover();state.logOperatorContext={trigger,selected:[...state.logOperatorSelections]};trigger.setAttribute('aria-expanded','true');$("#logOperatorSearch").value='';$("#logOperatorDropdown").hidden=false;renderLogOperatorOptions();placeFloating($("#logOperatorDropdown"),trigger,300);setTimeout(()=>$("#logOperatorSearch").focus(),0)
}
async function loadLogs(){
  const data=await api('/api/operation-logs?'+qs({page:state.pages.logs,page_size:state.pageSize,date_from:$("#logDateFrom").value,date_to:$("#logDateTo").value,operation_type:$("#logType").value,operator:state.logOperatorSelections.join(','),keyword:$("#logKeyword").value}));
  const fallbackTypes={import:'导入',split:'拆分',cancel_split:'取消拆分',adjust:'母行调账',child_adjust:'子项调账',restore:'金额复原',one_click_allocate:'一键调配',batch_assign:'批量修改',summary:'摘要修改',remark:'摘要修改（历史）',submit:'提交',withdraw_submit:'撤回提交',type_create:'新增费用类型',type_update:'编辑费用类型',type_toggle:'启停费用类型',type_delete:'删除费用类型',account_create:'新增入账',account_update:'编辑入账',account_toggle:'启停入账',account_delete:'删除入账'};
  const operationTypeMap=new Map(Object.entries(fallbackTypes));(data.operation_types||[]).forEach(x=>operationTypeMap.set(x.value,x.label));
  const operationTypes=[...operationTypeMap].map(([value,label])=>({value,label}));
  state.logOperatorOptions=[...new Set((Array.isArray(data.operators)?data.operators:[]).map(value=>decoded(value)).filter(Boolean))];state.logOperatorSelections=state.logOperatorSelections.filter(value=>state.logOperatorOptions.includes(value));renderLogOperatorLabel();
  const selectedType=$("#logType").value;$("#logType").innerHTML='<option value="">全部操作类型</option>'+operationTypes.map(x=>`<option value="${escapeHtml(x.value)}">${escapeHtml(x.label)}</option>`).join('');$("#logType").value=selectedType;
  const labels=Object.fromEntries(operationTypes.map(x=>[x.value,x.label]));
  const badgeClass=type=>['adjust','child_adjust','restore'].includes(type)?'warning':(['import','split','cancel_split','type_create','type_update','type_toggle','type_delete','account_create','account_update','account_toggle','account_delete'].includes(type)?'info':'success');
  $("#logBody").innerHTML=data.items.map(x=>{const amount=(x.change_amount==null||!['adjust','restore','one_click_allocate'].includes(x.operation_type))?'—':`<span class="${Number(x.change_amount)>=0?'log-amount-positive':'log-amount-negative'}">${Number(x.change_amount)>0?'+':''}${money(x.change_amount)}</span>`;return `<tr><td><strong>${x.log_no}</strong></td><td>${dateTime(x.created_at)}</td><td>${escapeHtml(decoded(x.operator))}</td><td><span class="status-badge ${badgeClass(x.operation_type)}">${labels[x.operation_type]||x.operation_type}</span></td><td>${escapeHtml(logTarget(x))}</td><td><div class="log-detail">${formatLogDetail(x)}</div></td><td class="amount">${amount}</td><td>${escapeHtml(x.ip_address||'—')}</td></tr>`}).join('')||'<tr><td colspan="8" class="empty">暂无操作日志</td></tr>';
  $("#logTotal").textContent=`共 ${data.pagination?.total??data.items.length} 条`;renderPager('logPager',data.pagination,page=>{state.pages.logs=page;loadLogs()});
}

const IMPORT_UPLOAD_DEFAULT_TITLE='选择或拖入银行 Excel 文件';
const IMPORT_UPLOAD_DEFAULT_HINT='支持包含“原数据”和可选“整理后”的 .xlsx，最大 50MB';
function updateImportFileState(file=null){const zone=$("#uploadZone");zone.classList.toggle('has-file',Boolean(file));$("#uploadTitle").textContent=file?file.name:IMPORT_UPLOAD_DEFAULT_TITLE;$("#uploadHint").textContent=file?'文件已选择，可开始导入':IMPORT_UPLOAD_DEFAULT_HINT;zone.title=file?file.name:''}
function resetImportDialog(){const form=$("#importForm");form.reset();$("#uploadZone").classList.remove('drag');updateImportFileState()}
function openImportDialog(){resetImportDialog();$("#importDialog").showModal()}
function closeImportDialog(){resetImportDialog();$("#importDialog").close()}
async function submitImport(event){event.preventDefault();const file=$("#fileInput").files[0];if(!file){toast('请选择Excel文件','error');return}const data=new FormData();data.append('file',file);const button=$("#importSubmit");try{setBusy(button,true,'导入解析中…');const result=await api('/api/import',{method:'POST',body:data});toast(`导入成功：ODS ${result.record_count} 条，DWD ${result.dwd_record_count} 条`);closeImportDialog();state.batchId=result.batch_id;await Promise.all([loadReferenceData(),loadImports(state.page==='imports')]);if(state.page==='statement')await loadStatement()}catch(e){toast(e.message,'error')}finally{setBusy(button,false)}}

function bind(){
  $$('.nav-item[data-page]').forEach(x=>x.onclick=()=>switchPage(x.dataset.page));window.addEventListener('hashchange',()=>switchPage(location.hash.slice(1)));$("#openImport").onclick=$("#openImport2").onclick=openImportDialog;$("#closeImport").onclick=$("#cancelImport").onclick=closeImportDialog;$("#importForm").onsubmit=submitImport;$("#importDialog").addEventListener('close',resetImportDialog);
  $("#batchSelect").onchange=async e=>{state.batchId=e.target.value;state.pages.statement=1;state.expandedOds.clear();await loadStatement()};$("#refreshStatement").onclick=loadStatement;$("#applyStatementFilter").onclick=()=>{state.pages.statement=1;loadStatement()};
  $("#statementKeyword").onkeydown=e=>{if(e.key==='Enter'){state.pages.statement=1;loadStatement()}};
  $("#resetStatement").onclick=()=>{window.DateRange.clear('dateFrom','dateTo');$("#expenseTypeFilter").value='';$("#statementKeyword").value='';state.pages.statement=1;loadStatement()};
  $("#expandAll").onclick=()=>{const splitParents=(state.statement?.rows||[]).filter(x=>x.split_rows.length>1);const expand=!splitParents.every(x=>state.expandedOds.has(x.ods_id));splitParents.forEach(x=>expand?state.expandedOds.add(x.ods_id):state.expandedOds.delete(x.ods_id));renderStatement()};
  $("#submitBatch").onclick=async()=>{if(!confirm('确认提交当前批次？提交后将锁定编辑并供后续看板链路使用。'))return;try{await api(`/api/statement/${state.batchId}/submit`,{method:'POST',body:{}});toast('批次提交成功');await loadImports(false)}catch(e){toast(e.message,'error')}};
  $("#withdrawSubmit").onclick=()=>openModal('撤回提交','WITHDRAW SUBMISSION',`<div class="form-grid"><label class="full"><span><b class="required">*</b> 撤回原因</span><textarea id="withdrawReason" maxlength="500" rows="4" placeholder="请说明数据错误或需要重新编辑的原因" autofocus></textarea></label><div class="full import-rule"><strong>撤回影响</strong><span>撤回后当前批次恢复为可编辑状态；修改完成后需要重新提交，撤回原因将写入操作日志。</span></div></div>`,async()=>{const reason=$("#withdrawReason").value.trim();if(!reason)throw new Error('请填写撤回原因');await api(`/api/statement/${state.batchId}/withdraw-submit`,{method:'POST',body:{reason}});toast('提交已撤回，批次恢复为可编辑状态');await loadImports(false)});
  $("#selectAll").onchange=e=>{$$('.row-check:not(:disabled)').forEach(x=>{x.checked=e.target.checked;e.target.checked?state.selected.add(Number(x.value)):state.selected.delete(Number(x.value))});updateSelectionBar()};$("#clearSelection").onclick=()=>{state.selected.clear();$$('.row-check').forEach(x=>x.checked=false);updateSelectionBar()};
  $("#addType").onclick=()=>editType();$("#searchTypes").onclick=()=>{state.pages.types=1;loadTypes()};$("#resetTypes").onclick=()=>{$("#typeStatus").value='';$("#typeKeyword").value='';state.pages.types=1;loadTypes()};$("#addAccount").onclick=()=>editAccount();$("#searchAccounts").onclick=()=>{state.pages.accounts=1;loadAccounts()};$("#resetAccounts").onclick=()=>{$("#accountTypeFilter").value='';$("#accountStatus").value='';$("#accountKeyword").value='';state.pages.accounts=1;loadAccounts()};$("#searchImports").onclick=()=>{state.pages.imports=1;loadImports(true)};$("#resetImports").onclick=()=>{window.DateRange.clear('importDateFrom','importDateTo');$("#importStatus").value='';$("#importKeyword").value='';state.pages.imports=1;loadImports(true)};$("#searchLogs").onclick=()=>{state.pages.logs=1;loadLogs()};$("#logKeyword").onkeydown=e=>{if(e.key==='Enter'){state.pages.logs=1;loadLogs()}};$("#exportLogs").onclick=()=>location.href='/api/operation-logs/export?'+qs({date_from:$("#logDateFrom").value,date_to:$("#logDateTo").value,operation_type:$("#logType").value,operator:state.logOperatorSelections.join(','),keyword:$("#logKeyword").value});
  $("#typeStatus").onchange=()=>{state.pages.types=1;loadTypes()};$("#typeKeyword").onkeydown=e=>{if(e.key==='Enter'){state.pages.types=1;loadTypes()}};
  $("#accountTypeFilter").onchange=$("#accountStatus").onchange=()=>{state.pages.accounts=1;loadAccounts()};$("#accountKeyword").onkeydown=e=>{if(e.key==='Enter'){state.pages.accounts=1;loadAccounts()}};
  $("#resetLogs").onclick=()=>{closeLogOperatorDropdown();window.DateRange.clear('logDateFrom','logDateTo');$("#logType").value='';state.logOperatorSelections=[];renderLogOperatorLabel();$("#logKeyword").value='';state.pages.logs=1;loadLogs()};
  $("#logOperatorTrigger").onclick=e=>{e.stopPropagation();openLogOperatorDropdown()};$("#logOperatorSearch").oninput=e=>renderLogOperatorOptions(e.target.value);$("#logOperatorSearch").onkeydown=e=>{if(e.key==='Escape')closeLogOperatorDropdown()};$("#logOperatorOptions").onclick=e=>{const option=e.target.closest('[data-log-operator]');if(!option||!state.logOperatorContext)return;const value=option.dataset.logOperator,selected=state.logOperatorContext.selected;state.logOperatorContext.selected=selected.includes(value)?selected.filter(item=>item!==value):[...selected,value];renderLogOperatorOptions($("#logOperatorSearch").value)};$("#logOperatorConfirm").onclick=()=>{if(!state.logOperatorContext)return;state.logOperatorSelections=[...state.logOperatorContext.selected];closeLogOperatorDropdown();state.pages.logs=1;loadLogs()};$("#logOperatorCancel").onclick=closeLogOperatorDropdown;$("#logOperatorDropdown").onclick=e=>e.stopPropagation();
  $("#assignSearch").oninput=e=>renderAssignOptions(e.target.value);
  $("#assignSearch").onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();const context=state.assignContext,query=e.currentTarget.value.trim();if(!context||context.requiresExpense)return;const exact=context.items.find(x=>x.name===query);if(exact){closeAssignDropdown(false);assignResolved(context.trigger,exact)}else if(query)showAutoAdd(context.trigger,query)}else if(e.key==='Escape')closeAssignDropdown(false)};
  $("#assignSearch").onblur=()=>setTimeout(()=>{const drop=$("#assignDropdown");if(state.assignContext&&!drop.contains(document.activeElement))closeAssignDropdown(true)},80);
  document.addEventListener('mousedown',event=>{const assign=$("#assignDropdown"),operator=$("#logOperatorDropdown"),operatorTrigger=$("#logOperatorTrigger");if(state.assignContext&&!assign.contains(event.target)&&!state.assignContext.trigger.contains(event.target))closeAssignDropdown(true);if(state.logOperatorContext&&!operator.contains(event.target)&&!operatorTrigger.contains(event.target))closeLogOperatorDropdown()});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){closeAssignDropdown(false);closeLogOperatorDropdown()}});
  const zone=$("#uploadZone");['dragenter','dragover'].forEach(ev=>zone.addEventListener(ev,e=>{e.preventDefault();zone.classList.add('drag')}));['dragleave','drop'].forEach(ev=>zone.addEventListener(ev,e=>{e.preventDefault();zone.classList.remove('drag')}));zone.addEventListener('drop',e=>{if(e.dataTransfer.files.length){$("#fileInput").files=e.dataTransfer.files;updateImportFileState(e.dataTransfer.files[0])}});$("#fileInput").onchange=e=>updateImportFileState(e.target.files[0]||null);
}

async function init(){enhanceNativeSelects();bind();try{await loadReferenceData();await loadImports(false);switchPage(location.hash.slice(1)||'statement')}catch(error){toast(error.message,'error')}}
init();
