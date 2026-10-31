const state = {
  reports: [], shops: [], files: [], selectedFiles: new Set(), feeItems: [], selectedFees: new Set(), feeBatchMode: false, feePage: 1, feePageSize: 10,
  feeCategories: [], feeCategoryOptions: [], categoryPage: 1, categoryPageSize: 10, rawFeeItems: [], rawFeePage: 1, rawFeePageSize: 10, currentEtlDetail: null,
  detailRequestId: 0, detailRequestController: null, activeDetailDialog: null,
  runPage: 1, runPageSize: 10, runFilters: {operator: [], status: [], keyword: '', date_field: 'created_at'}, runOperatorOptions: [], etlPage: 1, etlPageSize: 10, etlFilters: {operator: [], status: [], keyword: '', date_field: 'started_at'}, etlOperatorOptions: [], logPage: 1, logPageSize: 10, dateRangeContext: null, copyMessages: new Map(),
  financeView: 'financeOverview', financeResource: '', financeItems: [], financeSummary: null, financeAdjustmentSubpage: 'promotion', financePage: 1, financePageSize: 10, financeDialogMode: '', financeExpenseTypes: [], financeExpenseTypesLoaded: false, financeFilters: {platform: [], company: [], shop: [], expense_type: [], finance_operator: []}, financeOperatorOptions: [], financeDropdown: null, financeRechargeHistoryPage: 1, financeRechargeHistoryPageSize: 10, financeRechargeHistoryShopCode: '', financeRechargeHistoryRequestId: 0,
  currentPage: 'upload', currentRunId: null, pollingRuns: new Set(), uploading: false, health: null, dropdown: null, assignContext: null, popoverAction: null
};
state.logOperatorSelections=[];state.logOperatorOptions=[];
const AUTO_REMOVE_FILE_STATUSES = new Set(['success', 'duplicate']);
const uploadRemovalTimers = new Map();
const PENDING_UPLOAD_DB_NAME = 'mocc_file_ingest';
const PENDING_UPLOAD_DB_VERSION = 1;
const PENDING_UPLOAD_STORE = 'pending_files';
let pendingUploadDbPromise = null;
let pendingUploadWriteQueue = Promise.resolve();
let pendingUploadPersistenceWarned = false;
const pageMeta = {
  upload: ['数据上传', '支持文件名自动识别与表格内快速修正'],
  runs: ['导入记录', '查看API、影刀和网页采集会话'],
  etl: ['ETL任务', '串行执行、失败隔离并可人工重试'],
  logs: ['操作日志', '统一审计文件、任务和费用映射操作'],
  feeCategories: ['一级分类管理', '维护平台费用一级分类编码、名称、排序与状态'],
  feeMappings: ['平台收支配置', '分别维护经营归属和分类；未映射分类保留金额'],
  sceneRules: ['收支场景清洗规则', '维护场景命名规则，预览匹配结果并检查合并冲突'],
  rawFees: ['全部收支类型', '查看收入、支出和不计入项目；保留未映射明细'],
  financeOverview: ['经营指标总览', 'GSV目标、推广预算与营销预算执行情况'],
  financeGsv: ['GSV目标管理', '按月份、平台、公司与店铺维护目标并跟踪实际完成'],
  financePromotion: ['推广预算管理', '总预算、已分配、待分配、充值、消耗与理论余额总览，并直接维护店铺预算'],
  financeAdjustments: ['预算调整记录', '查看推广总预算每次修改的前后金额和操作留痕'],
  financeRecharges: ['充值流水', '基于DIM有效店铺直接登记推广账户充值'],
  financeSpend: ['推广消耗', '只读查看实际推广消耗与预算执行'],
  financeMarketing: ['营销预算管理', '整体月度营销预算及费用登记'],
  financeExpenseTypes: ['营销费用类型管理', '维护营销费用登记可选类型及启停状态'],
};
const financePagePermissions={financeOverview:'finance_budget.overview.view',financeGsv:'finance_budget.gsv.view',financePromotion:'finance_budget.promotion.view',financeAdjustments:'finance_budget.adjustment.view',financeRecharges:'finance_budget.recharge.view',financeSpend:'finance_budget.spend.view',financeMarketing:'finance_budget.marketing.view',financeExpenseTypes:'finance_budget.expense_type.view'};
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '—';
const money = value => Number(value||0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const day = value => value ? String(value).slice(0,10) : '—';
const statusLabel = value => ({selected:'已选择',draft:'待上传',ready:'待处理',processing:'处理中',success:'成功',success_with_warnings:'成功（有提醒）',failed:'失败',duplicate:'重复',no_change:'无变化',queued:'排队中',running:'执行中',partial_failed:'部分失败',skipped:'已跳过',deferred:'待数据就绪',uploaded:'已上传',active:'启用',mapped:'已映射',unmapped:'未映射',inactive:'已停用',pending:'待审批',approved:'已通过',rejected:'已拒绝'}[value] || value || '—');

function createClientId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let index=0; index<bytes.length; index++) bytes[index]=Math.floor(Math.random()*256);
  bytes[6]=(bytes[6]&0x0f)|0x40;
  bytes[8]=(bytes[8]&0x3f)|0x80;
  const hex=[...bytes].map(value=>value.toString(16).padStart(2,'0'));
  return `${hex.slice(0,4).join('')}-${hex.slice(4,6).join('')}-${hex.slice(6,8).join('')}-${hex.slice(8,10).join('')}-${hex.slice(10).join('')}`;
}

function openPendingUploadDb() {
  if (pendingUploadDbPromise) return pendingUploadDbPromise;
  if (typeof indexedDB === 'undefined') return Promise.reject(new Error('当前浏览器不支持未提交文件暂存'));
  pendingUploadDbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(PENDING_UPLOAD_DB_NAME, PENDING_UPLOAD_DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(PENDING_UPLOAD_STORE)) db.createObjectStore(PENDING_UPLOAD_STORE, {keyPath:'id'});
    };
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => db.close();
      resolve(db);
    };
    request.onerror = () => reject(request.error || new Error('未提交文件暂存初始化失败'));
    request.onblocked = () => reject(new Error('未提交文件暂存被其他页面占用'));
  }).catch(error => {
    pendingUploadDbPromise = null;
    throw error;
  });
  return pendingUploadDbPromise;
}
function queuePendingUploadWrite(operation) {
  const next = pendingUploadWriteQueue.then(operation, operation);
  pendingUploadWriteQueue = next.catch(() => undefined);
  return next;
}
function notifyPendingUploadPersistenceError(error) {
  if (pendingUploadPersistenceWarned) return;
  pendingUploadPersistenceWarned = true;
  console.warn('未提交文件暂存失败', error);
  if (typeof toast === 'function') toast('未提交文件暂存失败，离开页面后可能需要重新选择', true);
}
function pendingUploadRecord(item) {
  return {
    id: item.id,
    file: item.file,
    billDate: item.billDate || '',
    file_name: item.file.name,
    file_type: item.file.type || '',
    file_last_modified: item.file.lastModified || 0,
    selection: {...(item.selection || {})},
    selected: state.selectedFiles.has(item.id),
    guess_message: item.guessMessage || '',
    upload_status: item.uploadStatus || 'selected',
    server_status: item.serverStatus || '',
    server_error: item.serverError || '',
    server_output: item.serverOutput || '',
    file_task_id: item.fileTaskId || '',
    run_id: item.runId || '',
    run_status: item.runStatus || '',
    server_updated_at: item.serverUpdatedAt || 0,
    manual_corrected: Boolean(item.manualCorrected),
    saved_at: Date.now(),
  };
}
function persistPendingFile(item) {
  if (!item?.file) return Promise.resolve(false);
  return queuePendingUploadWrite(async () => {
    if (!state.files.some(file => file.id === item.id)) return false;
    try {
      const db = await openPendingUploadDb();
      await new Promise((resolve, reject) => {
        const transaction = db.transaction(PENDING_UPLOAD_STORE, 'readwrite');
        transaction.objectStore(PENDING_UPLOAD_STORE).put(pendingUploadRecord(item));
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error || new Error('未提交文件暂存失败'));
        transaction.onabort = () => reject(transaction.error || new Error('未提交文件暂存失败'));
      });
      return true;
    } catch (error) {
      notifyPendingUploadPersistenceError(error);
      return false;
    }
  });
}
function deletePendingFile(id) {
  return queuePendingUploadWrite(async () => {
    try {
      const db = await openPendingUploadDb();
      await new Promise((resolve, reject) => {
        const transaction = db.transaction(PENDING_UPLOAD_STORE, 'readwrite');
        transaction.objectStore(PENDING_UPLOAD_STORE).delete(id);
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error || new Error('未提交文件暂存清理失败'));
        transaction.onabort = () => reject(transaction.error || new Error('未提交文件暂存清理失败'));
      });
    } catch (error) {
      console.warn('未提交文件暂存清理失败', error);
    }
  });
}
async function readPendingFiles() {
  const db = await openPendingUploadDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(PENDING_UPLOAD_STORE, 'readonly');
    const request = transaction.objectStore(PENDING_UPLOAD_STORE).getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error || new Error('未提交文件暂存读取失败'));
    transaction.onerror = () => reject(transaction.error || new Error('未提交文件暂存读取失败'));
  });
}
function restorePendingFile(record) {
  if (!record?.file || typeof Blob === 'undefined' || !(record.file instanceof Blob)) throw new Error('未提交文件暂存内容无效');
  const file = new File([record.file], String(record.file_name || '未命名文件'), {
    type: String(record.file_type || record.file.type || ''),
    lastModified: Number(record.file_last_modified) || Date.now(),
  });
  const serverStatus = String(record.server_status || '');
  const uploadStatus = serverStatus === 'failed' || record.upload_status === 'failed'
    ? 'failed'
    : serverStatus
      ? 'uploaded'
      : record.upload_status === 'uploading' ? 'selected' : String(record.upload_status || 'selected');
  return {
    id: String(record.id), file, selection: selectionFromMeta(record.selection || null),
    billDate: String(record.billDate || ''),
    guessMessage: String(record.guess_message || ''), uploadStatus, uploadProgress: 0,
    serverStatus, serverError: String(record.server_error || ''), serverOutput: String(record.server_output || ''),
    fileTaskId: String(record.file_task_id || ''), manualCorrected: Boolean(record.manual_corrected),
    runId: String(record.run_id || ''), runStatus: String(record.run_status || ''),
    serverUpdatedAt: Number(record.server_updated_at) || 0,
  };
}
async function restorePendingFiles() {
  let records;
  try { records = await readPendingFiles(); }
  catch (error) { notifyPendingUploadPersistenceError(error); return; }
  const restored = [];
  for (const record of records) {
    if (state.files.some(item => item.id === String(record.id))) continue;
    try { restored.push({item: restorePendingFile(record), selected: Boolean(record.selected)}); }
    catch (error) { console.warn('跳过无效的未提交文件暂存', error); }
  }
  restored.forEach(({item, selected}) => {
    state.files.push(item);
    if (selected && !isSubmitted(item)) state.selectedFiles.add(item.id);
    if (AUTO_REMOVE_FILE_STATUSES.has(item.serverStatus)) scheduleSuccessfulFileRemoval(item);
  });
  if (restored.length) {
    renderFiles();
    toast(`已恢复 ${restored.length} 个未提交文件`);
  }
}

async function syncUploadedFiles(){
  if(state.syncingUploads||state.uploading||document.hidden)return;
  const pending=state.files.filter(item=>item.fileTaskId&&!AUTO_REMOVE_FILE_STATUSES.has(item.serverStatus));
  if(!pending.length)return;
  state.syncingUploads=true;
  try{
    const runs=new Set();
    for(const item of pending){
      if(item.runId){runs.add(item.runId);continue;}
      try{const detail=await api(`/api/ingest/file-tasks/${item.fileTaskId}/review-context`);applyRunDetail(detail);item.runId=detail.run.run_id;runs.add(item.runId);}
      catch(error){item.syncError=error.message;}
    }
    await Promise.allSettled([...runs].map(async runId=>{
      if(state.pollingRuns.has(runId))return;
      try{const detail=await api(`/api/ingest/runs/${runId}`);applyRunDetail(detail);
        if(['ready','processing'].includes(detail.run.status))void pollRun(runId);
      }catch(error){state.files.filter(item=>item.runId===runId).forEach(item=>{item.syncError=error.message;});}
    }));
    renderFiles();
  }finally{state.syncingUploads=false;}
}

async function api(path, options={}) {
  if(options.method&&options.method!=='GET'&&/^\/api\/ingest\/fee-(mappings|categories)/.test(path)){
    const capability=await api('/api/ingest/health');
    if(capability.operating_treatment_version!==2)throw new Error('经营收支功能已升级，请先重启后台服务后再保存，避免旧版逻辑修改金额');
  }
  const response = await fetch(path, {headers:{'X-Operator':encodeURIComponent('网页用户'), ...(options.body instanceof FormData ? {} : {'Content-Type':'application/json'}), ...(options.headers||{})}, ...options});
  const result = await response.json().catch(error=>{if(error.name==='AbortError')throw error;return {message:`HTTP ${response.status}`};});
  if (!response.ok || result.code) throw new Error(result.message || `请求失败(${response.status})`);
  return result.data;
}
function toast(message,type='success'){const t=type===true?'error':type;if(window.showAppToast&&window.hasOpenEditor?.())return window.showAppToast(message,t);const node=$('toast');node.textContent=message;node.className=`toast show ${t}`;node.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>{node.hidden=true},3500)}
function isWarningMessage(value) { return /(?:\[\s*warn(?:ing)?\s*\]|\bwarn(?:ing)?\b|警告|告警|提醒|商品\s*编码\s*未配置)/i.test(String(value || '')); }
function statusTone(status, errorMessage = '', outputSummary = '') {
  if (['failed', 'partial_failed'].includes(status)) return 'error';
  if (['success_with_warnings', 'deferred', 'skipped', 'unmapped', 'inactive'].includes(status)) return 'warning';
  if (isWarningMessage(String(outputSummary || '') + '\n' + String(errorMessage || ''))) return 'warning';
  if (errorMessage) return 'error';
  if (['success', 'duplicate', 'active', 'mapped'].includes(status)) return 'success';
  return 'info';
}
function messageClass(tone) { return tone === 'error' ? 'task-error' : tone === 'warning' ? 'task-warning' : ''; }
function tag(status, tone = '') { return `<span class="status-tag ${esc(status)}${tone ? ` tone-${esc(tone)}` : ''}">${esc(statusLabel(status))}</span>`; }
function setCopyMessage(key, message) { if (message) state.copyMessages.set(String(key), String(message)); }
async function clipboardReadback(text) {
  if (!navigator.clipboard?.readText) return null;
  try { return (await navigator.clipboard.readText()) === text; }
  catch (_error) { return null; }
}
function copyWithSelection(text) {
  const textarea=document.createElement('textarea');
  textarea.value=text; textarea.setAttribute('readonly',''); textarea.style.cssText='position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;opacity:0;pointer-events:none;';
  document.body.appendChild(textarea); textarea.focus({preventScroll:true}); textarea.select(); textarea.setSelectionRange?.(0,text.length);
  const handleCopy=event=>{if(event.clipboardData){event.clipboardData.setData('text/plain',text);event.preventDefault();}};
  document.addEventListener('copy',handleCopy,true);
  let copied=false;
  try { copied=document.execCommand('copy'); } catch(_error) { copied=false; }
  finally { document.removeEventListener('copy',handleCopy,true); textarea.remove(); }
  return copied;
}
async function writeClipboard(message) {
  const text = String(message || '');
  if (!text) throw new Error('没有可复制的错误信息');
  // 先在当前点击事件中同步执行降级复制，避免原生 API 失败后丢失用户手势。
  const fallbackCopied=copyWithSelection(text);
  let nativeError=null;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      const verified=await clipboardReadback(text);
      if(verified!==false)return;
    } catch(error) { nativeError=error; }
  }
  const verified=fallbackCopied ? await clipboardReadback(text) : false;
  if (fallbackCopied && verified!==false)return;
  if(nativeError && !fallbackCopied)throw new Error('浏览器拒绝访问剪切板，请检查页面权限后重试');
  throw new Error('复制失败，请手动选择错误信息');
}
async function copyMessage(key, successMessage = '错误信息已复制') {
  try { await writeClipboard(state.copyMessages.get(String(key))); toast(successMessage); }
  catch (error) { toast(error.message, true); }
}

function switchPage(page) {
  closeFinanceAssignDropdown();
  if(page==='financeBudget')page='financeOverview';
  if(page==='financeShopBudget')page='financePromotion';
  if(!pageMeta[page])page='upload';
  if(financePagePermissions[page]&&window.currentPermissions instanceof Set&&!window.currentPermissions.has(financePagePermissions[page])){toast('无权进入该经营配置页面','error');return;}
  state.currentPage=page;
  const isFinance=page.startsWith('finance');const domPage=isFinance?'financeBudget':page;
  document.querySelectorAll('.page').forEach(node=>node.classList.toggle('active', node.id===`${domPage}Page`));
  document.querySelectorAll('.nav-item[data-page]').forEach(node=>{const active=node.dataset.page===page;node.classList.toggle('active',active);active?node.setAttribute('aria-current','page'):node.removeAttribute('aria-current')});
  document.querySelectorAll('.nav-group').forEach(group=>{
    const active=Boolean(group.querySelector(`.nav-item[data-page="${page}"]`));group.classList.toggle('active',active);
    if(active){group.classList.add('open');group.querySelector('.nav-group-toggle')?.setAttribute('aria-expanded','true');}
  });
  [$('pageTitle').textContent,$('pageSubtitle').textContent]=pageMeta[page];
  if($('financeTopbarControls'))$('financeTopbarControls').hidden=!isFinance;
  history.replaceState(null,'',`#${page}`);
  if(page==='runs')loadRuns();if(page==='etl')loadEtls();if(page==='logs')loadLogs();
  if(page==='feeCategories')loadCategoryPage();if(page==='feeMappings')loadFees();if(page==='rawFees')loadRawFees();
  if(page==='sceneRules')loadSceneRules();
  if(isFinance){state.financePage=1;state.financeView=page;activateFinanceView(page);}
}

function platformOptions() {
  const platforms=[...new Map(state.reports.map(r=>[r.platform_code,r.platform_name])).entries()];
  const html='<option value="">全部平台</option>'+platforms.map(([code,name])=>`<option value="${esc(code)}">${esc(name)}</option>`).join('');
  const formHtml='<option value="">请选择平台</option>'+platforms.map(([code,name])=>`<option value="${esc(code)}">${esc(name)}</option>`).join('');
  $('feePlatform').innerHTML=html;$('rawPlatform').innerHTML=html;$('categoryPlatform').innerHTML=html;$('categoryFormPlatform').innerHTML=formHtml;
}

function selectionFromMeta(meta) {
  const shop=state.shops.find(item=>item.platform_code===meta?.platform_code&&item.shop_code===meta?.shop_code);
  return {
    platform_code:meta?.platform_code||shop?.platform_code||'', company_code:meta?.company_code||shop?.company_code||'',
    company_name:meta?.company_name||shop?.company_name||'', shop_code:meta?.shop_code||shop?.shop_code||'',
    shop_name:meta?.shop_name||shop?.shop_name||'', report_type:meta?.report_type||'',
  };
}
function fileExtension(file) { const index=file.name.lastIndexOf('.'); return index<0?'':file.name.slice(index).toLowerCase(); }
function matchingShopRows(item,excludeField='') {
  const s=item.selection||{};
  return state.shops.filter(shop=>(excludeField==='platform'||!s.platform_code||shop.platform_code===s.platform_code)
    &&(excludeField==='company'||!s.company_code||shop.company_code===s.company_code)
    &&(excludeField==='shop'||!s.shop_name||shop.shop_name===s.shop_name));
}
function autoFillUniqueFacets(item) {
  const s=item.selection;
  for(let pass=0;pass<3;pass++) {
    const rows=matchingShopRows(item); if(!rows.length)break; let changed=false;
    const platforms=uniqueOptions(rows,row=>row.platform_code,row=>row.platform_name);
    const companies=uniqueOptions(rows,row=>row.company_code,row=>row.company_name);
    const shops=uniqueOptions(rows,row=>row.shop_name,row=>row.shop_name);
    if(!s.platform_code&&platforms.length===1){s.platform_code=platforms[0].value;changed=true;}
    if(!s.company_code&&companies.length===1){s.company_code=companies[0].value;s.company_name=companies[0].label;changed=true;}
    if(!s.shop_name&&shops.length===1){s.shop_name=shops[0].value;changed=true;}
    if(!changed)break;
  }
  const exact=matchingShopRows(item);s.shop_code=exact.length===1?exact[0].shop_code:'';
  if(s.report_type&&!state.reports.some(report=>report.report_type===s.report_type&&report.platform_code===s.platform_code))s.report_type='';
}
function itemReadiness(item) {
  const s=item.selection||{}; const missing=[];
  if(!s.platform_code)missing.push('平台'); if(!s.company_code)missing.push('公司'); if(!s.shop_name)missing.push('店铺'); if(!s.report_type)missing.push('报表名称');
  const report=state.reports.find(r=>r.report_type===s.report_type);
  const matches=matchingShopRows(item); const shop=matches.length===1?matches[0]:null;
  if(missing.length)return {ready:false,message:`请补充${missing.join('、')}`,report,shop};
  if(matches.length>1)return {ready:false,message:`当前条件匹配到${matches.length}条DIM，请继续选择平台或公司`,report,shop};
  if(!matches.length)return {ready:false,message:'平台、公司、店铺组合未匹配到DIM',report,shop};
  if(!report||report.platform_code!==s.platform_code)return {ready:false,message:'报表与平台不匹配',report,shop};
  if(!(report.extensions||[]).includes(fileExtension(item.file)))return {ready:false,message:`${report.report_name}不支持${fileExtension(item.file)||'无扩展名'}文件`,report,shop};
  return {ready:true,message:'可提交',report,shop,meta:{...report,...shop,matched:true}};
}
function isSubmitted(item) { return ['uploaded','processing','success','duplicate'].includes(item.serverStatus); }
function uniqueOptions(items,key,label) { return [...new Map(items.map(item=>[key(item),{value:key(item),label:label(item),raw:item}])).values()].filter(item=>item.value); }
function fieldOptions(item,field) {
  const s=item.selection||{};
  if(field==='platform')return uniqueOptions(matchingShopRows(item,'platform'),row=>row.platform_code,row=>row.platform_name);
  if(field==='company')return uniqueOptions(matchingShopRows(item,'company'),row=>row.company_code,row=>row.company_name);
  if(field==='shop')return uniqueOptions(matchingShopRows(item,'shop'),row=>row.shop_name,row=>row.shop_name);
  return uniqueOptions(state.reports.filter(report=>!s.platform_code||report.platform_code===s.platform_code),report=>report.report_type,report=>report.report_name);
}
function fieldValue(item,field) { return ({platform:item.selection.platform_code,company:item.selection.company_code,shop:item.selection.shop_name,report:item.selection.report_type})[field]||''; }
function fieldLabel(item,field) {
  const value=fieldValue(item,field); return fieldOptions(item,field).find(option=>option.value===value)?.label||'';
}
function fieldPlaceholder(field) { return ({platform:'选择平台',company:'选择公司',shop:'选择店铺',report:'选择报表'})[field]; }
function optionTone(label) { let hash=0;for(const char of String(label||''))hash=(hash*31+char.charCodeAt(0))|0;return Math.abs(hash)%6; }
function cellSelectHtml(item,field,disabled=false) {
  if((field==='company'||field==='shop')&&!state.uploading&&!isSubmitted(item))disabled=false;
  const label=fieldLabel(item,field); const value=fieldValue(item,field); const placeholder=fieldPlaceholder(field);
  return `<button class="cell-select" data-cell-select="${field}" data-item-id="${item.id}" title="${esc(label||placeholder)}" ${disabled?'disabled':''}><span class="cell-select-value ${label?'':'placeholder'}">${label?`<span class="cell-option-pill tone-${optionTone(label)}">${esc(label)}</span>`:esc(placeholder)}</span><svg><use href="#i-chevron-down"/></svg></button>`;
}
function applyFieldSelection(item,field,value) {
  const options=fieldOptions(item,field); const option=options.find(entry=>entry.value===value); if(!option)return;
  if(field==='platform')item.selection.platform_code=value;
  if(field==='company'){item.selection.company_code=value;item.selection.company_name=option.label;}
  if(field==='shop'){item.selection.shop_name=value;item.selection.shop_code='';}
  if(field==='report')item.selection.report_type=value;
  if(field!=='report')autoFillUniqueFacets(item);
  item.manualCorrected=true; item.serverError=''; closeCellDropdown(); renderFiles(); void persistPendingFile(item);
}

function clearFileRemovalTimer(id) {
  const timer=uploadRemovalTimers.get(id); if(!timer)return;
  clearTimeout(timer.fade); if(timer.remove)clearTimeout(timer.remove); uploadRemovalTimers.delete(id);
}
function scheduleSuccessfulFileRemoval(item) {
  if(!item||item.removalScheduled||!AUTO_REMOVE_FILE_STATUSES.has(item.serverStatus))return;
  item.removalScheduled=true;
  const timer={fade:null,remove:null};
  timer.fade=setTimeout(()=>{
    const current=state.files.find(file=>file.id===item.id);
    if(!current){uploadRemovalTimers.delete(item.id);return;}
    current.removing=true; renderFiles();
    timer.remove=setTimeout(()=>{
      uploadRemovalTimers.delete(item.id);
      if(state.files.some(file=>file.id===item.id))removeFile(item.id);
    },320);
  },2000);
  uploadRemovalTimers.set(item.id,timer);
}
function errorElementId(id) { return `upload-error-${String(id).replace(/[^a-zA-Z0-9_-]/g,'')}`; }
function renderErrorDisclosure(item) {
  const message=String(item.serverError||'').trim(); if(!message)return '';
  const key=`file:${item.id}`,contentId=errorElementId(item.id); setCopyMessage(key,message);
  return `<tr class="upload-error-row" data-error-block="${esc(key)}" hidden><td colspan="8"><div class="row-error"><div class="row-error-content" id="${contentId}" hidden><pre class="task-error">${esc(message)}</pre><div class="row-error-actions"><button type="button" class="copy-error-button" data-copy-message="${esc(key)}" data-copy-kind="error"><svg><use href="#i-copy"/></svg>复制错误信息</button></div></div></div></td></tr>`;
}
function renderRecognitionStatus(item, recognition) {
  const message=String(item.serverError||'').trim();
  if(!message)return `<span class="recognition-tag ${recognition.tone}" title="${esc(recognition.label)}"><svg><use href="#i-${recognition.tone==='success'?'check-circle':recognition.tone==='warning'?'info':recognition.tone==='error'?'close':'loader'}"/></svg>${esc(recognition.label)}</span>`;
  const key=`file:${item.id}`,contentId=errorElementId(item.id);
  return `<button type="button" class="recognition-tag ${recognition.tone} recognition-error-toggle" data-error-toggle="${esc(key)}" aria-expanded="false" aria-controls="${contentId}" title="展开或收起导入失败信息"><svg><use href="#i-close"/></svg><span>${esc(recognition.label)}</span><svg class="recognition-chevron"><use href="#i-chevron-down"/></svg></button>`;
}
function detailErrorMessage(item) {
  const error=String(item?.error_message||'').trim();
  if(error)return error;
  return ['failed','skipped','deferred'].includes(item?.status)?String(item?.output_summary||'').trim():'';
}
function detailMessage(item) {
  const message=detailErrorMessage(item);
  if(message)return message;
  const output=String(item?.output_summary||'').trim();
  return statusTone(item?.status,item?.error_message,item?.output_summary)==='warning'?output:'';
}
function detailCopyMessageButton(key,message,tone='error') {
  if(!message)return '';
  const label=tone==='warning'?'复制警告信息':'复制错误信息';
  setCopyMessage(key,message);
  return `<button type="button" class="text-button detail-action error-copy-button" data-copy-message="${esc(key)}" data-copy-kind="${tone==='warning'?'warning':'error'}" title="${label}"><svg><use href="#i-copy"/></svg>${label}</button>`;
}
function toggleErrorDisclosure(button) {
  const content=document.getElementById(button.getAttribute('aria-controls')),block=content?.closest('[data-error-block]'); if(!block||!content)return;
  const expanded=button.getAttribute('aria-expanded')==='true'; button.setAttribute('aria-expanded',String(!expanded)); content.hidden=expanded; block.classList.toggle('expanded',!expanded);
  block.hidden=expanded; button.classList.toggle('expanded',!expanded);
  const label=button.querySelector('em'); if(label)label.textContent=expanded?'展开':'收起';
}
function closeCellDropdown() {
  if(state.dropdown?.button)state.dropdown.button.classList.remove('open');
  state.dropdown=null; $('cellDropdown').hidden=true;
}
function renderDropdownOptions(query='') {
  if(!state.dropdown)return; const keyword=query.trim().toLocaleLowerCase();
  const options=state.dropdown.options.filter(option=>!keyword||option.label.toLocaleLowerCase().includes(keyword));
  let previousTone=-1;
  $('cellDropdownOptions').innerHTML=options.length?options.map(option=>{let tone=optionTone(option.label);if(tone===previousTone)tone=(tone+1)%6;previousTone=tone;return `<button class="cell-dropdown-option ${option.value===state.dropdown.value?'selected':''}" data-option-value="${esc(option.value)}" title="${esc(option.label)}"><span class="cell-option-pill tone-${tone}">${esc(option.label)}</span></button>`;}).join(''):'<div class="cell-dropdown-empty">没有匹配选项</div>';
}
function openCellDropdown(button,item,field) {
  closeCellDropdown(); const options=fieldOptions(item,field); const dropdown=$('cellDropdown'); const rect=button.getBoundingClientRect();
  state.dropdown={button,item,field,options,value:fieldValue(item,field)}; button.classList.add('open'); $('cellDropdownSearch').value=''; renderDropdownOptions(); dropdown.hidden=false;
  const width=Math.max(240,Math.min(320,rect.width+80)); dropdown.style.width=`${width}px`; dropdown.style.left=`${Math.max(8,Math.min(rect.left,window.innerWidth-width-8))}px`;
  const proposedTop=rect.bottom+4; dropdown.style.top=`${proposedTop+dropdown.offsetHeight>window.innerHeight?Math.max(8,rect.top-dropdown.offsetHeight-4):proposedTop}px`; $('cellDropdownSearch').focus();
}

async function addFiles(fileList) {
  const added=[...fileList].map(file=>({id:createClientId(),file,selection:selectionFromMeta(null),guessMessage:'正在识别文件名',uploadStatus:'selected',uploadProgress:0,serverStatus:'',serverError:''}));
  if(!added.length)return; state.files.push(...added); renderFiles(); $('fileInput').value='';
  await Promise.all(added.map(item=>persistPendingFile(item)));
  await Promise.all(added.map(async item=>{try{const guessed=await api(`/api/ingest/guess?filename=${encodeURIComponent(item.file.name)}`);if(guessed.matched){item.selection=selectionFromMeta(guessed);item.guessMessage='文件名识别成功';}else item.guessMessage=guessed.message||'文件名未完整识别';}catch(exc){item.guessMessage=exc.message;}finally{void persistPendingFile(item);}}));
  renderFiles(); const ready=added.filter(item=>itemReadiness(item).ready).length;
  toast(ready===added.length?`已识别 ${ready} 个文件，可勾选提交`:`已加入 ${added.length} 个文件，${added.length-ready} 个需要在表格中修正`);
}
function renderUploadFileList() {
  $('uploadFileList').innerHTML=state.files.map(item=>{
    const status=item.uploadStatus||'selected'; const serverUi=fileTaskUiStatus(item); const uploading=status==='uploading'; const uploaded=status==='uploaded'&&!serverUi; const failed=status==='failed'||serverUi?.tone==='failed'||serverUi?.tone==='error';
    const rowClass=serverUi?.tone==='success'?'ods-success':serverUi?.tone==='warning'?'warning':serverUi?.tone==='duplicate'?'duplicate':uploading?'uploading':uploaded?'uploaded':failed?'failed':''; const removing=item.removing?' is-removing':''; const icon=uploading?'i-loader':serverUi?.tone==='success'?'i-check-circle':serverUi?.tone==='warning'?'i-info':serverUi?.tone==='duplicate'?'i-info':uploaded?'i-check-circle':failed?'i-close':'i-loader';
    const label=uploading?`上传中 ${Math.round(item.uploadProgress||0)}%`:serverUi?.label|| (uploaded?'上传成功':failed?'上传失败':'未上传');
    return `<div class="upload-file-item ${rowClass}${removing}"><svg class="upload-file-icon ${uploading?'spin':''}"><use href="#i-file-sheet"/></svg><div class="upload-file-main"><div class="upload-file-name" title="${esc(item.file.name)}">${esc(item.file.name)}</div>${uploading?`<div class="upload-file-progress"><span style="width:${Math.max(2,item.uploadProgress||0)}%"></span></div>`:''}</div><span class="upload-state"><svg class="${uploading?'spin':''}"><use href="#${icon}"/></svg>${label}</span><button class="upload-file-remove" data-upload-remove="${item.id}" title="从页面移除" ${state.uploading||item.removing?'disabled':''}><svg><use href="#i-close"/></svg></button></div>`;
  }).join('');
}
function renderFiles() {
  $('uploadImportMode').disabled=state.uploading;$('uploadCompleteExport').disabled=state.uploading;
  document.querySelector('[data-date-range="uploadCoverageStart,uploadCoverageEnd"] .date-range-trigger').disabled=state.uploading;
  renderUploadFileList();
  $('fileCount').textContent=`${state.files.length} 个文件`;
  $('fileBody').innerHTML=state.files.length ? state.files.map(item=>{
    const check=itemReadiness(item); const terminal=isSubmitted(item); const disabled=state.uploading||terminal||item.removing;
    const serverUi=fileTaskUiStatus(item); const recognition=serverUi?{...serverUi,tone:serverUi.tone==='success'?'success':serverUi.tone==='warning'?'warning':serverUi.tone==='failed'||serverUi.tone==='error'?'error':'info'}:{label:check.ready?'可提交':'待修正',tone:check.ready?'success':'pending'};
    const recognitionIcon=recognition.tone==='success'?'i-check-circle':recognition.tone==='warning'?'i-info':recognition.tone==='error'?'i-close':'i-loader';
    const errorDisclosure=renderErrorDisclosure(item),recognitionHtml=String(item.serverError||'').trim()?renderRecognitionStatus(item,recognition):`<span class="recognition-tag ${recognition.tone}" title="${esc(serverUi?.label||check.message)}"><svg><use href="#${recognitionIcon}"/></svg>${esc(recognition.label)}</span>`;
    const pending=item.serverStatus==='uploaded'&&!['ready','processing'].includes(item.runStatus);
    const submit=pending?`<button class="text-button" data-continue-file="${item.id}" ${state.uploading?'disabled':''}>继续确认</button>`:`<button class="text-button" data-submit-one="${item.id}" ${disabled||!check.ready?'disabled':''}>${terminal?'已提交':'单独提交'}</button>`;
    return `<tr class="${item.removing?'file-row-removing':''}"><td><input type="checkbox" data-file-check="${item.id}" ${state.selectedFiles.has(item.id)?'checked':''} ${disabled?'disabled':''} aria-label="选择${esc(item.file.name)}"></td><td><div class="file-name-cell" title="${esc(item.file.name)}">${esc(item.file.name)}</div></td><td>${cellSelectHtml(item,'platform',disabled)}</td><td>${cellSelectHtml(item,'company',disabled||!item.selection.platform_code)}</td><td>${cellSelectHtml(item,'shop',disabled||!item.selection.company_code)}</td><td>${cellSelectHtml(item,'report',disabled||!item.selection.platform_code)}</td><td>${recognitionHtml}</td><td><div class="row-actions">${submit}<button class="text-button danger" data-remove="${item.id}" ${state.uploading||item.removing?'disabled':''}>移除</button></div></td></tr>${errorDisclosure}`;
  }).join('') : '<tr><td colspan="8" class="empty-row">尚未选择文件</td></tr>';
  $('fileBody').querySelectorAll('[data-remove]').forEach(removeButton=>{
    const item=state.files.find(file=>file.id===removeButton.dataset.remove);if(!item)return;
    const resetButton=document.createElement('button');resetButton.type='button';resetButton.className='text-button';resetButton.dataset.reset=item.id;resetButton.textContent='重置';resetButton.disabled=state.uploading||isSubmitted(item);removeButton.before(resetButton);
  });
  $('fileBody').querySelectorAll('[data-submit-one]').forEach(button=>{
    const item=state.files.find(file=>file.id===button.dataset.submitOne);
    if(item?.selection.report_type!=='jd_settlement')return;
    const input=document.createElement('input');input.type='date';input.value=item.billDate||'';input.dataset.billDate=item.id;
    input.setAttribute('aria-label','京东文件缺少账单日期时请明确填写业务日');input.title='文件缺少账单日期时，需明确指定业务日';
    input.disabled=state.uploading||isSubmitted(item);button.closest('tr').children[5].append(input);
  });
  const eligible=state.files.filter(item=>!isSubmitted(item)); const selected=eligible.filter(item=>state.selectedFiles.has(item.id)); const invalid=selected.filter(item=>!itemReadiness(item).ready);
  const allSelected=eligible.length>0&&eligible.every(item=>state.selectedFiles.has(item.id)); $('selectAllFiles').checked=allSelected; $('selectAllFiles').indeterminate=!allSelected&&selected.length>0;
  $('selectedFileSummary').textContent=invalid.length?`已勾选 ${selected.length} 个文件，${invalid.length} 个待修正`:`已勾选 ${selected.length} 个文件`;
  $('selectedFileSummary').classList.toggle('has-selection',selected.length>0); $('submitFiles').disabled=state.uploading||!selected.length;
  updateImportCapabilities();
}
function removeFile(id) { clearFileRemovalTimer(id); state.files=state.files.filter(item=>item.id!==id); state.selectedFiles.delete(id); state.copyMessages.delete(`file:${id}`); closeCellDropdown(); renderFiles(); void deletePendingFile(id); }
function resetFileParameters(id) {
  const item=state.files.find(file=>file.id===id);
  if(!item||state.uploading||isSubmitted(item))return;
  item.selection=selectionFromMeta(null);
  item.manualCorrected=true;
  item.serverError='';
  state.selectedFiles.delete(id);
  closeCellDropdown();
  renderFiles();
  void persistPendingFile(item);
}
function uploadCoverage() {
  const start=$('uploadCoverageStart').value,end=$('uploadCoverageEnd').value;
  return start||end?{start,end,complete_export:$('uploadCompleteExport').checked}:{};
}
function saveUploadSettings(){
  const mode=$('uploadImportMode').value;
  updateImportCapabilities();
  try{localStorage.setItem('ingest_upload_coverage',JSON.stringify({mode,...uploadCoverage()}));}catch(_error){/* 表单仍可使用。 */}
}
function unsupportedReplacement(items){
  return items.filter(item=>{
    const report=state.reports.find(spec=>spec.report_type===(item.report_type||item.selection?.report_type));
    return !report?.coverage_modes?.includes('replace_range');
  });
}
function updateImportCapabilities(){
  const selected=state.files.filter(item=>state.selectedFiles.has(item.id)&&!isSubmitted(item));
  const unsupported=unsupportedReplacement(selected),option=$('uploadImportMode').querySelector('[value="replace_range"]');
  option.disabled=unsupported.length>0;
  if(unsupported.length){
    const reports=[...new Set(unsupported.map(item=>state.reports.find(spec=>spec.report_type===item.selection?.report_type)).filter(Boolean))];
    $('uploadCoverageHint').textContent=reports.some(report=>!report.coverage_modes)?'后台的报表能力信息未更新，请重启经营配置中心后再提交。':`${reports.map(report=>report.platform_name+report.report_name).join('、')||'当前报表'}暂不支持范围替换；补缺模式将沿用各报表原有的来源核对规则。`;
  }else{
    $('uploadCoverageHint').textContent=$('uploadImportMode').value==='replace_range'?'用更正后的完整报表更新所选日期；核对差异并填写原因后才会提交，原始流水保留。':'补入缺失日期，已有日期内容一致时不重复计算；发现差异时停止并提示核对。';
  }
}
async function requireReviewVersion() {
  if((await api('/api/ingest/health')).ingest_review_version!==3)throw new Error('导入流程已更新，请先重启后台服务，再继续原导入记录');
}
const coverageModeLabels={fill_gaps:'补入缺失日期',replace_range:'替换所选范围的来源',refresh_only:'使用已入库文件重新刷新'};
async function reviewUpload(runId,{autoSubmit=false,detail:providedDetail=null}={}) {
  await requireReviewVersion();
  const dialog=$('coverageDialog'),detail=providedDetail||await api(`/api/ingest/runs/${runId}`);
  const claim=detail.files.find(file=>file.coverage?.start||file.coverage?.end||file.coverage?.reason)?.coverage||detail.files[0]?.coverage||{};
  $('coverageMode').value=detail.run.import_mode||$('uploadImportMode').value;
  $('coverageStart').value=claim.start||'';$('coverageEnd').value=claim.end||'';
  $('coverageComplete').checked=Boolean(claim.complete_export);$('coverageReason').value=claim.reason||'';
  syncDateRange(document.querySelector('[data-date-range="coverageStart,coverageEnd"]'));
  $('coverageEditor').hidden=true;$('coverageEdit').textContent='调整导入设置';$('coverageEmptyHelp').hidden=true;
  $('coverageRows').innerHTML='';
  const allStored=detail.files.every(file=>['success','duplicate'].includes(file.status)&&file.batch_id);
  $('coverageMode').querySelector('[value="replace_range"]').disabled=unsupportedReplacement(detail.files).length>0;
  $('coverageMode').querySelector('[value="refresh_only"]').hidden=!allStored;
  $('coverageDescription').textContent=allStored?'文件已入库，本次复用原文件核对来源并刷新。':'文件已暂存，尚未提交入库。保存草稿后可从导入记录继续。';
  $('coverageApply').textContent=allStored?'确认来源并刷新':'确认导入并刷新';
  const emptyDays=new Map(detail.files.map(file=>[file.file_task_id,new Set(file.coverage?.confirmed_empty_days||[])]));
  let latest=null,epoch=0,timer=null,closed=false,rangeEdited=false,firstCheck=true,requestChain=Promise.resolve();
  let resolveReview;
  const completion=new Promise(resolve=>{resolveReview=resolve;});
  const notice=(message,tone='pending')=>{$('coverageSummary').textContent=message;$('coverageSummary').className=`coverage-notice ${tone}`;};
  const updateContext=()=>{
    const mode=$('coverageMode').value,start=$('coverageStart').value,end=$('coverageEnd').value;
    $('coverageContext').innerHTML=`<strong>${esc(coverageModeLabels[mode])}</strong><span>${esc(start&&end?`${start} 至 ${end}`:'按文件中有交易的日期核对')}</span>`;
    $('coverageReasonField').hidden=mode!=='replace_range';
    $('coverageReason').required=mode==='replace_range';
  };
  const payload=()=>({import_mode:$('coverageMode').value,items:detail.files.map(file=>{
    const coverage={...(file.coverage||{})};
    if(rangeEdited){coverage.start=$('coverageStart').value;coverage.end=$('coverageEnd').value;coverage.complete_export=$('coverageComplete').checked;
      if(coverage.start!==file.coverage?.start||coverage.end!==file.coverage?.end)delete coverage.artifact_id;}
    if($('coverageMode').value==='replace_range'){
      coverage.reason=$('coverageReason').value;coverage.confirmed_empty_days=[...(emptyDays.get(file.file_task_id)||[])];
    }else{delete coverage.reason;coverage.confirmed_empty_days=[];}
    return {file_task_id:file.file_task_id,coverage};
  })});
  const finish=value=>{
    closed=true;epoch++;clearTimeout(timer);closeDateRange();dialog.oncancel=null;
    if(['fill_gaps','replace_range'].includes($('coverageMode').value)){
      $('uploadImportMode').value=$('coverageMode').value;
      if(rangeEdited){$('uploadCoverageStart').value=$('coverageStart').value;$('uploadCoverageEnd').value=$('coverageEnd').value;$('uploadCompleteExport').checked=$('coverageComplete').checked;
        syncDateRange(document.querySelector('[data-date-range="uploadCoverageStart,uploadCoverageEnd"]'));}
      saveUploadSettings();
    }
    if(dialog.open)dialog.close();resolveReview(value);
  };
  const invalidate=()=>{
    epoch++;latest=null;$('coverageApply').disabled=true;
    $('coverageActionHint').textContent='设置已变化，正在重新核对';
    $('coverageEmptyHelp').hidden=true;$('coverageRows').classList.add('checking');
    notice('设置已变化，核对完成后即可继续。');updateContext();
  };
  const check=async()=>{
    if(closed)return;
    clearTimeout(timer);invalidate();const version=epoch,current=payload();
    $('coverageRecheck').disabled=true;notice('正在核对文件内容与已有来源…');
    const request=requestChain.then(()=>api(`/api/ingest/runs/${runId}/coverage-preflight`,{method:'POST',body:JSON.stringify(current)}));
    requestChain=request.catch(()=>{});
    try {
      const report=await request;if(closed||version!==epoch)return;
      latest=report;
      const labels={same:'内容一致',empty_both:'均无交易',new_only:'补齐缺口',empty_new:'本次为空',different:'内容不同'};
      notice(latest.message+' '+Object.entries(latest.summary).map(([k,v])=>`${labels[k]||k} ${v} 个店铺日期`).join('；'),latest.blocked?'warning':'success');
      $('coverageRows').innerHTML=latest.items.flatMap(item=>item.days.map(d=>{
        const needsZero=latest.mode==='replace_range'&&d.status==='empty_new';
        const zero=needsZero?`<label class="coverage-zero"><input type="checkbox" data-empty-file="${esc(item.file_task_id)}" data-empty-date="${esc(d.date)}" ${emptyDays.get(item.file_task_id)?.has(d.date)?'checked':''}><span>确认该店铺当日确无交易，以零交易替换</span></label>`:'';
        return `<tr class="${d.blocked?'coverage-blocked':''}"><td><strong>${esc(item.shop_name||item.shop_identity_key)}</strong><br><span class="muted">${esc(item.report_name||item.report_type)}</span></td><td>${esc(d.date)}</td><td><span class="coverage-result ${d.blocked?'warning':d.status==='new_only'?'new':'same'}">${esc(labels[d.status])}${d.blocked?' · 需处理':''}</span>${d.missing_accounts?.length?`<div class="error-text">缺少账户 ${esc(d.missing_accounts.join('、'))}</div>`:''}${zero}</td><td>${d.old_rows} / ${money(d.old_amount)}</td><td>${d.new_rows} / ${money(d.new_amount)}</td></tr>`;
      })).join('')||'<tr><td colspan="5">本次报表沿用现有导入规则。</td></tr>';
      $('coverageRows').classList.remove('checking');
      $('coverageEmptyHelp').hidden=!(latest.mode==='replace_range'&&latest.items.some(item=>item.days.some(d=>d.status==='empty_new')));
      $('coverageApply').disabled=latest.blocked;
      $('coverageActionHint').textContent=latest.blocked?'请先处理标记的差异或确认空日':'核对通过，可以提交';
      if(firstCheck&&autoSubmit&&latest.mode==='fill_gaps'&&!latest.blocked){finish(latest.token);return;}
    } catch(error) {
      if(closed||version!==epoch)return;
      notice(error.message,'error');$('coverageActionHint').textContent='尚未提交，请调整设置后重试';
      $('coverageRows').innerHTML='<tr><td colspan="5" class="empty-row">核对未完成，现有数据未替换。</td></tr>';
      $('coverageRows').classList.remove('checking');$('coverageEditor').hidden=false;
    } finally {
      if(!closed&&version===epoch){firstCheck=false;$('coverageRecheck').disabled=false;if(!dialog.open)dialog.showModal();}
    }
  };
  const changed=()=>{invalidate();clearTimeout(timer);timer=setTimeout(check,500);};
  for(const id of ['coverageMode','coverageComplete','coverageReason'])$(id).oninput=changed;
  $('coverageComplete').oninput=()=>{rangeEdited=true;changed();};
  const rangeControl=document.querySelector('[data-date-range="coverageStart,coverageEnd"]');
  rangeControl.onchange=()=>{rangeEdited=true;changed();if(!$('coverageEnd').value){clearTimeout(timer);notice('请选择完整的开始和结束日期。');}};
  $('coverageRows').onchange=event=>{const box=event.target.closest('[data-empty-file]');if(!box)return;
    const set=emptyDays.get(box.dataset.emptyFile)||new Set();emptyDays.set(box.dataset.emptyFile,set);
    box.checked?set.add(box.dataset.emptyDate):set.delete(box.dataset.emptyDate);changed();};
  $('coverageEdit').onclick=()=>{$('coverageEditor').hidden=!$('coverageEditor').hidden;$('coverageEdit').textContent=$('coverageEditor').hidden?'调整导入设置':'收起设置';};
  const save=async()=>{
    if(closed)return;invalidate();clearTimeout(timer);
    const buttons=['coverageCancel','coverageClose','coverageRecheck','coverageApply'];buttons.forEach(id=>$(id).disabled=true);
    try{await requestChain;await api(`/api/ingest/runs/${runId}/draft`,{method:'POST',body:JSON.stringify(payload())});finish(null);}
    catch(error){notice(`草稿未保存：${error.message}`,'error');$('coverageActionHint').textContent='请重试保存草稿';}
    finally{if(!closed){['coverageCancel','coverageClose','coverageRecheck'].forEach(id=>$(id).disabled=false);}}
  };
  $('coverageCancel').disabled=false;$('coverageClose').disabled=false;
  $('coverageCancel').onclick=save;$('coverageClose').onclick=save;
  dialog.oncancel=event=>{event.preventDefault();if(state.dateRangeContext){closeDateRange();return;}void save();};
  $('coverageRecheck').onclick=check;
  $('coverageApply').onclick=()=>{if(latest&&!latest.blocked)finish(latest.token);};
  updateContext();void check();return completion;
}
function uploadFile(runId,item) {
  return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();const form=new FormData();const meta=itemReadiness(item).meta;
    form.append('file',item.file,item.file.name);form.append('client_file_id',item.id);form.append('report_type',meta.report_type);form.append('platform_name',meta.platform_name);form.append('company_name',meta.company_name);form.append('shop_code',meta.shop_code);form.append('shop_name',meta.shop_name);if(item.manualCorrected)form.append('manual_correction','true');
    form.append('coverage',JSON.stringify({...uploadCoverage(),...(item.billDate?{bill_date:item.billDate}:{})}));
    xhr.open('POST',`/api/ingest/runs/${runId}/files`);xhr.setRequestHeader('X-Operator',encodeURIComponent('网页用户'));
    const csrfToken=window.appCsrfToken?.();if(!csrfToken){reject(new Error('CSRF令牌缺失，请刷新页面后重试'));return;}xhr.setRequestHeader('X-CSRF-Token',csrfToken);
    xhr.upload.onprogress=event=>{if(event.lengthComputable){item.uploadProgress=Math.round(event.loaded/event.total*100);renderFiles();}};
    xhr.onerror=()=>reject(new Error('网络异常，文件上传失败'));xhr.onload=()=>{let result;try{result=JSON.parse(xhr.responseText);}catch{reject(new Error(`上传接口返回异常(${xhr.status})`));return;}if(xhr.status<200||xhr.status>=300||result.code){reject(new Error(result.message||`上传失败(${xhr.status})`));return;}resolve(result.data);};xhr.send(form);
  });
}
async function submitItems(items) {
  if(state.uploading||!items.length)return; const invalid=items.filter(item=>!itemReadiness(item).ready); if(invalid.length){toast(`有 ${invalid.length} 个文件待修正，不能提交`,true);return;}
  try{await requireReviewVersion();if($('uploadImportMode').value==='replace_range'&&unsupportedReplacement(items).length)throw new Error('勾选文件中有报表不支持范围替换，请分开提交或使用原有导入规则');const coverage=uploadCoverage();if(Boolean(coverage.start)!==Boolean(coverage.end))throw new Error('请选择完整的平台查询开始和结束日期');if(coverage.start&&!coverage.complete_export)throw new Error('请确认文件为所填范围的完整导出');}catch(error){toast(error.message,true);return;}
  state.uploading=true; closeCellDropdown();closeDateRange(); renderFiles();
  let runId=null,filesUploaded=false;
  try {
    items.forEach(item=>{item.serverError='';item.serverStatus='';item.uploadProgress=0;void persistPendingFile(item);});
    const run=await api('/api/ingest/runs',{method:'POST',body:JSON.stringify({source:'manual',expected_file_count:items.length,idempotency_key:createClientId(),auto_refresh:true,import_mode:$('uploadImportMode').value})}); runId=run.run_id;state.currentRunId=runId;
    for(const item of items){item.runId=runId;item.runStatus='draft';item.uploadStatus='uploading';renderFiles();void persistPendingFile(item);const uploaded=await uploadFile(runId,item);item.fileTaskId=uploaded.file_task_id;item.serverStatus=uploaded.status;item.uploadStatus='uploaded';item.uploadProgress=100;renderFiles();void persistPendingFile(item);}
    filesUploaded=true;const token=await reviewUpload(runId,{autoSubmit:true});if(!token){toast('草稿已保存，可点击“继续确认”处理；尚未提交入库');await loadRuns();return;}
    const detail=await api(`/api/ingest/runs/${runId}/complete`,{method:'POST',body:JSON.stringify({preflight_token:token})});items.forEach(item=>state.selectedFiles.delete(item.id));applyRunDetail(detail,items);renderFiles();
    toast(detail.run.status==='no_change'?'上传成功；文件内容重复，未重复写入 ODS':'上传成功，后台正在导入 ODS');pollRun(runId,items);Promise.all([loadRuns(),loadEtls(),loadLogs()]);
  } catch(exc) {
    if(runId&&!filesUploaded){try{await api(`/api/ingest/runs/${runId}/fail`,{method:'POST',body:JSON.stringify({message:exc.message})});}catch(markError){console.warn('标记上传会话失败失败',markError);}}
    const active=items.find(item=>item.uploadStatus==='uploading');if(active){active.uploadStatus='failed';active.serverError=exc.message;void persistPendingFile(active);}toast(exc.message,true);
    if(runId)loadRuns();
  } finally { state.uploading=false; renderFiles(); }
}
async function submitFiles() { const items=state.files.filter(item=>state.selectedFiles.has(item.id)&&!isSubmitted(item));await submitItems(items); }
function fileTaskUiStatus(item) {
  if(item.syncError)return {label:'状态待同步',tone:'warning'};
  if(item.serverStatus==='success')return {label:'ODS导入成功', tone:statusTone(item.serverStatus,item.serverError,item.serverOutput)};
  if(item.serverStatus==='duplicate')return {label:'重复文件', tone:'duplicate'};
  if(item.serverStatus==='processing')return {label:'ODS处理中', tone:'processing'};
  if(item.serverStatus==='failed'||item.uploadStatus==='failed')return {label:'ODS导入失败', tone:'failed'};
  if(item.serverStatus==='uploaded')return {label:['ready','processing'].includes(item.runStatus)?'已提交，等待入库':'已暂存，待确认', tone:'uploaded'};
  return null;
}
function applyRunDetail(detail,items=state.files) {
  if(!detail?.run) return;
  const byClient=new Map((detail.files||[]).map(file=>[String(file.client_file_id),file]));
  const byTask=new Map((detail.files||[]).map(file=>[String(file.file_task_id),file]));
  items.forEach(item=>{
    const server=byClient.get(String(item.id))||byTask.get(String(item.fileTaskId))||byClient.get(String(item.fileTaskId));
    if(!server||(item.runId&&String(item.runId)!==String(detail.run.run_id)))return;
    const updated=Math.max(Date.parse(server.updated_at)||0,Date.parse(detail.run.updated_at)||0);
    if(item.serverUpdatedAt&&updated&&updated<item.serverUpdatedAt)return;
    item.serverUpdatedAt=updated;item.syncError='';item.runId=detail.run.run_id;item.runStatus=detail.run.status;item.fileTaskId=server.file_task_id;item.serverStatus=server.status;item.serverError=server.error_message||(server.status==='failed'?server.output_summary:'')||'';item.serverOutput=server.output_summary||'';
    if(server.status==='failed')item.uploadStatus='failed';else if(server.status)item.uploadStatus='uploaded';
    if(AUTO_REMOVE_FILE_STATUSES.has(server.status))scheduleSuccessfulFileRemoval(item);void persistPendingFile(item);
  });renderFiles();
}
async function pollRun(runId,items) {
  if(state.pollingRuns.has(runId))return;state.pollingRuns.add(runId);
  let failures=0;
  try {
    while(true) {
      try{
        const detail=await api(`/api/ingest/runs/${runId}`);applyRunDetail(detail);failures=0;
        if(['success','success_with_warnings','no_change','failed','partial_failed'].includes(detail.run.status)){if(detail.run.status==='success')toast(`${detail.run.success_file_count} 个文件已成功写入 ODS`);if(['failed','partial_failed'].includes(detail.run.status))toast(detail.run.error_message||'文件导入失败，请查看导入记录',true);await Promise.all([loadRuns(),loadEtls(),loadLogs()]);break;}
        if(detail.run.status==='draft')break;
      }catch(error){
        failures++;state.files.filter(item=>item.runId===runId).forEach(item=>{item.syncError=error.message;});renderFiles();
        if(failures===1)toast('状态暂未同步，后台处理继续；正在自动重连',true);
      }
      await new Promise(resolve=>setTimeout(resolve,Math.min(30000,2000*2**Math.min(failures,4))));
    }
  }
  finally { state.pollingRuns.delete(runId); }
}

function applySharedHealth(detail) {
  const ingest=detail?.data?.modules?.ingest||{};
  const worker=detail?.data?.modules?.worker||{};
  state.health={...ingest,...worker};
  $('workerAlert').hidden=Boolean(detail?.workerOk)||ingest.ingest_ready!==true;
}

async function completeRun(runId,{reviewMode=null}={}){
  if(state.uploading)return;state.uploading=true;closeDateRange();renderFiles();
  try{
    await requireReviewVersion();let detail=await api(`/api/ingest/runs/${runId}`);
    if(detail.run.can_resume)detail=await api(`/api/ingest/runs/${runId}/resume`,{method:'POST',body:'{}'});
    applyRunDetail(detail);
    if(!detail.run.can_complete){
      toast(['ready','processing'].includes(detail.run.status)?'已提交，正在等待或执行入库':'请在导入详情中查看处理阶段');
      if(['ready','processing'].includes(detail.run.status))void pollRun(runId,state.files.filter(file=>file.runId===runId));
      return;
    }
    if(reviewMode)detail.run.import_mode=reviewMode;
    const token=await reviewUpload(runId,{detail});
    if(!token){toast('草稿已保存，可随时继续确认；尚未提交入库');return;}
    detail=await api(`/api/ingest/runs/${runId}/complete`,{method:'POST',body:JSON.stringify({preflight_token:token})});
    applyRunDetail(detail);toast(detail.run.status==='ready'?'已提交入库；刷新进度可在详情查看':'导入提交已处理');
    void pollRun(runId,state.files.filter(file=>file.runId===runId));
  }catch(error){toast(error.message,true);}
  finally{state.uploading=false;renderFiles();await Promise.all([loadRuns(),loadEtls()]);}
}
async function continueUploadedFile(item){
  try{if(!item.runId){const detail=await api(`/api/ingest/file-tasks/${item.fileTaskId}/review-context`);item.runId=detail.run.run_id;applyRunDetail(detail);}
    await completeRun(item.runId);
  }catch(error){toast(error.message,true);}
}
async function recalculateRun(runId){
  if(state.recalculatingRun)return;state.recalculatingRun=runId;
  try{
    await requireReviewVersion();const detail=await api(`/api/ingest/runs/${runId}`);
    if(!detail.run.can_reuse)throw new Error('请先完成文件入库，再重新计算');
    const reused=await api(`/api/ingest/runs/${runId}/reuse`,{method:'POST',body:JSON.stringify({idempotency_key:createClientId()})});
    if($('ingestDetailDialog').open)closeDetailDialog('ingestDetailDialog');
    await completeRun(reused.run.run_id,{reviewMode:'refresh_only'});
  }catch(error){toast(error.message,true);}
  finally{state.recalculatingRun=null;}
}
async function deleteRun(runId){if(!confirm('确认删除这个未完成的导入记录及其已上传文件吗？已成功写入 ODS 的记录不能删除。'))return;try{await api(`/api/ingest/runs/${runId}`,{method:'DELETE',body:'{}'});toast('导入记录已删除');await loadRuns();}catch(e){toast(e.message,true);}}
function hasOdsBatchMetrics(batch){return ['total_rows','parsed_rows','success_rows','failed_rows','ingest_status'].some(key=>batch[key]!==null&&batch[key]!==undefined);}
function ingestFileMessage(file){const batches=file.ods_batches||[];const batchSummary=batches.map(batch=>hasOdsBatchMetrics(batch)?`${batch.target_table||'ODS'} 批次${batch.batch_id}：读取${batch.total_rows??'—'}行，成功${batch.success_rows??'—'}行，失败${batch.failed_rows??'—'}行`:`${batch.target_table||'ODS'} 批次${batch.batch_id}：ODS已写入，统计稍后可查看`).join('；');const message=file.error_message||file.output_summary||batchSummary||'暂无 Loader 输出';return `<pre class="${messageClass(statusTone(file.status,file.error_message,file.output_summary))}" title="${esc(message)}">${esc(message)}</pre>`;}
function ingestFileBatches(file){const batches=file.ods_batches||[];if(!batches.length&&file.batch_id)return `<span>批次 ${esc(file.batch_id)}</span>`;return batches.length?batches.map(batch=>`<div>${esc(batch.target_table||'ODS')} · ${esc(batch.batch_id)}${hasOdsBatchMetrics(batch)?`<br><span class="muted">读取${esc(batch.total_rows??'—')} / 成功${esc(batch.success_rows??'—')} / 失败${esc(batch.failed_rows??'—')}行</span>`:'<br><span class="muted">ODS已写入 · 统计稍后可用</span>'}</div>`).join(''):'—';}
const DETAIL_DIALOG_IDS=['ingestDetailDialog','etlDetailDialog'];
function invalidateDetailRequest(dialogId){
  if(state.activeDetailDialog!==dialogId)return;
  state.detailRequestController?.abort();
  state.detailRequestController=null;
  state.detailRequestId+=1;
  state.activeDetailDialog=null;
}
function beginDetailRequest(dialogId){
  state.detailRequestController?.abort();
  const controller=typeof AbortController==='function'?new AbortController():null;
  const request={id:++state.detailRequestId,dialogId,controller};
  state.detailRequestController=controller;
  state.activeDetailDialog=dialogId;
  DETAIL_DIALOG_IDS.forEach(id=>{if(id!==dialogId){const dialog=$(id);if(dialog?.open)dialog.close();}});
  const dialog=$(dialogId);
  if(!dialog.open)dialog.showModal();
  return request;
}
function isCurrentDetailRequest(request){
  const dialog=$(request.dialogId);
  return state.detailRequestId===request.id&&state.activeDetailDialog===request.dialogId&&state.detailRequestController===request.controller&&Boolean(dialog?.open);
}
function finishDetailRequest(request){if(state.detailRequestController===request.controller)state.detailRequestController=null;}
function closeDetailDialog(dialogId){invalidateDetailRequest(dialogId);$(dialogId)?.close();}
function detailRequestOptions(request){return request.controller?{signal:request.controller.signal}:{};}
function showDetailError(request,bodyId,colspan,message){
  if(!isCurrentDetailRequest(request))return;
  $(bodyId).innerHTML=`<tr><td colspan="${colspan}" class="empty-row error-text">详情加载失败：${esc(message)}</td></tr>`;
}
async function showRunDetail(runId){
  const request=beginDetailRequest('ingestDetailDialog');
  $('ingestDetailMeta').textContent=`${String(runId)} · 正在加载详情`;
  $('ingestDetailSummary').innerHTML='<span>正在读取会话状态…</span>';
  $('ingestFileDetailBody').innerHTML='<tr><td colspan="7" class="empty-row">正在加载详情…</td></tr>';
  try{
    const detail=await api(`/api/ingest/runs/${encodeURIComponent(runId)}`,detailRequestOptions(request));
    if(!isCurrentDetailRequest(request))return;
    applyRunDetail(detail);
    const run=detail.run,files=detail.files||[];
    const canContinue=run.can_complete||run.can_resume;
    $('recalculateIngestFiles').disabled=!run.can_reuse||['ready','processing'].includes(run.status);
    $('recalculateIngestFiles').onclick=()=>void recalculateRun(run.run_id);
    $('reuseIngestFiles').disabled=!canContinue&&!run.can_reuse;
    $('reuseIngestFiles').textContent=canContinue?'继续确认本次导入':'使用这些文件重新核对';
    $('reuseIngestFiles').onclick=async()=>{try{let nextId=run.run_id;
      if(!canContinue){const reused=await api(`/api/ingest/runs/${run.run_id}/reuse`,{method:'POST',body:JSON.stringify({idempotency_key:createClientId()})});nextId=reused.run.run_id;}
      closeDetailDialog('ingestDetailDialog');await completeRun(nextId);
    }catch(error){toast(error.message,true);}};
    const runTone=statusTone(run.status,run.error_message,run.output_summary),displayTone=runTone==='error'?'error':files.some(file=>statusTone(file.status,file.error_message,file.output_summary)==='warning')?'warning':runTone;
    $('ingestDetailMeta').textContent=`${run.run_id} · ${({api:'API',robot:'影刀',manual:'网页'})[run.source]||run.source} · ${fmt(run.created_at)}`;
    $('ingestDetailSummary').innerHTML=`<span>会话状态：${tag(run.status,displayTone)}</span><span>文件：${files.length}/${run.expected_file_count}</span><span>ODS成功：${run.success_file_count||0}</span><span>重复：${run.duplicate_file_count||0}</span><span>失败：${run.failed_file_count||0}</span>`;
    if(run.coverage_result)$('ingestDetailSummary').insertAdjacentHTML('beforeend',`<span>采信：${esc(run.coverage_result.mode)} · ${run.coverage_result.selected_days||0} 天；指标刷新请查看关联ETL状态</span>`);
    const lastEtl=(detail.etl_runs||[]).at(-1);
    const stage=canContinue?'文件已暂存，等待确认；尚未提交入库或刷新。':run.status==='ready'?'已提交，等待后台写入ODS；指标刷新将在入库和来源确认后排队。':run.status==='processing'?'正在写入ODS；来源确认和指标刷新尚未完成。':lastEtl?`入库与来源确认已完成；指标刷新：${statusLabel(lastEtl.status)}，请查看关联ETL。`:run.status==='failed'?'导入处理未完成，请查看各文件的具体状态。':'文件处理已完成，本记录没有关联的指标刷新任务。';
    $('ingestDetailSummary').insertAdjacentHTML('beforeend',`<p class="ingest-stage-notice">${esc(stage)}</p>`);
    $('ingestFileDetailBody').innerHTML=files.length?files.map(file=>{const canRetry=file.status==='failed',message=detailMessage(file),tone=statusTone(file.status,file.error_message,file.output_summary),actions=[];if(canRetry)actions.push(`<button type="button" class="text-button detail-action" data-retry-ingest-file="${esc(file.file_task_id)}" data-retry-ingest-run="${esc(run.run_id)}"><svg><use href="#i-refresh"/></svg>重试</button>`);if(message)actions.push(detailCopyMessageButton(`file-detail:${file.file_task_id}`,message,tone));return `<tr><td class="file-detail-name" title="${esc(file.source_file_name)}"><strong>${esc(file.source_file_name)}</strong><br><span class="muted">任务 ${esc(String(file.file_task_id).slice(0,8))}</span></td><td>${esc(file.report_type)}<br><span class="muted">${file.loader_exit_code===null||file.loader_exit_code===undefined?'未执行':`退出码 ${file.loader_exit_code}`}</span></td><td class="file-detail-context">${esc(file.resolved_platform_name)}<br>${esc(file.resolved_company_name)}<br>${esc(file.resolved_shop_name)}<br><span class="muted">${esc(file.resolved_shop_code)}</span></td><td>${tag(file.status,statusTone(file.status,file.error_message,file.output_summary))}<br><span class="muted">开始 ${fmt(file.started_at)}<br>结束 ${fmt(file.finished_at)}</span></td><td class="file-detail-batches">${ingestFileBatches(file)}</td><td class="file-detail-message">${ingestFileMessage(file)}</td><td><div class="row-actions">${actions.length?actions.join(''):'—'}</div></td></tr>`;}).join(''):'<tr><td colspan="7" class="empty-row">本会话没有文件任务</td></tr>';
  }catch(e){
    if(e?.name==='AbortError'||!isCurrentDetailRequest(request))return;
    showDetailError(request,'ingestFileDetailBody',7,e.message);
    toast(e.message,true);
  }finally{finishDetailRequest(request);}
}
async function retryIngestFile(fileTaskId,runId){try{await api(`/api/ingest/file-tasks/${fileTaskId}/retry`,{method:'POST',body:'{}'});toast('文件已重新排队，正在提交会话');await completeRun(runId);await showRunDetail(runId);await loadRuns();}catch(e){toast(e.message,true);}}
function runQuery(){const params=new URLSearchParams({page:String(state.runPage),page_size:String(state.runPageSize),date_field:state.runFilters.date_field||$('runDateField')?.value||'created_at'});const operators=state.runFilters.operator||[];if(operators.length)params.set('operator',operators.join(','));if(state.runFilters.status?.length)params.set('status',state.runFilters.status[0]);const dateFrom=$('runDateFrom')?.value||'',dateTo=$('runDateTo')?.value||'';if(dateFrom)params.set('date_from',dateFrom);if(dateTo)params.set('date_to',dateTo);const keyword=($('runKeyword')?.value||'').trim();if(keyword)params.set('keyword',keyword);return params;}
function renderRunRow(r){
  const progress=Number(r.task_file_count??(r.success_file_count+r.duplicate_file_count+r.failed_file_count));
  const actions=[`<button class="text-button" data-run-detail="${esc(r.run_id)}">查看详情</button>`];
  if(r.can_complete||r.can_resume)actions.push(`<button class="text-button" data-complete-run="${esc(r.run_id)}">继续确认</button>`);
  if(r.can_reuse&&!['ready','processing'].includes(r.status))actions.push(`<button class="text-button" data-recalculate-run="${esc(r.run_id)}">重新计算</button>`);
  if(r.can_delete)actions.push(`<button class="text-button danger" data-delete-run="${esc(r.run_id)}">删除</button>`);
  const labels={draft:'待确认',ready:'等待入库',processing:'入库处理中',success:'入库完成'};
  const label=r.can_resume?'失败（可继续确认）':labels[r.status]||statusLabel(r.status);
  const tone=r.can_resume?'warning':statusTone(r.status,r.error_message,`${r.output_summary||''}${r.has_warning?'\nwarning':''}`);
  return `<tr class="clickable-row" data-run-id="${esc(r.run_id)}"><td title="${esc(r.run_id)}">${esc(String(r.run_id).slice(0,8))}</td><td>${({api:'API',robot:'影刀',manual:'网页'})[r.source]||r.source}</td><td title="已收到的文件数；不等于ODS成功数">${progress}/${r.expected_file_count}</td><td><span class="status-tag ${esc(r.status)} tone-${esc(tone)}">${esc(label)}</span></td><td>${esc(r.operator||'—')}</td><td>${fmt(r.created_at)}</td><td>${fmt(r.completed_at)}</td><td><div class="row-actions">${actions.join('')}</div></td></tr>`;
}
async function loadRuns(){
  try{const data=await api(`/api/ingest/runs?${runQuery()}`);state.runOperatorOptions=Array.isArray(data.operators)?data.operators:[];
    renderPickerLabel('run_operator','runOperator','runOperatorLabel');
    $('runBody').innerHTML=data.items.length?data.items.map(renderRunRow).join(''):'<tr><td colspan="8" class="empty-row">暂无导入记录；上传文件后会自动出现在这里</td></tr>';
    renderRunPagination(data.pagination);$('runTotal').textContent=`共 ${data.pagination.total} 条`;
  }catch(error){$('runBody').innerHTML=`<tr><td colspan="8" class="empty-row error-text">加载失败：${esc(error.message)}</td></tr>`;}
}
function renderRunPagination(pagination){const total=Number(pagination.total||0),size=Number(pagination.page_size||state.runPageSize),current=Number(pagination.page||1),pages=Math.max(1,Math.ceil(total/size));renderPagination('runPageNumbers','runPrevPage','runNextPage','runPageInfo','runPageSize',current,pages,total,page=>{state.runPage=page;loadRuns()});}
const etlTriggerLabel=value=>({manual:'人工创建',ingest_complete:'导入完成',nightly:'夜间全量',bank_submit:'银行提交',fee_mapping:'费用映射'}[value]||value);
const etlScopeLabel=value=>({all:'全量',affected:'受影响范围',selected:'指定节点'}[value]||value);
function etlQuery(){const params=new URLSearchParams({page:String(state.etlPage),page_size:String(state.etlPageSize),date_field:state.etlFilters.date_field||$('etlDateField')?.value||'started_at'});const operators=state.etlFilters.operator||[];if(operators.length)params.set('operator',operators.join(','));if(state.etlFilters.status?.length)params.set('status',state.etlFilters.status[0]);const dateFrom=$('etlDateFrom')?.value||'',dateTo=$('etlDateTo')?.value||'';if(dateFrom)params.set('date_from',dateFrom);if(dateTo)params.set('date_to',dateTo);const keyword=($('etlKeyword')?.value||'').trim();if(keyword)params.set('keyword',keyword);return params;}
async function loadEtls(){try{const data=await api(`/api/etl/runs?${etlQuery()}`);state.etlOperatorOptions=Array.isArray(data.operators)?data.operators:[];renderPickerLabel('etl_operator','etlOperator','etlOperatorLabel');$('etlBody').innerHTML=data.items.length?data.items.map(r=>{const actions=[`<button class="text-button" data-etl-detail="${esc(r.etl_run_id)}">查看详情</button>`];return `<tr><td title="${esc(r.etl_run_id)}">${esc(String(r.etl_run_id).slice(0,8))}</td><td>${esc(etlTriggerLabel(r.trigger_type))}</td><td>${esc(etlScopeLabel(r.scope))}</td><td>${tag(r.status,statusTone(r.status,r.error_message,`${r.output_summary||''}${r.has_warning?'\nwarning':''}`))}</td><td class="wrap" title="${esc((r.requested_etls||[]).join('、'))}">${esc((r.requested_etls||[]).join('、'))}</td><td>${fmt(r.started_at)}</td><td>${fmt(r.completed_at)}</td><td><div class="row-actions">${actions.join('')}</div></td></tr>`}).join(''):'<tr><td colspan="8" class="empty-row">暂无ETL任务</td></tr>';renderEtlPagination(data.pagination);$('etlTotal').textContent=`共 ${data.pagination.total} 条`;}catch(e){toast(e.message,true);}}
function renderEtlPagination(pagination){const total=Number(pagination.total||0),size=Number(pagination.page_size||state.etlPageSize),current=Number(pagination.page||1),pages=Math.max(1,Math.ceil(total/size));renderPagination('etlPageNumbers','etlPrevPage','etlNextPage','etlPageInfo','etlPageSize',current,pages,total,page=>{state.etlPage=page;loadEtls()});}
function taskDuration(task){
  if(task.status==='running')return '执行中';
  if(!['success','failed'].includes(task.status)||!task.started_at||!task.finished_at)return '—';
  const seconds=Math.max(0,(new Date(task.finished_at)-new Date(task.started_at))/1000);
  return `${seconds.toFixed(1)} 秒`;
}
function taskMessage(task){const message=task.error_message||task.output_summary||'暂无输出';return `<pre class="${messageClass(statusTone(task.status,task.error_message,task.output_summary))}">${esc(message)}</pre>`;}
async function showEtlDetail(runId){
  const request=beginDetailRequest('etlDetailDialog');
  $('etlDetailMeta').textContent=`${String(runId)} · 正在加载详情`;
  $('etlDetailSummary').className='etl-detail-summary';$('etlDetailSummary').innerHTML='<span>正在读取ETL运行状态…</span>';
  $('etlTaskBody').innerHTML='<tr><td colspan="6" class="empty-row">正在加载详情…</td></tr>';
  try{
    const detail=await api(`/api/etl/runs/${encodeURIComponent(runId)}`,detailRequestOptions(request));
    if(!isCurrentDetailRequest(request))return;
    state.currentEtlDetail=detail;
    const tasks=detail.tasks||[],counts=tasks.reduce((result,task)=>{result[task.status]=(result[task.status]||0)+1;return result;},{}),runTone=statusTone(detail.run.status,detail.run.error_message,detail.run.output_summary),displayTone=runTone==='error'?'error':tasks.some(task=>statusTone(task.status,task.error_message,task.output_summary)==='warning')?'warning':runTone;
    $('etlDetailMeta').textContent=`${detail.run.etl_run_id} · ${etlTriggerLabel(detail.run.trigger_type)} · ${etlScopeLabel(detail.run.scope)}`;
    if(detail.run.refresh_context)$('etlDetailMeta').textContent+=` · 来源批次上限 ${detail.run.refresh_context.batch_cutoff??'人工全量'} · 采信版本 ${detail.run.refresh_context.source_selection_cutoff??'历史规则'}`;
    const scope=detail.run.refresh_context;
    if(scope?.mode==='incremental'){
      const ranges=Object.entries(scope.months||{}).map(([platform,months])=>`${platform} ${(months||[]).map(m=>m.slice(0,7)).join('、')}（${(scope.shops?.[platform]||[]).length}家店铺）`).join('；');
      $('etlDetailMeta').textContent+=` · 重跑范围：${ranges}；仅原店铺和原月份，不会扩展到新月份`;
      if(scope.snapshot_policy==='replay')$('etlDetailMeta').textContent+=' · 已确认写回的原快照重放';
    }
    if(detail.snapshot_diagnostics?.current_batch_cutoff!==undefined)$('etlDetailMeta').textContent+=` · 当前全库批次上限 ${detail.snapshot_diagnostics.current_batch_cutoff}（是否相关见提示）`;
    if(detail.run.parent_etl_run_id)$('etlDetailMeta').textContent+=` · 重试自 ${detail.run.parent_etl_run_id}`;
    $('etlDetailSummary').className='etl-detail-summary';$('etlDetailSummary').innerHTML=`<span>运行状态：${tag(detail.run.status,displayTone)}</span><span>成功：${counts.success||0}</span><span>失败：${counts.failed||0}</span><span>跳过：${counts.skipped||0}</span><span>延后：${counts.deferred||0}</span><span>排队/执行：${(counts.queued||0)+(counts.running||0)}</span>`;
    if(detail.snapshot_diagnostics?.message)$('etlDetailSummary').insertAdjacentHTML('beforeend',`<span>${esc(detail.snapshot_diagnostics.message)}</span>`);
    $('etlTaskBody').innerHTML=tasks.length?tasks.map(task=>{const canRetry=['failed','skipped','deferred'].includes(task.status),message=detailMessage(task),tone=statusTone(task.status,task.error_message,task.output_summary),actions=[];if(canRetry)actions.push(`<button type="button" class="text-button detail-action" data-retry-etl-task="${esc(task.etl_task_id)}"><svg><use href="#i-refresh"/></svg>使用最新数据重跑</button>`);if(message)actions.push(detailCopyMessageButton(`etl-task:${task.etl_task_id}`,message,tone));return `<tr><td>${task.sequence_no}</td><td><strong>${esc(task.etl_label)}</strong><br><span class="muted">${esc(task.etl_key)}</span></td><td>${tag(task.status,tone)}</td><td class="duration">${taskDuration(task)}</td><td class="task-message">${taskMessage(task)}</td><td><div class="row-actions">${actions.length?actions.join(''):'—'}</div></td></tr>`;}).join(''):'<tr><td colspan="6" class="empty-row">本次运行没有ETL节点</td></tr>';
  }catch(e){
    if(e?.name==='AbortError'||!isCurrentDetailRequest(request))return;
    showDetailError(request,'etlTaskBody',6,e.message);
    toast(e.message,true);
  }finally{finishDetailRequest(request);}
}
async function retryEtlTask(taskId){try{const result=await api(`/api/etl/tasks/${taskId}/retry`,{method:'POST',body:JSON.stringify({snapshot_policy:'latest'})});toast(result.message||'已按最新来源创建关联重试运行');closeDetailDialog('etlDetailDialog');await loadEtls();if(result.etl_run_id)await showEtlDetail(result.etl_run_id);}catch(e){toast(e.message,true);}}
function placeFloating(drop,trigger,preferredWidth){if(!drop||!trigger||drop.hidden)return;const rect=trigger.getBoundingClientRect(),width=Math.min(preferredWidth,window.innerWidth-16),height=drop.offsetHeight||360;drop.style.width=`${width}px`;drop.style.left=`${Math.max(8,Math.min(rect.left,window.innerWidth-width-8))}px`;drop.style.top=`${rect.bottom+6+height<=window.innerHeight-8?rect.bottom+6:Math.max(8,rect.top-height-6)}px`;}
const pad2=value=>String(value).padStart(2,'0');
const localDate=value=>{if(!value)return null;const [year,month,day]=value.split('-').map(Number);return new Date(year,month-1,day)};
const dateKey=value=>`${value.getFullYear()}-${pad2(value.getMonth()+1)}-${pad2(value.getDate())}`;
const monthShift=(value,offset)=>new Date(value.getFullYear(),value.getMonth()+offset,1);
function syncDateRange(control){const [startId,endId]=control.dataset.dateRange.split(','),start=$(startId),end=$(endId);if(!start||!end)return;const startText=control.querySelector('.date-start'),endText=control.querySelector('.date-end');startText.textContent=start.value||'开始日期';endText.textContent=end.value||'结束日期';startText.classList.toggle('empty',!start.value);endText.classList.toggle('empty',!end.value);}
function calendarPanel(month,index){const year=month.getFullYear(),monthIndex=month.getMonth(),first=new Date(year,monthIndex,1),gridStart=new Date(year,monthIndex,1-first.getDay()),context=state.dateRangeContext,start=context.start.value,end=context.end.value,days=[];for(let i=0;i<42;i++){const value=new Date(gridStart);value.setDate(gridStart.getDate()+i);const key=dateKey(value),classes=['calendar-day'];if(value.getMonth()!==monthIndex)classes.push('outside');if(start&&end&&key>start&&key<end)classes.push('in-range');if(key===start)classes.push('range-start');if(key===end)classes.push('range-end');days.push(`<button type="button" class="${classes.join(' ')}" data-calendar-date="${key}" ${context.maxDate&&key>context.maxDate?'disabled':''}><span>${value.getDate()}</span></button>`);}return `<section class="calendar-panel"><div class="calendar-head"><button type="button" class="calendar-nav" data-month-step="-1" ${index?'style="visibility:hidden"':''}>‹</button><strong>${year}年 ${monthIndex+1}月</strong><button type="button" class="calendar-nav next" data-month-step="1" ${!index?'style="visibility:hidden"':''}>›</button></div><div class="calendar-week"><span>日</span><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span></div><div class="calendar-days">${days.join('')}</div></section>`;}
function renderDateRange(){const context=state.dateRangeContext;if(!context)return;const drop=$('dateRangeDropdown'),right=monthShift(context.viewMonth,1);drop.innerHTML=`<div class="date-picker-shortcuts"><button type="button" class="date-shortcut" data-date-days="7">近7天</button><button type="button" class="date-shortcut" data-date-days="30">近30天</button><button type="button" class="date-shortcut" data-date-days="90">近90天</button></div><div class="date-picker-main">${calendarPanel(context.viewMonth,0)}${calendarPanel(right,1)}</div><div class="date-picker-tip">${context.pickingEnd?'请选择结束日期':'请选择开始日期'}</div>`;drop.querySelectorAll('[data-month-step]').forEach(button=>button.onclick=()=>{context.viewMonth=monthShift(context.viewMonth,Number(button.dataset.monthStep));renderDateRange();placeFloating(drop,context.trigger,640);});drop.querySelectorAll('[data-calendar-date]').forEach(button=>button.onclick=()=>selectCalendarDate(button.dataset.calendarDate));drop.querySelectorAll('[data-date-days]').forEach(button=>button.onclick=()=>applyDateShortcut(Number(button.dataset.dateDays)));}
function notifyDateRange(context){syncDateRange(context.control);context.control.dispatchEvent(new Event('change',{bubbles:true}));}
function selectCalendarDate(value){
  const context=state.dateRangeContext;if(!context||(context.maxDate&&value>context.maxDate))return;
  if(!context.pickingEnd){context.start.value=value;context.end.value='';context.pickingEnd=true;notifyDateRange(context);renderDateRange();placeFloating($('dateRangeDropdown'),context.trigger,640);return;}
  if(value<context.start.value){context.end.value=context.start.value;context.start.value=value;}else context.end.value=value;
  notifyDateRange(context);closeDateRange();
}
function applyDateShortcut(days){
  const context=state.dateRangeContext;if(!context)return;
  const end=context.maxDate?localDate(context.maxDate):new Date(),start=new Date(end);
  start.setDate(start.getDate()-(context.maxDate?days-1:days));
  context.start.value=dateKey(start);context.end.value=dateKey(end);notifyDateRange(context);closeDateRange();
}
function openDateRange(control){
  if(state.dateRangeContext?.control===control){closeDateRange();return;}closeAssignDropdown();closeDateRange();hideTablePopover();
  const [startId,endId]=control.dataset.dateRange.split(','),start=$(startId),end=$(endId),trigger=control.querySelector('.date-range-trigger');
  const yesterday=new Date();yesterday.setDate(yesterday.getDate()-1);
  const maxDate=control.dataset.maxDate==='yesterday'?dateKey(yesterday):null,base=localDate(start.value)||localDate(maxDate)||new Date();
  const drop=$('dateRangeDropdown'),host=control.closest('dialog[open]');
  state.dateRangeContext={control,trigger,start,end,maxDate,viewMonth:new Date(base.getFullYear(),base.getMonth(),1),pickingEnd:false,originalParent:drop.parentNode};
  if(host)host.appendChild(drop); // Native modal dialogs make body-level popovers inert.
  trigger?.setAttribute('aria-expanded','true');control.classList.add('open');drop.hidden=false;renderDateRange();placeFloating(drop,trigger,640);
}
function closeDateRange(){
  const context=state.dateRangeContext;if(!context)return;context.control.classList.remove('open');context.trigger?.setAttribute('aria-expanded','false');
  const drop=$('dateRangeDropdown');drop.hidden=true;if(context.originalParent&&drop.parentNode!==context.originalParent)context.originalParent.appendChild(drop);state.dateRangeContext=null;
}
function clearDateRange(startId,endId){$(startId).value='';$(endId).value='';const control=document.querySelector(`[data-date-range="${startId},${endId}"]`);if(control)syncDateRange(control);}
function logQuery(){const params=new URLSearchParams({page:state.logPage,page_size:state.logPageSize});[['date_from','logDateFrom'],['date_to','logDateTo'],['operation_type','logType'],['keyword','logKeyword']].forEach(([key,id])=>{const value=$(id)?.value?.trim();if(value)params.set(key,value);});const operators=financeFilterValues('log_operator');if(operators.length)params.set('operator',operators.join(','));return params;}
const operationTypeLabels={run_create:'创建采集会话',file_upload:'文件上传',parameter_correction:'参数修正',run_complete:'提交采集会话',run_failed:'上传会话失败',run_delete:'删除未完成采集会话',file_retry:'重试文件任务',run_timeout:'上传会话超时',etl_retry:'重试ETL任务',etl_interrupted:'ETL中断收尾',etl_schedule_update:'更新夜间全量刷新配置',finance_config_save:'保存经营预算配置',finance_config_delete:'删除经营预算配置',fee_category_create:'新增平台费用一级分类',fee_category_update:'修改平台费用一级分类',fee_category_delete:'删除平台费用一级分类',fee_mapping_assign:'批量映射费用场景',fee_mapping_status:'启停费用映射',fee_mapping_delete:'删除费用映射'};
operationTypeLabels.run_resume='继续确认导入';operationTypeLabels.run_draft_save='保存导入草稿';
function renderLogFilterOptions(data){const typeSelect=$('logType');if(!typeSelect)return;const selectedType=typeSelect.value,types=(Array.isArray(data.operation_types)?data.operation_types:[]).map(item=>typeof item==='string'?{value:item,label:operationTypeLabels[item]||item}:item).filter(item=>item?.value);typeSelect.innerHTML='<option value="">全部操作类型</option>'+types.map(item=>`<option value="${esc(item.value)}">${esc(item.label||item.value)}</option>`).join('');typeSelect.value=types.some(item=>item.value===selectedType)?selectedType:'';state.logOperatorOptions=(Array.isArray(data.operators)?data.operators:[]).filter(Boolean);state.logOperatorSelections=financeFilterValues('log_operator').filter(value=>state.logOperatorOptions.includes(value));renderPickerLabel('log_operator','logOperator','logOperatorLabel');}
async function loadLogs(){try{const data=await api(`/api/ingest/operation-logs?${logQuery()}`);renderLogFilterOptions(data);$('logBody').innerHTML=data.items.length?data.items.map(r=>`<tr><td>${fmt(r.created_at)}</td><td>${esc(operationTypeLabels[r.operation_type]||r.operation_type)}</td><td>${esc(r.operator)}</td><td>${esc(r.target_type)} ${esc(r.target_key||'')}</td><td class="wrap">${esc(r.description)}</td><td>${esc(r.ip_address||'—')}</td></tr>`).join(''):'<tr><td colspan="6" class="empty-row">暂无操作日志</td></tr>';renderLogPagination(data.pagination);$('logTotal').textContent=`共 ${data.pagination.total} 条`;}catch(e){toast(e.message,true);}}
function renderLogPagination(pagination){const total=Number(pagination.total||0),size=Number(pagination.page_size||state.logPageSize),current=Number(pagination.page||1),pages=Math.max(1,Math.ceil(total/size));renderPagination('logPageNumbers','logPrevPage','logNextPage','logPageInfo','logPageSize',current,pages,total,page=>{state.logPage=page;loadLogs()});}

const operatingLabel=value=>({income:'收入',expense:'支出',excluded:'不计入',pending:'归属待确认'}[value]||'归属待确认');
function feeQuery(){const p=new URLSearchParams({page:state.feePage,page_size:state.feePageSize});[['platform_code','feePlatform'],['source_document_type','feeDocument'],['mapping_status','feeStatus'],['operating_treatment','feeTreatment'],['keyword','feeKeyword']].forEach(([key,id])=>{if($(id).value)p.set(key,$(id).value)});return p;}
let feePolicyRefreshTimer=null;
let feeRequest=0,feeRequestController=null;
let sceneRules=[],sceneRuleEditing=null,sceneRuleProof=null;
function sceneRulePayload(){return {
  ...(sceneRuleEditing?{rule_id:sceneRuleEditing.rule_id,updated_at:sceneRuleEditing.updated_at}:{}),
  rule_name:$('sceneRuleName').value,platform_code:$('sceneRulePlatform').value,source_document_type:$('sceneRuleDocument').value,
  source_business_type:$('sceneRuleBusiness').value,pattern:$('sceneRulePattern').value,replacement:$('sceneRuleReplacement').value,
  priority:Number($('sceneRulePriority').value),is_active:$('sceneRuleActive').value==='true',note:$('sceneRuleNote').value,sample_text:$('sceneRuleSamples').value
};}
async function loadSceneRules(){try{const data=await api('/api/ingest/fee-mappings/scene-rules');sceneRules=data.items;
  const selected=$('sceneRuleFilterPlatform').value,platforms=new Map(state.reports.map(r=>[r.platform_code,r.platform_name]));
  $('sceneRuleFilterPlatform').innerHTML='<option value="">全部平台</option>'+[...platforms].map(([code,name])=>`<option value="${esc(code)}">${esc(name)}</option>`).join('');
  $('sceneRuleFilterPlatform').value=selected;renderSceneRules();
}catch(e){toast(e.message,true);}}
function renderSceneRules(){const platforms=new Map(state.reports.map(r=>[r.platform_code,r.platform_name]));
  const platform=$('sceneRuleFilterPlatform').value,documentType=$('sceneRuleFilterDocument').value,active=$('sceneRuleFilterActive').value,keyword=$('sceneRuleKeyword').value.trim().toLowerCase();
  const rows=sceneRules.map((r,i)=>({r,i})).filter(({r})=>(!platform||r.platform_code===platform)&&(!documentType||r.source_document_type===documentType)&&(!active||String(r.is_active)===active)&&(!keyword||[r.rule_name,r.source_business_type,r.pattern,r.note].join(' ').toLowerCase().includes(keyword)));
  $('sceneRuleRows').innerHTML=rows.map(({r,i})=>`<tr><td>${esc(platforms.get(r.platform_code)||r.platform_code)} / ${r.source_document_type==='fund'?'资金':'结算'}</td><td class="wrap">${esc(r.rule_name)}</td><td>${esc(r.source_business_type||'全部业务类型')}</td><td class="wrap"><code>${esc(r.pattern)}</code></td><td class="wrap">${esc(r.replacement||'（删除）')}</td><td>${r.priority}</td><td>${tag(r.is_active?'active':'inactive')}</td><td>${esc(({queued:'等待重算',deferred:'等待重算',running:'重算中',success:'已生效',failed:'重算失败',cancelled:'重算失败'})[r.configuration_etl_status]||'—')}</td><td>${fmt(r.updated_at)}</td><td><button type="button" class="text-button" data-permission="platform_fee.mappings.manage" data-edit-scene-rule="${i}">编辑</button></td></tr>`).join('')||'<tr><td colspan="10" class="empty-row">当前筛选条件下没有清洗规则</td></tr>';
  $('sceneRuleTotal').textContent=`共 ${rows.length} 条规则`;
}
function editSceneRule(rule=null){sceneRuleEditing=rule;sceneRuleProof=null;
  const platforms=new Map(state.reports.map(r=>[r.platform_code,r.platform_name]));
  $('sceneRulePlatform').innerHTML=[...platforms].map(([code,name])=>`<option value="${esc(code)}">${esc(name)}</option>`).join('');
  $('sceneRulePlatform').value=rule?.platform_code||$('sceneRuleFilterPlatform').value||$('feePlatform').value||platforms.keys().next().value;
  $('sceneRuleDocument').value=rule?.source_document_type||'fund';$('sceneRuleName').value=rule?.rule_name||'';
  $('sceneRuleBusiness').value=rule?.source_business_type||'';$('sceneRulePattern').value=rule?.pattern||'';
  $('sceneRuleReplacement').value=rule?.replacement||'';$('sceneRulePriority').value=rule?.priority??100;
  $('sceneRuleActive').value=String(rule?.is_active??true);$('sceneRuleNote').value=rule?.note||'';$('sceneRuleSamples').value='';
  $('sceneRuleTitle').textContent=rule?'编辑场景清洗规则':'新增场景清洗规则';$('sceneRulePreview').hidden=true;$('saveSceneRule').disabled=true;$('sceneRuleEditor').showModal();
}
async function previewSceneRule(){if(!$('sceneRuleForm').reportValidity())return;const button=$('previewSceneRule');try{button.disabled=true;sceneRuleProof=null;$('saveSceneRule').disabled=true;
  const payload=sceneRulePayload(),proof=await api('/api/ingest/fee-mappings/scene-rules/preview',{method:'POST',body:JSON.stringify(payload)});
  $('sceneRulePreviewSummary').textContent=`当前来源 ${proof.source_names_before} 个名称，清洗后 ${proof.source_names_after} 个；本次变化 ${proof.changed_names} 个样本。${proof.scope_note}`;
  $('sceneRuleConflicts').textContent=proof.conflicts.length?`存在 ${proof.conflicts.length} 组配置冲突，不能保存：${proof.conflicts.map(r=>r.scene).join('；')}`:'';
  $('sceneRuleExamples').innerHTML=proof.examples.map(r=>`<tr><td class="wrap">${esc(r.before)}</td><td class="wrap">${esc(r.after)}</td></tr>`).join('')||'<tr><td colspan="2">当前样本未发生变化；可以补充未来新增类型测试。</td></tr>';
  $('sceneRulePreview').hidden=false;if(proof.can_save){sceneRuleProof={payload,token:proof.preview_token};$('saveSceneRule').disabled=false;}
}catch(e){toast(e.message,true);}finally{button.disabled=false;}}
async function saveSceneRule(event){event.preventDefault();if(!sceneRuleProof){toast('请先预览匹配结果',true);return;}const button=$('saveSceneRule');try{button.disabled=true;const result=await api('/api/ingest/fee-mappings/scene-rules',{method:'POST',body:JSON.stringify({...sceneRuleProof.payload,preview_token:sceneRuleProof.token})});$('sceneRuleEditor').close();await loadSceneRules();await loadFees();toast('场景规则已保存，历史数据等待重算');}catch(e){toast(e.message,true);}finally{button.disabled=!sceneRuleProof;}}
async function loadFees(){
  clearTimeout(feePolicyRefreshTimer);
  const request=++feeRequest;
  feeRequestController?.abort();feeRequestController=new AbortController();
  $('feeMappingTable').setAttribute('aria-busy','true');
  $('feeTotal').textContent='正在加载…';
  try{
    const data=await api(`/api/ingest/fee-mappings?${feeQuery()}`,{signal:feeRequestController.signal});
    if(request!==feeRequest)return;
    state.feeItems=data.items;state.selectedFees.clear();renderFees();renderFeePagination(data.pagination);
    $('feeTotal').textContent=`共 ${data.pagination.total} 条 · 未映射 ${data.pagination.unmapped_total} 条`;
    if(state.feeItems.some(r=>['queued','running','deferred'].includes(r.configuration_etl_status)))feePolicyRefreshTimer=setTimeout(()=>{if(state.currentPage==='feeMappings'&&!state.selectedFees.size&&!$('feeMappingDialog').open&&!$('operatingPreviewDialog').open)loadFees();},3000);
  }catch(e){if(request===feeRequest&&e.name!=='AbortError'){$('feeTotal').textContent='加载失败';toast(e.message,true);}}
  finally{if(request===feeRequest)$('feeMappingTable').removeAttribute('aria-busy');}
}
function renderFeePagination(pagination){const total=Number(pagination.total||0),size=Number(pagination.page_size||state.feePageSize),current=Number(pagination.page||1),pages=Math.max(1,Math.ceil(total/size));renderPagination('feePageNumbers','feePrevPage','feeNextPage','feePageInfo','feePageSize',current,pages,total,page=>{state.feePage=page;loadFees()});}
function renderFees(){
  const table=$('feeMappingTable');table?.classList.toggle('batch-selection-mode',state.feeBatchMode);
  $('feeBody').innerHTML=state.feeItems.length?state.feeItems.map((r,i)=>{
    const categoryName=r.primary_category_name||'',categoryCode=r.primary_category_code||'';
    return `<tr data-fee-index="${i}" class="${state.selectedFees.has(i)?'is-selected':''}">
      <td><input type="checkbox" data-fee-index="${i}" aria-label="选择费用场景" ${state.selectedFees.has(i)?'checked':''}></td>
      <td>${esc(r.platform_name)}</td><td>${r.source_document_type==='fund'?'资金':'结算'}</td>
      <td class="wrap fee-scene-cell"><strong>${esc(r.secondary_category_name)}</strong></td>
      <td><div class="assign-combobox"><button type="button" class="assign-trigger" data-assign-trigger="${i}" data-value="${esc(categoryCode)}" data-name="${esc(categoryName)}"><span class="assign-value ${categoryName?'':'empty'}">${esc(categoryName||'待分配')}</span><svg><use href="#i-down"/></svg></button></div></td>
      <td><div class="assign-combobox"><button type="button" class="assign-trigger" data-assign-trigger="${i}" data-assign-kind="treatment" data-value="${esc(r.operating_treatment||'')}" aria-label="修改经营收支归属" aria-haspopup="listbox" aria-expanded="false"><span class="assign-value ${r.operating_treatment?'':'empty'}">${esc(operatingLabel(r.operating_treatment))}</span><svg><use href="#i-down"/></svg></button></div></td>
      <td class="fee-status-cell">${tag(r.mapping_status)}${r.last_etl_run_id?`<br><button class="text-button" data-policy-etl="${esc(r.last_etl_run_id)}">${esc(r.configuration_status_label)}</button>`:''}</td>
      <td><div class="row-actions">${r.mapping_id?`<button class="text-button" data-source-fee="${i}">来源依据</button>`:''}<button class="icon-action" data-edit-fee="${i}" title="编辑"><svg><use href="#i-edit"/></svg><span>编辑</span></button>${r.mapping_id?`<button class="icon-action ${r.is_active?'warning':'primary'}" data-toggle-map="${i}" title="${r.is_active?'停用分类':'启用分类'}"><svg><use href="#i-power"/></svg><span>${r.is_active?'停用分类':'启用分类'}</span></button><button class="icon-action danger" data-delete-fee="${i}" title="清除分类"><svg><use href="#i-trash"/></svg><span>清除分类</span></button>`:''}</div></td></tr>`;
  }).join(''):`<tr><td colspan="${state.feeBatchMode?'8':'7'}" class="empty-row">当前筛选条件下没有收支场景</td></tr>`;
  updateSelection();
}
function updateSelection(){const n=state.selectedFees.size,table=$('feeMappingTable'),selectAll=$('selectAllFees'),batchButton=$('batchMapFees');table?.classList.toggle('batch-selection-mode',state.feeBatchMode);if(selectAll){selectAll.checked=state.feeItems.length>0&&n===state.feeItems.length;selectAll.indeterminate=n>0&&n<state.feeItems.length;}if(batchButton){batchButton.classList.toggle('batch-mode-active',state.feeBatchMode);batchButton.querySelector('use')?.setAttribute('href',state.feeBatchMode?'#i-x-square':'#i-check-square');}if($('batchMapFeesLabel'))$('batchMapFeesLabel').textContent=state.feeBatchMode?`关闭批量勾选${n?` (${n})`:''}`:'开启批量勾选';}
function toggleFeeBatchMode(){state.feeBatchMode=!state.feeBatchMode;state.selectedFees.clear();closeAssignDropdown();hideTablePopover();renderFees();}
let feeCategoriesRequest=null;
function loadCategories(){
  if(feeCategoriesRequest)return feeCategoriesRequest;
  feeCategoriesRequest=api('/api/ingest/fee-categories?status=active').then(data=>{
    state.feeCategoryOptions=Array.isArray(data?.items)?data.items:[];
    return state.feeCategoryOptions;
  }).catch(e=>{toast(e.message,true);return state.feeCategoryOptions;}).finally(()=>{feeCategoriesRequest=null;});
  return feeCategoriesRequest;
}
async function deleteFeeMapping(index){const item=state.feeItems[index];if(!item.mapping_id)return;if(!confirm(`清除「${item.secondary_category_name}」的分类？经营归属和金额将保留。`))return;try{await api(`/api/ingest/fee-mappings/${item.mapping_id}`,{method:'DELETE'});toast('分类已清除，经营归属保留');loadFees();}catch(e){toast(e.message,true)}}
function openFeeMappingDialog(index){const item=state.feeItems[index];if(!item)return;closeAssignDropdown();const categoryName=item.primary_category_name||'';const categoryCode=item.primary_category_code||'';$('feeMappingDialogTitle').textContent='编辑经营收支配置';$('feeMappingFeeName').value=item.secondary_category_name||'';$('feeMappingBizType').value=item.source_business_type||'';$('feeMappingCategory').value=categoryName;$('feeMappingCategoryCode').value=categoryCode;$('feeMappingCategoryValue').textContent=categoryName||'选择一级分类';$('feeMappingCategoryValue').classList.toggle('empty',!categoryName);$('feeMappingCategoryTrigger').dataset.value=categoryCode;$('feeMappingCategoryTrigger').dataset.name=categoryName;$('feeMappingMatchType').value=item.source_description_match_type||'';$('feeMappingMatchValue').value=item.source_description_match_value||'';$('feeMappingPriority').value=item.mapping_priority??'';$('feeMappingInclude').value=item.operating_treatment||'pending';$('feeMappingNote').value=item.classification_note||'';$('feeMappingEditId').value=index;$('feeMappingUpdatedAt').value=item.updated_at||'';$('feeMappingDialog').showModal();}
async function saveFeeMapping(event){
  event.preventDefault();const item=state.feeItems[Number($('feeMappingEditId').value)];if(!item)return;
  const payload={items:[item],primary_category_code:$('feeMappingCategoryCode').value.trim(),primary_category_name:$('feeMappingCategory').value.trim(),classification_note:$('feeMappingNote').value};
  const chosen=$('feeMappingInclude').value||'pending';if(chosen!==(item.operating_treatment||'pending'))payload.operating_treatment=chosen;
  if($('feeMappingMatchType').value)payload.source_description_match_type=$('feeMappingMatchType').value;
  if($('feeMappingMatchValue').value)payload.source_description_match_value=$('feeMappingMatchValue').value;
  if($('feeMappingPriority').value!=='')payload.mapping_priority=Number($('feeMappingPriority').value);
  const apply=async(previewToken)=>{if(previewToken)payload.preview_token=previewToken;await api('/api/ingest/fee-mappings/assign',{method:'POST',body:JSON.stringify(payload)});$('feeMappingDialog').close();toast('配置已保存，等待重算生效');await Promise.all([loadFees(),loadCategories()]);};
  try{if('operating_treatment' in payload)await previewOperatingChange(payload,apply);else await apply();}catch(e){toast(e.message,true);}
}
/* ── Assign dropdown (fee mapping inline selectors) ── */
function renderAssignOptions(query=''){
  const context=state.assignContext;if(!context)return;
  const treatment=context.kind==='treatment',keyword=query.trim().toLowerCase();
  const options=treatment?['income','expense','excluded','pending'].map(value=>({primary_category_code:value,primary_category_name:operatingLabel(value)})):[{primary_category_code:'unmapped',primary_category_name:'未映射（清除分类）'},...state.feeCategoryOptions];
  $('assignSearch').placeholder=treatment?'查找经营收支归属':'查找一级分类管理名称';
  const items=options.filter(x=>!keyword||x.primary_category_name.toLowerCase().includes(keyword));
  $('assignOptions').innerHTML=items.length?items.map(x=>`<button type="button" class="assign-option ${context.trigger.dataset.value===x.primary_category_code?'active':''}" data-assign-code="${esc(x.primary_category_code)}" data-assign-name="${esc(x.primary_category_name)}"><span>${esc(x.primary_category_name)}</span></button>`).join(''):`<div class="assign-empty">未找到匹配的${treatment?'归属':'分类'}</div>`;
  $('assignOptions').querySelectorAll('[data-assign-code]').forEach(btn=>{btn.onmousedown=e=>e.preventDefault();btn.onclick=()=>{closeAssignDropdown();assignResolved(context.trigger,btn.dataset.assignCode,btn.dataset.assignName)};});
}
let assignDropdownHost=null;
function assignDropdownHome(){const dropdown=$('assignDropdown');if(dropdown&&!assignDropdownHost)assignDropdownHost=dropdown.parentElement;return assignDropdownHost;}
function placeAssignDropdown(drop,trigger){const rect=trigger.getBoundingClientRect(),width=Math.min(250,window.innerWidth-16),height=drop.offsetHeight||286,dialog=drop.closest('#feeMappingDialog');if(dialog){const parentRect=dialog.getBoundingClientRect(),scrollLeft=dialog.scrollLeft||0,scrollTop=dialog.scrollTop||0,maxLeft=Math.max(8,dialog.clientWidth-width-8),left=Math.max(8,Math.min(rect.left-parentRect.left+scrollLeft,maxLeft)),below=rect.bottom-parentRect.top+scrollTop+6,above=rect.top-parentRect.top+scrollTop-height-6,top=rect.bottom+6+height<=window.innerHeight-8?below:Math.max(8,above);drop.style.width=`${width}px`;drop.style.left=`${left}px`;drop.style.top=`${top}px`;return;}const left=Math.max(8,Math.min(rect.left,window.innerWidth-width-8)),below=rect.bottom+6,top=below+height<=window.innerHeight-8?below:Math.max(8,rect.top-height-6);drop.style.width=`${width}px`;drop.style.left=`${left}px`;drop.style.top=`${top}px`;}
async function openAssignDropdown(trigger){if(state.assignContext?.trigger===trigger){closeAssignDropdown();return}closeAssignDropdown();hideTablePopover();if(trigger.id==='feeMappingCategoryTrigger'&&!state.feeCategoryOptions.length){await loadCategories();if(!trigger.isConnected||!$('feeMappingDialog')?.open)return;}const drop=$('assignDropdown'),isModal=trigger.id==='feeMappingCategoryTrigger';if(isModal){const dialog=$('feeMappingDialog');assignDropdownHome();if(dialog&&drop.parentElement!==dialog)dialog.appendChild(drop);drop.classList.add('fee-dialog-dropdown');}state.assignContext={trigger,modal:isModal,kind:trigger.dataset.assignKind||'category'};trigger.setAttribute('aria-expanded','true');$('assignSearch').value='';drop.hidden=false;renderAssignOptions();placeAssignDropdown(drop,trigger);setTimeout(()=>$('assignSearch').focus(),0);}
function closeAssignDropdown(){const context=state.assignContext,drop=$('assignDropdown'),home=assignDropdownHome();context?.trigger?.setAttribute('aria-expanded','false');if(drop){drop.hidden=true;if(home&&drop.parentElement!==home)home.appendChild(drop);drop.classList.remove('fee-dialog-dropdown');['left','top','width'].forEach(property=>drop.style.removeProperty(property));}state.assignContext=null;}
function assignResolved(trigger,code,name){
  if(trigger.id==='feeMappingCategoryTrigger'){closeAssignDropdown();$('feeMappingCategory').value=name;$('feeMappingCategoryCode').value=code;$('feeMappingCategoryValue').textContent=name;$('feeMappingCategoryValue').classList.remove('empty');trigger.dataset.value=code;trigger.dataset.name=name;return;}
  const index=Number(trigger.dataset.assignTrigger),item=state.feeItems[index];if(!item)return;
  const treatment=trigger.dataset.assignKind==='treatment',fieldLabel=treatment?'经营收支归属':'一级分类';
  const ids=state.selectedFees.size?[...state.selectedFees]:[index];
  const apply=async(previewToken)=>{
    const items=ids.map(i=>state.feeItems[i]);
    const payload=treatment?{items,operating_treatment:code}:{items,primary_category_code:code,primary_category_name:code==='unmapped'?'未映射':name};
    if(previewToken)payload.preview_token=previewToken;
    const result=await api('/api/ingest/fee-mappings/assign',{method:'POST',body:JSON.stringify(payload)});
    toast(`已保存 ${result.items.length} 条${treatment?'经营归属，等待重算生效':'分类'}`);await Promise.all([loadFees(),loadCategories()]);
  };
  if(treatment){previewOperatingChange({items:ids.map(i=>state.feeItems[i]),operating_treatment:code},apply).catch(e=>toast(e.message,true));return;}
  if(ids.length>1){showTablePopover('batch-confirm',`<div class="popover-message"><span class="popover-icon warning">!</span><div class="popover-copy"><p>已选中 <em>${ids.length}</em> 行，确认批量修改${fieldLabel}为「<em class="highlight">${esc(name)}</em>」？</p></div></div><div class="popover-actions"><button class="mini-button" data-popover-cancel>取消</button><button class="mini-button primary button" data-popover-confirm>确定修改</button></div>`,apply);return;}
  apply().catch(e=>toast(e.message,true));
}

/* ── Table popover (batch confirm) ── */
function hideTablePopover(){const pop=$('tablePopover');pop.hidden=true;pop.className='table-popover';pop.innerHTML='';state.popoverAction=null;}
function showTablePopover(kind,html,onConfirm){const pop=$('tablePopover');pop.className=`table-popover ${kind}`;pop.innerHTML=html;pop.hidden=false;state.popoverAction=onConfirm;pop.querySelector('[data-popover-cancel]').onclick=()=>{hideTablePopover();};pop.querySelector('[data-popover-confirm]').onclick=async()=>{const btn=pop.querySelector('[data-popover-confirm]');try{btn.disabled=true;btn.textContent='处理中…';await onConfirm();hideTablePopover();}catch(e){toast(e.message,true);btn.disabled=false;btn.textContent='确定修改';}};}
async function toggleFee(index){const item=state.feeItems[index];try{await api(`/api/ingest/fee-mappings/${item.mapping_id}/status`,{method:'PUT',body:JSON.stringify({is_active:!item.is_active,updated_at:item.updated_at})});toast(item.is_active?'映射已停用':'映射已启用');loadFees();}catch(e){toast(e.message,true)}}
async function exportFees(){try{const params=feeQuery();params.set('page','1');params.set('page_size','5000');params.set('export','true');const data=await api(`/api/ingest/fee-mappings?${params}`);const columns=['平台','来源单据','原始业务类型','原始描述','二级分类编码','二级分类名称','一级分类编码','一级分类名称','经营收支归属','映射状态','优先级','备注','更新时间','更新人'];const keys=['platform_name','source_document_type','source_business_type','source_description_match_value','secondary_category_code','secondary_category_name','primary_category_code','primary_category_name','operating_treatment','mapping_status','mapping_priority','classification_note','updated_at','updated_by'];const csv=[columns,...data.items.map(row=>keys.map(key=>{const value=key==='operating_treatment'?operatingLabel(row[key]):(row[key]??'');return `"${String(value).replaceAll('"','""')}"`;}))].map(row=>row.join(',')).join('\r\n');const link=document.createElement('a');link.href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));link.download=`费用映射_${new Date().toISOString().slice(0,10)}.csv`;link.click();URL.revokeObjectURL(link.href);}catch(e){toast(e.message,true)}}

function categoryQuery(){const params=new URLSearchParams({page:state.categoryPage,page_size:state.categoryPageSize});if($('categoryPlatform').value)params.set('platform_code',$('categoryPlatform').value);if($('categoryStatus').value)params.set('status',$('categoryStatus').value);if($('categoryKeyword').value)params.set('keyword',$('categoryKeyword').value);return params;}
async function loadCategoryPage(){try{const data=await api(`/api/ingest/fee-categories?${categoryQuery()}`);const allItems=data.items||[];const total=allItems.length;const size=state.categoryPageSize;const pages=Math.max(1,Math.ceil(total/size));const page=Math.min(state.categoryPage,pages);const start=(page-1)*size;state.categoryPage=page;state.feeCategories=allItems.slice(start,start+size);renderCategoryPage();renderCategoryPagination({total,page,page_size:size});$('categoryTotal').textContent=`共 ${total} 条`;}catch(e){toast(e.message,true);}}
function renderCategoryPagination(pagination){const total=Number(pagination.total||0),size=Number(pagination.page_size||state.categoryPageSize),current=Number(pagination.page||1),pages=Math.max(1,Math.ceil(total/size));renderPagination('categoryPageNumbers','categoryPrevPage','categoryNextPage','categoryPageInfo','categoryPageSize',current,pages,total,page=>{state.categoryPage=page;loadCategoryPage()});}
function renderCategoryPage(){
  $('categoryBody').innerHTML=state.feeCategories.length?state.feeCategories.map((item,index)=>`<tr><td>${item.display_order}</td><td><span class="category-code">${esc(item.primary_category_code)}</span></td><td><strong>${esc(item.primary_category_name)}</strong>${Number(item.same_name_code_count)>1?'<span class="category-name-conflict">名称重复</span>':''}</td><td>${item.mapping_count}</td><td>${item.included_mapping_count}</td><td><div class="platform-list" title="${esc((item.platforms||[]).join('、'))}">${esc((item.platforms||[]).join('、')||'—')}</div></td><td>${tag(item.is_active?'active':'inactive')}</td><td class="wrap">${esc(item.classification_note||'—')}</td><td>${fmt(item.updated_at)}</td><td><div class="row-actions"><button class="icon-action" data-edit-category="${index}" title="编辑"><svg><use href="#i-edit"/></svg><span>编辑</span></button><button class="icon-action ${item.is_active?'warning':'primary'}" data-toggle-category="${index}" title="${item.is_active?'停用':'启用'}"><svg><use href="#i-power"/></svg><span>${item.is_active?'停用':'启用'}</span></button><button class="icon-action danger" data-delete-category="${index}" title="删除"><svg><use href="#i-trash"/></svg><span>删除</span></button><button class="icon-action" data-view-category-mappings="${index}" title="查看映射"><svg><use href="#i-search"/></svg><span>查看</span></button></div></td></tr>`).join(''):'<tr><td colspan="10" class="empty-row">没有符合条件的一级分类</td></tr>';
}
async function toggleCategoryStatus(index){const item=state.feeCategories[index];if(!item)return;try{await api(`/api/ingest/fee-categories/${encodeURIComponent(item.primary_category_code)}`,{method:'PUT',body:JSON.stringify({primary_category_code:item.primary_category_code,primary_category_name:item.primary_category_name,display_order:item.display_order,is_active:!item.is_active,classification_note:item.classification_note,updated_at:item.updated_at})});toast(item.is_active?'分类已停用':'分类已启用');await Promise.all([loadCategoryPage(),loadCategories()]);}catch(e){toast(e.message,true)}}
async function deleteCategory(index){const item=state.feeCategories[index];if(!item)return;if(!confirm(`确认删除分类「${item.primary_category_name}」(${item.primary_category_code})？\n${item.mapping_count>0?`该分类下有 ${item.mapping_count} 条映射，删除后映射将变为未映射状态。`:''}`))return;try{await api(`/api/ingest/fee-categories/${encodeURIComponent(item.primary_category_code)}`,{method:'DELETE'});toast('分类已删除');await Promise.all([loadCategoryPage(),loadCategories()]);}catch(e){toast(e.message,true)}}
function openCategoryDialog(item=null){
  $('categoryDialogTitle').textContent=item?'编辑一级分类':'新增一级分类';$('categoryForm').dataset.editCode=item?.primary_category_code||'';
  const platformCode=item?.platform_code||(item?.platform_codes?.length===1?item.platform_codes[0]:'');
   const platformField=$('categoryFormPlatform').closest('label');
   if(platformField)platformField.hidden=Boolean(item);
   $('categoryFormPlatform').value=platformCode;$('categoryFormPlatform').disabled=Boolean(item);$('categoryFormPlatform').required=!item;
  $('categoryFormName').value=item?.primary_category_name||'';$('categoryFormOrder').value=item?.display_order??0;$('categoryFormActive').checked=Boolean(item?.is_active??true);$('categoryFormNote').value=item?.classification_note||'';$('categoryFormUpdatedAt').value=item?.updated_at||'';$('categoryDialog').showModal();
}
async function saveCategory(event){
  event.preventDefault();const editCode=$('categoryForm').dataset.editCode;const payload={primary_category_name:$('categoryFormName').value,display_order:Number($('categoryFormOrder').value||0),is_active:$('categoryFormActive').checked,classification_note:$('categoryFormNote').value,updated_at:$('categoryFormUpdatedAt').value||null};
  if(!editCode){payload.platform_code=$('categoryFormPlatform').value;if(!payload.platform_code){toast('请选择平台',true);return;}}
  try{if(editCode)await api(`/api/ingest/fee-categories/${encodeURIComponent(editCode)}`,{method:'PUT',body:JSON.stringify(payload)});else await api('/api/ingest/fee-categories',{method:'POST',body:JSON.stringify(payload)});$('categoryDialog').close();toast(editCode?'一级分类已更新':'一级分类已创建');await Promise.all([loadCategoryPage(),loadCategories()]);}catch(e){toast(e.message,true);}
}
function viewCategoryMappings(item){$('feeKeyword').value=item.primary_category_name;state.feePage=1;switchPage('feeMappings');}

function rawFeeQuery(){const params=new URLSearchParams({page:state.rawFeePage,page_size:state.rawFeePageSize});[['platform_code','rawPlatform'],['source_document_type','rawDocument'],['mapping_status','rawStatus'],['operating_treatment','rawTreatment'],['date_from','rawDateFrom'],['date_to','rawDateTo'],['keyword','rawKeyword']].forEach(([key,id])=>{if($(id).value)params.set(key,$(id).value)});return params;}
async function loadRawFees(){try{const data=await api(`/api/ingest/operating-details?${rawFeeQuery()}`);state.rawFeeItems=data.items;renderRawFees();renderRawFeePagination(data.pagination);$('rawFeeTotal').textContent=`共 ${data.pagination.total} 条日汇总 · ${data.summary.scene_total??'—'} 种收支场景`;$('rawOperatingSummary').textContent=`筛选范围经营收入 ${money(data.summary.income_amount)} 元 · 经营支出 ${money(data.summary.expense_amount)} 元；待确认 ${data.summary.pending_total||0} 条，原公式净额 ${money(data.summary.pending_amount||0)} 元；不计入项目保留明细。`;}catch(e){toast(e.message,true);}}

function renderRawFeePagination(pagination){const total=Number(pagination.total||0),size=Number(pagination.page_size||state.rawFeePageSize),current=Number(pagination.page||1),pages=Math.max(1,Math.ceil(total/size));renderPagination('rawFeePageNumbers','rawFeePrevPage','rawFeeNextPage','rawFeePageInfo','rawFeePageSize',current,pages,total,page=>{state.rawFeePage=page;loadRawFees()});}
function renderRawFees(){$('rawFeeBody').innerHTML=state.rawFeeItems.length?state.rawFeeItems.map(r=>`<tr><td>${esc(r.stat_date)}</td><td>${esc(r.platform_name)}<br>${esc(r.shop_name)}</td><td>${r.source_document_type==='fund'?'资金':'结算'}</td><td class="wrap">${esc(r.secondary_category_name)}</td><td>${esc(r.primary_category_name)}</td><td>${esc(operatingLabel(r.operating_treatment))}</td><td class="wrap">${esc(r.operating_treatment==='excluded'?(r.exclusion_reason||'财务设置不计入经营收支'):'—')}</td><td>${money(r.source_signed_amount)}</td><td>${money(r.income_amount)}</td><td>${money(r.expense_amount)}</td><td>${tag(r.mapping_status)}</td></tr>`).join(''):'<tr><td colspan="11" class="empty-row">当前筛选条件下没有收支日汇总</td></tr>';}
async function exportRawFees(){try{const params=rawFeeQuery();params.set('page_size','1000');params.set('export','true');let rows=[],page=1,total=1;while(rows.length<total){params.set('page',String(page++));const data=await api(`/api/ingest/operating-details?${params}`);rows.push(...data.items);total=data.pagination.total;if(!data.items.length)break;}const labels=['日期','平台','公司','店铺','来源','原始场景','一级分类','经营归属','不计入原因','原公式净额','经营收入','经营支出','不计入净额','映射状态'];const keys=['stat_date','platform_name','company_name','shop_name','source_document_type','secondary_category_name','primary_category_name','operating_treatment','exclusion_reason','source_signed_amount','income_amount','expense_amount','excluded_amount','mapping_status'];const csv=[labels,...rows.map(r=>keys.map(k=>`"${String(k==='operating_treatment'?operatingLabel(r[k]):(r[k]??'')).replaceAll('"','""')}"`))].map(r=>r.join(',')).join('\r\n');const link=document.createElement('a');link.href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));link.download=`全部收支类型_${new Date().toISOString().slice(0,10)}.csv`;link.click();URL.revokeObjectURL(link.href);}catch(e){toast(e.message,true);}}

/* ── Finance operating configuration ── */
const financePk={budgets:'budget_month','shop-plans':'shop_plan_id',recharges:'recharge_id',adjustments:'adjustment_id','marketing-expenses':'marketing_expense_id'};
function financeMonthValue(){return $('financeMonth').value?`${$('financeMonth').value}-01`:'';}
function currentMonthValue(){const today=new Date();return `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`;}
function currentDateValue(){const today=new Date();return `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;}
function bindNativePicker(input){if(!input)return;const open=()=>{if(input.disabled)return;input.focus();if(typeof input.showPicker!=='function')return;try{input.showPicker()}catch(_error){input.focus()}};input.addEventListener('click',open);input.closest('label')?.addEventListener('click',event=>{if(event.target===input)return;event.preventDefault();open()});input.style.cursor='pointer';}
function financeRate(value){return Number.isFinite(Number(value))?Number(value):0;}
function financePercent(value){return financeRate(value).toLocaleString('zh-CN',{minimumFractionDigits:1,maximumFractionDigits:1})+'%';}
function compactFinanceAmount(value){const amount=Number(value||0);return Math.abs(amount)>=10000?{value:(amount/10000).toLocaleString('zh-CN',{minimumFractionDigits:1,maximumFractionDigits:2}),unit:'万元'}:{value:money(amount),unit:'元'};}
function platformBadge(value){const code=String(value||'other').toLowerCase().replace(/[^a-z0-9_-]/g,'');return '<span class="finance-platform-tag '+esc(code)+'">'+esc(value||'—')+'</span>';}
function financeProgress(value,tone='blue',label=true){const rate=financeRate(value),width=Math.min(100,Math.max(0,rate));return '<div class="finance-inline-progress"><span class="finance-progress-track"><i class="finance-progress-fill '+tone+'" style="--progress:'+width+'%"></i></span>'+(label?'<b class="'+tone+'">'+financePercent(rate)+'</b>':'')+'</div>';}
function financeStatusPill(value,label){return '<span class="finance-row-status '+esc(value)+'"><i></i>'+esc(label)+'</span>';}
function financeStatCard(label,value,tone='blue',type='money'){const amount=type==='percent'?{value:financePercent(value),unit:''}:type==='count'?{value:String(value||0),unit:'家'}:compactFinanceAmount(value);return '<article class="panel finance-view-stat '+tone+'"><small>'+esc(label)+'</small><div><strong>'+esc(amount.value)+'</strong><span>'+esc(amount.unit)+'</span></div></article>';}
function financeMarketingCard(label,value,tone='blue',type='money'){const amount=type==='percent'?{value:financePercent(value),unit:''}:compactFinanceAmount(value);return '<article class="panel finance-marketing-card '+tone+'"><small>'+esc(label)+'</small><div><strong>'+esc(amount.value)+'</strong><span>'+esc(amount.unit)+'</span></div>'+(type==='money-edit'?'<button type="button" class="text-button finance-total-manage-action" data-permission="finance_budget.marketing_budget.manage" data-edit-marketing-budget>修改预算</button>':'')+'</article>';}
function animateFinanceProgress(){document.querySelectorAll('.finance-progress-fill').forEach(node=>node.classList.add('is-ready'));}
function parseCsvRows(text){const rows=[];let row=[],cell='',quoted=false;for(let index=0;index<text.length;index++){const char=text[index],next=text[index+1];if(char==='"'&&quoted&&next==='"'){cell+='"';index++;continue}if(char==='"'){quoted=!quoted;continue}if(char===','&&!quoted){row.push(cell.trim());cell='';continue}if((char==='\n'||char==='\r')&&!quoted){if(char==='\r'&&next==='\n')index++;row.push(cell.trim());cell='';if(row.some(Boolean))rows.push(row);row=[];continue}cell+=char}if(cell||row.length){row.push(cell.trim());if(row.some(Boolean))rows.push(row)}return rows;}
async function importGsvTargets(file){
  if(!file)return;try{const rows=parseCsvRows((await file.text()).replace(/^\ufeff/,''));if(rows.length<2)throw new Error('CSV 至少需要表头和一行数据');const aliases={budget_month:['budget_month','月份'],shop_code:['shop_code','店铺编码'],gsv_target_amount:['gsv_target_amount','GSV目标','目标GSV'],promotion_budget_amount:['promotion_budget_amount','推广预算'],remark:['remark','备注']},headers=rows[0].map(value=>value.trim()),index={};Object.entries(aliases).forEach(([key,names])=>index[key]=headers.findIndex(value=>names.includes(value)));if(index.shop_code<0||index.gsv_target_amount<0)throw new Error('CSV 必须包含店铺编码和 GSV目标');const defaultMonth=financeMonthValue()||currentMonthValue()+'-01',existing=(await api('/api/ingest/finance-config/shop-plans?budget_month='+defaultMonth+'&page=1&page_size=200')).items||[];let success=0;for(const values of rows.slice(1)){const shopCode=values[index.shop_code],shop=state.shops.find(item=>item.shop_code===shopCode);if(!shop)throw new Error('店铺编码不存在：'+shopCode);const month=(index.budget_month>=0?values[index.budget_month]:'')||defaultMonth,normalizedMonth=month.length===7?month+'-01':month,current=existing.find(item=>item.shop_plan_id&&item.shop_code===shopCode&&String(item.budget_month).slice(0,7)===normalizedMonth.slice(0,7)),payload={permission_action:'gsv_detail',budget_month:normalizedMonth,shop_code:shopCode,gsv_target_amount:values[index.gsv_target_amount],promotion_budget_amount:index.promotion_budget_amount>=0&&values[index.promotion_budget_amount]!==''?values[index.promotion_budget_amount]:(current?.promotion_budget_amount||0),remark:index.remark>=0?values[index.remark]:'',updated_at:current?.updated_at||null};await api('/api/ingest/finance-config/shop-plans'+(current?'/'+current.shop_plan_id:''),{method:current?'PUT':'POST',body:JSON.stringify(payload)});success++}toast('已导入 '+success+' 条 GSV 目标');loadFinanceConfig();}catch(e){toast(e.message,true)}finally{$('financeBatchFile').value=''}
}
/* ── Operating configuration console ── */
const financeConsoleViewResources={financeOverview:null,financeGsv:'gsv-targets',financePromotion:'shop-budgets',financeAdjustments:'adjustments',financeRecharges:'recharges',financeSpend:'promotion-spend',financeMarketing:'marketing-expenses',financeExpenseTypes:'expense-types'};
const financeConsoleResourceMeta={
  'gsv-targets':{title:'GSV目标明细',description:'DIM当前月份全部有效店铺均展示；未设置目标的店铺可在行内直接分配。',action:'',mode:'gsv'},
  'shop-budgets':{title:'店铺预算分配',description:'DIM当前月份全部有效店铺均展示；未分配预算的店铺可在行内直接分配。',action:'',mode:'promotion-allocation'},
  adjustments:{title:'推广预算调整记录',description:'每次推广总预算二次修改均保留调整前、调整后、差额、操作人、时间和备注，本页只读。',action:'',mode:'adjustments'},
  'marketing-budget-history':{title:'营销预算调整记录',description:'每次营销总预算二次修改均保留调整前、调整后、差额、操作人、时间和备注，本页只读。',action:'',mode:'marketing-adjustments'},
  recharges:{title:'充值流水',description:'DIM当前月份全部有效店铺均展示，在店铺行直接登记充值；充值记录独立留痕。',action:'',mode:'recharges'},
  'promotion-spend':{title:'推广消耗',description:'只读展示实际推广消耗、分配预算、累计充值、理论余额和执行率。',action:'',mode:'promotion-spend'},
  'marketing-expenses':{title:'营销费用流水',description:'登记整体营销费用；费用类型只能选择费用类型管理中启用的类型。',action:'',mode:'marketing-expenses'},
  'expense-types':{title:'营销费用类型',description:'维护营销费用登记可选类型；停用后不能登记新费用，但历史流水仍保留。',action:'新增费用类型',mode:'expense-types'},
};
const financeConsoleActions={gsv_total:'finance_budget.gsv_total.manage',gsv_detail:'finance_budget.gsv_detail.manage',promotion_total:'finance_budget.promotion_total.manage',shop_budget:'finance_budget.shop_budget.manage',promotion_recharge:'finance_budget.promotion_recharge.manage',marketing_budget:'finance_budget.marketing_budget.manage',marketing_expense:'finance_budget.marketing_expense.manage',expense_type:'finance_budget.expense_type.manage'};
function financeCanPage(page){const permission=financePagePermissions[page];return !permission||!(window.currentPermissions instanceof Set)||Boolean(window.currentUser?.is_super_admin)||window.currentPermissions.has(permission);}
function financeCanAction(action){const permission=financeConsoleActions[action];return !permission||!(window.currentPermissions instanceof Set)||Boolean(window.currentUser?.is_super_admin)||window.currentPermissions.has(permission);}
function financeConsoleMonth(){const value=$('financeMonth')?.value||'';return value?`${value}-01`:'';}
function financeFilterValues(kind){
  if(kind==='run_operator')return Array.isArray(state.runFilters?.operator)?state.runFilters.operator:[];
  if(kind==='etl_operator')return Array.isArray(state.etlFilters?.operator)?state.etlFilters.operator:[];
  if(kind==='log_operator')return Array.isArray(state.logOperatorSelections)?state.logOperatorSelections:[];
  return Array.isArray(state.financeFilters?.[kind])?state.financeFilters[kind]:[];
}
function setFilterValues(kind,values){
  if(kind==='run_operator'){state.runFilters.operator=[...values];return;}
  if(kind==='etl_operator'){state.etlFilters.operator=[...values];return;}
  if(kind==='log_operator'){state.logOperatorSelections=[...values];return;}
  state.financeFilters[kind]=[...values];
}
function renderPickerLabel(kind,inputId,labelId){const values=financeFilterValues(kind);if($(inputId))$(inputId).value=values.join(',');if($(labelId))$(labelId).textContent=financeFilterSummary(kind);}
function financeShopFilterRows(){return Array.isArray(state.financeSummary?.shops)?state.financeSummary.shops:(state.shops||[]);}
function financeOptionRows(kind,{activeOnly=false}={}){
  if(kind==='run_operator')return (state.runOperatorOptions||[]).map(item=>typeof item==='string'?{id:item,label:item,sub:'',search:item}:item);
  if(kind==='etl_operator')return (state.etlOperatorOptions||[]).map(item=>typeof item==='string'?{id:item,label:item,sub:'',search:item}:item);
  if(kind==='log_operator')return (state.logOperatorOptions||[]).map(item=>typeof item==='string'?{id:item,label:item,sub:'',search:item}:item);
  if(kind==='finance_operator')return (state.financeOperatorOptions||[]).map(item=>typeof item==='string'?{id:item,label:item,sub:'',search:item}:item);
  if(kind==='expense_type')return (state.financeExpenseTypes||[]).filter(item=>!activeOnly||item.is_active).map(item=>({id:item.expense_type_code,label:item.expense_type_name,sub:'',search:`${item.expense_type_name} ${item.expense_type_code}`}));
  let rows=financeShopFilterRows();
  if(kind!=='platform')rows=rows.filter(row=>!financeFilterValues('platform').length||financeFilterValues('platform').includes(row.platform_code));
  if(kind==='shop')rows=rows.filter(row=>!financeFilterValues('company').length||financeFilterValues('company').includes(row.company_code));
  const key=kind==='platform'?'platform_code':kind==='company'?'company_code':'shop_code';
  const label=kind==='platform'?'platform_name':kind==='company'?'company_name':'shop_name';
  return [...new Map(rows.map(row=>[row[key],{id:row[key],label:row[label],sub:'',search:`${row[label]||''} ${row[key]||''}`}])).values()].filter(row=>row.id);
}
let financeExpenseTypesRequest=null;
let financeAssignDropdownHost=null;
async function ensureFinanceExpenseTypes(){
  if(state.financeExpenseTypesLoaded)return state.financeExpenseTypes;
  if(!financeExpenseTypesRequest){
    financeExpenseTypesRequest=api('/api/ingest/finance-config/expense-types?page=1&page_size=200').then(data=>{
      state.financeExpenseTypes=Array.isArray(data?.items)?data.items:[];
      state.financeExpenseTypesLoaded=true;
      return state.financeExpenseTypes;
    }).finally(()=>{financeExpenseTypesRequest=null;});
  }
  return financeExpenseTypesRequest;
}
function financeAssignDropdownHome(){
  const dropdown=$('financeAssignDropdown');
  if(dropdown&&!financeAssignDropdownHost)financeAssignDropdownHost=dropdown.parentElement;
  return financeAssignDropdownHost;
}
function financeFilterSummary(kind){
  const selected=financeFilterValues(kind),options=financeOptionRows(kind);
  if(!selected.length){if(kind==='expense_type')return '全部类型';if(kind.endsWith('_operator'))return '全部操作人';return `全部${kind==='platform'?'平台':kind==='company'?'公司':'店铺'}`;}
  const labels=selected.map(id=>options.find(item=>item.id===id)?.label||id);
  return labels.length===1?labels[0]:`${labels[0]} 等 ${labels.length} 项`;
}
function renderFinanceFilterLabels(){
  [['platform','financePlatform','financePlatformLabel'],['company','financeCompany','financeCompanyLabel'],['shop','financeShop','financeShopLabel'],['expense_type','financeExpenseTypeFilter','financeExpenseTypeFilterLabel'],['finance_operator','financeOperator','financeOperatorLabel']].forEach(([kind,inputId,labelId])=>{const values=financeFilterValues(kind);if($(inputId))$(inputId).value=values.join(',');if($(labelId))$(labelId).textContent=financeFilterSummary(kind);});
}
function syncFinanceFilterSelections(){
  const rows=financeShopFilterRows();
  [['platform','platform_code'],['company','company_code'],['shop','shop_code']].forEach(([kind,key])=>{
    const valid=new Set(rows.map(row=>row[key]).filter(Boolean));
    state.financeFilters[kind]=financeFilterValues(kind).filter(value=>valid.has(value));
  });
}
function financeFilterQuery(){
  const params=new URLSearchParams();const month=financeConsoleMonth();if(month)params.set('budget_month',month);
  [['platform_codes','platform'],['company_codes','company'],['shop_codes','shop']].forEach(([key,kind])=>{const values=financeFilterValues(kind);if(values.length)params.set(key,values.join(','));});
  const types=financeFilterValues('expense_type');if(types.length)params.set('expense_type',types.join(','));
  const keyword=($('financeKeyword')?.value||'').trim();if(keyword)params.set('keyword',keyword);
  if(['adjustments','marketing-budget-history','marketing-expenses'].includes(state.financeResource)){
    const operators=financeFilterValues('finance_operator');if(operators.length)params.set('changed_by',operators.join(','));
    const dateFrom=$('financeDateFrom')?.value||'',dateTo=$('financeDateTo')?.value||'';if(dateFrom)params.set('date_from',dateFrom);if(dateTo)params.set('date_to',dateTo);
  }
  if(state.financeResource==='expense-types'){const status=$('financeStatus')?.value||'';if(status)params.set('status',status);}
  return params;
}
function placeFinanceAssignDropdown(drop,trigger){const rect=trigger.getBoundingClientRect(),width=Math.min(320,window.innerWidth-16),height=drop.offsetHeight||360,dialog=drop.closest('#financeConfigDialog');if(dialog){const parentRect=dialog.getBoundingClientRect(),scrollLeft=dialog.scrollLeft||0,scrollTop=dialog.scrollTop||0,maxLeft=Math.max(8,dialog.clientWidth-width-8),left=Math.max(8,Math.min(rect.left-parentRect.left+scrollLeft,maxLeft)),below=rect.bottom-parentRect.top+scrollTop+6,above=rect.top-parentRect.top+scrollTop-height-6,top=rect.bottom+6+height<=window.innerHeight-8?below:Math.max(8,above);drop.style.width=`${width}px`;drop.style.left=`${left}px`;drop.style.top=`${top}px`;return;}const left=Math.max(8,Math.min(rect.left,window.innerWidth-width-8)),below=rect.bottom+6,top=below+height<=window.innerHeight-8?below:Math.max(8,rect.top-height-6);drop.style.width=`${width}px`;drop.style.left=`${left}px`;drop.style.top=`${top}px`;}
function renderFinanceAssignOptions(query=''){
  const context=state.financeDropdown;if(!context)return;const keyword=query.trim().toLowerCase(),items=context.items.filter(item=>!keyword||`${item.label} ${item.sub||''} ${item.search||''}`.toLowerCase().includes(keyword));
  const single=context.kind==='form_expense';$('financeAssignOptions').innerHTML=items.length?items.map(item=>{const selected=context.selected.includes(item.id);return `<button type="button" class="finance-assign-option ${selected?'selected':''}" data-finance-option="${esc(item.id)}"><input type="${single?'radio':'checkbox'}" tabindex="-1" ${single?'name="finance-assign-single" ':''}${selected?'checked':''}><span>${esc(item.label)}</span><small>${esc(item.sub||'')}</small></button>`;}).join(''):'<div class="assign-empty">未找到匹配项，不会创建新数据</div>';
  $('financeAssignSelectedSummary').textContent=context.selected.length?`已选择 ${context.selected.length} 项`:'未选择';
}
function closeFinanceAssignDropdown(){const context=state.financeDropdown,dropdown=$('financeAssignDropdown'),home=financeAssignDropdownHome();context?.trigger?.setAttribute('aria-expanded','false');if(dropdown){dropdown.hidden=true;if(home&&dropdown.parentElement!==home)home.appendChild(dropdown);dropdown.classList.remove('finance-dialog-dropdown');['left','top','width'].forEach(property=>dropdown.style.removeProperty(property));}state.financeDropdown=null;}
 function applyFinanceDropdownSelection(){const context=state.financeDropdown;if(!context)return;const selected=[...context.selected];if(context.kind==='form_expense'){const type=state.financeExpenseTypes.find(item=>item.expense_type_code===selected[0]);$('financeFormExpenseType').value=selected[0]||'';$('financeFormExpenseTypeLabel').textContent=type?.expense_type_name||'请选择费用类型';$('financeExpenseTypeTrigger').setAttribute('aria-expanded','false');closeFinanceAssignDropdown();return;}setFilterValues(context.kind,selected);if(['platform','company','shop','expense_type','finance_operator'].includes(context.kind)){syncFinanceFilterSelections();renderFinanceFilterLabels();}else if(context.kind==='run_operator')renderPickerLabel('run_operator','runOperator','runOperatorLabel');else if(context.kind==='etl_operator')renderPickerLabel('etl_operator','etlOperator','etlOperatorLabel');else if(context.kind==='log_operator')renderPickerLabel('log_operator','logOperator','logOperatorLabel');closeFinanceAssignDropdown();if(context.kind==='run_operator'){state.runPage=1;loadRuns();return;}if(context.kind==='etl_operator'){state.etlPage=1;loadEtls();return;}if(context.kind==='log_operator'){state.logPage=1;loadLogs();return;}state.financePage=1;loadFinanceConfig();}
async function openFinanceAssignDropdown(trigger){
  if(state.financeDropdown?.trigger===trigger){closeFinanceAssignDropdown();return;}
  closeFinanceAssignDropdown();
  const kind=trigger.dataset.financeFilter||'form_expense';
  if(kind==='form_expense'){
    try{await ensureFinanceExpenseTypes();}catch(error){toast(error.message,true);return;}
    if(!trigger.isConnected||!$('financeConfigDialog')?.open)return;
  }
  const contextItems=kind==='form_expense'?financeOptionRows('expense_type',{activeOnly:true}):financeOptionRows(kind);
  const current=kind==='form_expense'?[($('financeFormExpenseType')?.value||'')].map(value=>state.financeExpenseTypes.find(item=>item.is_active&&(item.expense_type_code===value||item.expense_type_name===value))?.expense_type_code||'').filter(Boolean):financeFilterValues(kind);
  state.financeDropdown={trigger,kind,items:contextItems,selected:[...current]};
  const dropdown=$('financeAssignDropdown');
  if(kind==='form_expense'){
    const dialog=$('financeConfigDialog');
    financeAssignDropdownHome();
    if(dialog&&dropdown.parentElement!==dialog)dialog.appendChild(dropdown);
    dropdown.classList.add('finance-dialog-dropdown');
  }
  trigger.setAttribute('aria-expanded','true');$('financeAssignSearch').value='';$('financeAssignSearch').placeholder=kind==='form_expense'?'搜索启用的费用类型':'搜索选项';dropdown.hidden=false;renderFinanceAssignOptions();placeFinanceAssignDropdown(dropdown,trigger);setTimeout(()=>$('financeAssignSearch').focus(),0);
}
function financeActionButton(action,label,attrs=''){
  const pages={gsv_detail:'financeGsv',shop_budget:'financePromotion',promotion_recharge:'financeRecharges',marketing_expense:'financeMarketing',expense_type:'financeExpenseTypes'},page=pages[action],permission=financeConsoleActions[action],pagePermission=financePagePermissions[page],buttonClass=['gsv_detail','shop_budget'].includes(action)?'finance-detail-manage-action':'finance-total-manage-action';
  return financeCanAction(action)?`<button type="button" class="icon-action ${buttonClass}" data-permission="${permission}" data-page-permission="${pagePermission}" data-finance-action="${action}" ${attrs}><svg><use href="#i-edit"/></svg><span>${label}</span></button>`:'';
}
function financeRowShopContext(row){return `<strong>${esc(row.shop_name||'—')}</strong>`;}
function financeTargetCell(row){return row.target_is_set?money(row.gsv_target_amount):'<span class="finance-unset">未设置</span>';}
function financeTargetStatusCell(row){if(!row.target_is_set)return financeStatusPill('attention','未设置');const rate=financeRate(row.gsv_completion_rate);return financeStatusPill(rate>=100?'completed':rate>=80?'progress':'attention',rate>=100?'已完成':rate>=80?'进行中':'需关注');}
function financeBudgetStatusCell(row){const pending=Number(row.pending_recharge_amount||0),rate=financeRate(row.promotion_execution_rate);return financeStatusPill(Number(row.over_recharge_amount||0)>0||rate>100?'danger':pending>0?'attention':'normal',Number(row.over_recharge_amount||0)>0?'超额充值':pending>0?'待充值':'正常');}
function financeConsoleColumns(resource){
  if(resource==='gsv-targets')return [['platform_name','平台',platformBadge],['company_name','公司',value=>esc(value||'—')],['shop_name','店铺',(value,row)=>financeRowShopContext(row)],['gsv_target_amount','目标 GSV（元）',(value,row)=>financeTargetCell(row)],['actual_gsv_amount','实际 GSV（元）',value=>`<strong class="finance-number purple">${money(value)}</strong>`],['gsv_completion_rate','完成率',(value,row)=>financeProgress(row.gsv_completion_rate,financeRate(row.gsv_completion_rate)>=100?'purple':'orange')],['target_status','状态',(value,row)=>financeTargetStatusCell(row)]];
  if(resource==='shop-budgets')return [['platform_name','平台',platformBadge],['company_name','公司',value=>esc(value||'—')],['shop_name','店铺',(value,row)=>financeRowShopContext(row)],['promotion_budget_amount','已分配预算（元）',value=>money(value)],['recharge_amount','累计充值（元）',value=>money(value)],['pending_recharge_amount','待充值（元）',value=>`<strong class="finance-number orange">${money(value)}</strong>`],['promotion_expense_amount','实际推广消耗（元）',value=>`<strong class="finance-number purple">${money(value)}</strong>`],['theoretical_account_balance','理论余额（元）',value=>money(value)],['promotion_execution_rate','执行率',(value,row)=>financeProgress(row.promotion_execution_rate,financeRate(row.promotion_execution_rate)>100?'orange':'blue')]];
  if(resource==='recharges')return [['platform_name','平台',platformBadge],['company_name','公司',value=>esc(value||'—')],['shop_name','店铺',(value,row)=>financeRowShopContext(row)],['promotion_budget_amount','当月预算（元）',value=>money(value)],['recharge_amount','累计充值（元）',value=>money(value)],['pending_recharge_amount','待充值（元）',value=>money(value)],['latest_recharge_date','最近充值日期',day],['latest_recharge_amount','最近充值金额（元）',value=>money(value)]];
  if(resource==='promotion-spend')return [['platform_name','平台',platformBadge],['company_name','公司',value=>esc(value||'—')],['shop_name','店铺',(value,row)=>financeRowShopContext(row)],['promotion_expense_amount','实际推广消耗（元）',value=>`<strong class="finance-number purple">${money(value)}</strong>`],['promotion_budget_amount','分配预算（元）',value=>money(value)],['recharge_amount','累计充值（元）',value=>money(value)],['theoretical_account_balance','理论余额（元）',value=>money(value)],['promotion_execution_rate','预算执行率',(value,row)=>financeProgress(row.promotion_execution_rate,financeRate(row.promotion_execution_rate)>100?'orange':'blue')]];
  if(resource==='adjustments')return [['budget_month','预算月份',value=>day(value).slice(0,7)],['before_amount','调整前金额（元）',value=>value===null||value===undefined?'—':money(value)],['after_amount','调整后金额（元）',value=>value===null||value===undefined?'—':money(value)],['adjustment_amount','调整金额（元）',value=>`<strong class="finance-number ${Number(value)>=0?'green':'orange'}">${Number(value)>0?'+':''}${money(value)}</strong>`],['created_at','操作时间',fmt],['changed_by','操作人',(value,row)=>esc(value||row.updated_by||'—')],['change_remark','备注',(value,row)=>{const note=value||row.reason||'';return `<span class="finance-history-note" title="${esc(note)}">${esc(note||'—')}</span>`;}]];
  if(resource==='marketing-budget-history')return [['budget_month','预算月份',value=>day(value).slice(0,7)],['before_amount','调整前金额（元）',value=>money(value)],['after_amount','调整后金额（元）',value=>money(value)],['change_amount','调整金额（元）',value=>`<strong class="finance-number ${Number(value)>=0?'green':'orange'}">${Number(value)>0?'+':''}${money(value)}</strong>`],['changed_at','操作时间',fmt],['changed_by','操作人',value=>esc(value||'—')],['remark','备注',value=>`<span class="finance-history-note" title="${esc(value||'')}">${esc(value||'—')}</span>`]];
  if(resource==='marketing-expenses')return [['expense_date','费用日期',day],['expense_type','费用类型',value=>`<span class="finance-type-tag">${esc(value||'—')}</span>`],['counterparty','合作方 / 内容',(value,row)=>`<strong>${esc(value||'—')}</strong><br><span class="muted">${esc(row.remark||'—')}</span>`],['expense_amount','费用金额（元）',value=>`<strong class="finance-number orange">${money(value)}</strong>`],['document_no','单据号',value=>esc(value||'—')],['updated_at','更新时间',fmt]];
  if(resource==='expense-types')return [['expense_type_name','名称',(value,row)=>`<strong>${esc(value||'—')}</strong><br><span class="muted">${esc('编码：'+(row.expense_type_code||''))}</span>`],['is_active','状态',value=>tag(value?'active':'inactive')],['remark','备注',value=>esc(value||'—')],['created_at','创建时间',fmt],['updated_at','更新时间',fmt]];
  return [['budget_month','月份',value=>day(value)],['gsv_target_amount','财务总GSV目标',money],['promotion_budget_amount','推广总预算',money],['marketing_budget_amount','营销总预算',money],['remark','备注',value=>esc(value||'—')],['updated_at','更新时间',fmt]];
}
function financeAdjustmentResource(){return state.financeAdjustmentSubpage==='marketing'?'marketing-budget-history':'adjustments';}
function setFinanceAdjustmentSubpage(subpage){state.financeAdjustmentSubpage=subpage==='marketing'?'marketing':'promotion';document.querySelectorAll('[data-finance-adjustment-tab]').forEach(node=>{const active=node.dataset.financeAdjustmentTab===state.financeAdjustmentSubpage;node.classList.toggle('active',active);node.setAttribute('aria-selected',String(active));});if(state.financeView==='financeAdjustments'){state.financeResource=financeAdjustmentResource();state.financePage=1;updateFinanceResourceChrome();loadFinanceConfig();}}
function activateFinanceView(view){state.financeView=view;state.financeResource=view==='financeAdjustments'?financeAdjustmentResource():(financeConsoleViewResources[view]||'');document.querySelectorAll('[data-finance-view]').forEach(node=>node.classList.toggle('active',node.dataset.financeView===view));document.querySelectorAll('[data-finance-adjustment-tab]').forEach(node=>{const active=node.dataset.financeAdjustmentTab===state.financeAdjustmentSubpage;node.classList.toggle('active',active);node.setAttribute('aria-selected',String(active));});$('financeManagementPanel').hidden=!state.financeResource;$('financeMethodologyCard').hidden=view==='financeOverview'||view==='financeExpenseTypes';updateFinanceResourceChrome();loadFinanceConfig();}
function financeQueryParams(includePagination=true){const params=financeFilterQuery();if(includePagination){params.set('page',state.financePage);params.set('page_size',state.financePageSize);}return params;}
function financeToolbarActionMarkup(){
  const resource=state.financeResource,page=financeViewPage(),items=[];
  const exportable=['shop-budgets','adjustments','marketing-budget-history','recharges','promotion-spend','expense-types'].includes(resource);
  if(exportable)items.push('<button class="button" type="button" data-finance-toolbar-export><svg><use href="#i-upload"/></svg>导出</button>');
  if(resource==='shop-budgets'&&financeCanAction('promotion_total'))items.push(`<button class="button finance-total-manage-action" id="setPromotionTotalBudget" type="button" data-permission="${financeConsoleActions.promotion_total}" data-page-permission="${financePagePermissions.financePromotion}" data-finance-total="promotion-total"><svg><use href="#i-task"/></svg>设置/调整总预算</button>`);
  if(resource==='expense-types'&&financeCanAction('expense_type'))items.push(`<button class="button primary finance-panel-add" type="button" data-permission="${financeConsoleActions.expense_type}" data-page-permission="${financePagePermissions.financeExpenseTypes}" data-finance-add><svg><use href="#i-plus"/></svg>新增费用类型</button>`);
  return items.join('');
}
function financeViewPage(){return state.financeView||'';}
function updateFinanceResourceChrome(){const resource=state.financeResource,meta=financeConsoleResourceMeta[resource];if(!resource||!meta){$('financeManagementPanel').hidden=true;return;}const shopResource=['gsv-targets','shop-budgets','recharges','promotion-spend'].includes(resource),historyResource=['adjustments','marketing-budget-history'].includes(resource),dateFilterResource=['adjustments','marketing-budget-history','marketing-expenses'].includes(resource);$('financePlatformField').hidden=!shopResource;$('financeCompanyField').hidden=!shopResource;$('financeShopField').hidden=!shopResource;$('financeExpenseTypeField').hidden=resource!=='marketing-expenses';$('financeOperatorField').hidden=!historyResource;$('financeDateField').hidden=!dateFilterResource;$('financeDateField').querySelector('.finance-filter-label').textContent=resource==='marketing-expenses'?'费用日期':'操作时间';$('financeStatusField').hidden=resource!=='expense-types';$('financeKeywordField').hidden=false;$('financeKeyword').placeholder=resource==='marketing-expenses'?'搜索费用类型、合作方或单据号':resource==='expense-types'?'搜索费用类型或说明':historyResource?'搜索备注或审批信息':'搜索平台、公司、店铺';$('financeToolbarActions').innerHTML=financeToolbarActionMarkup();renderFinanceFilterLabels();renderFinanceMethodology();}
 function filteredFinanceSummaryShops(){
  const filters=state.financeFilters||{},keyword=($('financeKeyword')?.value||'').trim().toLowerCase();
  return (state.financeSummary?.shops||[]).filter(row=>{
    const text=[row.platform_name,row.company_name,row.shop_name,row.platform_code,row.company_code,row.shop_code].filter(Boolean).join(' ').toLowerCase();
    return (!filters.platform.length||filters.platform.includes(row.platform_code))
      &&(!filters.company.length||filters.company.includes(row.company_code))
      &&(!filters.shop.length||filters.shop.includes(row.shop_code))
      &&(!keyword||text.includes(keyword));
  });
}
async function loadFinanceConfig(){const page=$('financeBudgetPage');page?.classList.add('is-loading');try{const summaryParams=new URLSearchParams();if(financeConsoleMonth())summaryParams.set('budget_month',financeConsoleMonth());const summary=await api(`/api/ingest/finance-config/summary?${summaryParams}`);state.financeSummary=summary||{global:{},shops:[],actuals:{},alerts:[]};syncFinanceFilterSelections();renderFinanceFilterLabels();renderFinanceOverview(state.financeSummary);renderFinanceViewSummaries(state.financeSummary);if(!state.financeResource)return;const data=await api(`/api/ingest/finance-config/${state.financeResource}?${financeQueryParams()}`);state.financeItems=data.items||[];state.financeOperatorOptions=(data.operators||[]).map(item=>typeof item==='string'?item:item.value||item.label||'').filter(Boolean);if(state.financeResource==='expense-types'){state.financeExpenseTypes=data.items||[];state.financeExpenseTypesLoaded=true;}renderFinanceFilterLabels();renderFinanceConsoleTable();renderFinanceConsolePagination(data.pagination);}catch(error){toast(error.message,true);if(state.financeResource&&$('financeConfigBody'))$('financeConfigBody').innerHTML='<tr><td colspan="12" class="empty-row">经营配置加载失败，请稍后重试</td></tr>';}finally{page?.classList.remove('is-loading');}}

function renderFinanceRechargeHistory(data){
  const items=data?.items||[],pagination=data?.pagination||{},total=Number(pagination.total||0),size=Number(pagination.page_size||state.financeRechargeHistoryPageSize),current=Number(pagination.page||state.financeRechargeHistoryPage),pages=Math.max(1,Math.ceil(total/size));
  $('financeRechargeHistoryTotal').textContent=`共 ${total} 条`;
  $('financeRechargeHistoryBody').innerHTML=items.length?items.map(item=>`<tr><td>${day(item.recharge_date)}</td><td><strong class="finance-number green">${money(item.recharge_amount)}</strong></td><td>${esc(item.document_no||'—')}</td><td class="wrap"><span class="finance-history-note" title="${esc(item.remark||'')}">${esc(item.remark||'—')}</span></td><td>${esc(item.created_by||item.updated_by||'—')}</td><td>${fmt(item.updated_at||item.created_at)}</td></tr>`).join(''):'<tr><td colspan="6" class="empty-row">该店铺暂无历史充值记录</td></tr>';
  state.financeRechargeHistoryPage=current;
  renderPagination('financeRechargeHistoryPageNumbers','financeRechargeHistoryPrevPage','financeRechargeHistoryNextPage','financeRechargeHistoryPageInfo','financeRechargeHistoryPageSize',current,pages,total,page=>{state.financeRechargeHistoryPage=page;loadFinanceRechargeHistory();});
}
async function loadFinanceRechargeHistory(){
  const shopCode=state.financeRechargeHistoryShopCode;if(!shopCode)return;
  const requestId=++state.financeRechargeHistoryRequestId;
  try{
    const params=new URLSearchParams({console:'false',shop_code:shopCode,page:String(state.financeRechargeHistoryPage),page_size:String(state.financeRechargeHistoryPageSize)});
    const data=await api(`/api/ingest/finance-config/recharges?${params}`);
    if(requestId!==state.financeRechargeHistoryRequestId||!$('financeRechargeHistoryDialog')?.open)return;
    renderFinanceRechargeHistory(data);
  }catch(error){
    if(requestId!==state.financeRechargeHistoryRequestId||!$('financeRechargeHistoryDialog')?.open)return;
    $('financeRechargeHistoryBody').innerHTML=`<tr><td colspan="6" class="empty-row error-text">历史充值记录加载失败：${esc(error.message)}</td></tr>`;
  }
}
function openFinanceRechargeHistory(item={}){
  const shopCode=String(item.shop_code||'').trim();if(!shopCode)return toast('当前店铺缺少标准店铺编码，无法读取历史记录',true);
  state.financeRechargeHistoryShopCode=shopCode;state.financeRechargeHistoryPage=1;
  $('financeRechargeHistoryTitle').textContent=`${item.shop_name||'店铺'} · 历史充值记录`;
  $('financeRechargeHistoryMeta').textContent=[item.platform_name,item.company_name,shopCode].filter(Boolean).join(' · ');
  $('financeRechargeHistoryBody').innerHTML='<tr><td colspan="6" class="empty-row">正在加载历史充值记录…</td></tr>';
  $('financeRechargeHistoryTotal').textContent='读取中…';
  $('financeRechargeHistoryDialog').showModal();
  loadFinanceRechargeHistory();
}

function renderFinanceConsoleTable(){
  const resource=state.financeResource,items=state.financeItems||[],columns=financeConsoleColumns(resource),readOnly=['promotion-spend','adjustments','marketing-budget-history'].includes(resource);$('financeConfigHead').innerHTML=columns.map(column=>`<th>${esc(column[1])}</th>`).join('')+(readOnly?'':'<th>操作</th>');
  $('financeConfigBody').innerHTML=items.length?items.map((item,index)=>{let action='';if(resource==='gsv-targets')action=financeActionButton('gsv_detail',item.target_is_set?'调整目标':'分配目标',`data-finance-index="${index}"`);else if(resource==='shop-budgets')action=financeActionButton('shop_budget',item.budget_is_set?'调整分配':'分配预算',`data-finance-index="${index}"`);else if(resource==='recharges'){const history=financeCanPage('financeRecharges')?`<button type="button" class="icon-action" data-page-permission="${financePagePermissions.financeRecharges}" data-finance-history-index="${index}"><svg><use href="#i-search"/></svg><span>历史记录</span></button>`:'';action=history+financeActionButton('promotion_recharge','登记充值',`data-finance-index="${index}"`);}else if(resource==='marketing-expenses')action=financeActionButton('marketing_expense','编辑',`data-finance-index="${index}"`);else if(resource==='expense-types'&&financeCanAction('expense_type'))action=`<button type="button" class="icon-action" data-permission="${financeConsoleActions.expense_type}" data-page-permission="${financePagePermissions.financeExpenseTypes}" data-finance-type-edit="${index}"><svg><use href="#i-edit"/></svg><span>编辑</span></button><button type="button" class="icon-action ${item.is_active?'warning':'primary'}" data-permission="${financeConsoleActions.expense_type}" data-page-permission="${financePagePermissions.financeExpenseTypes}" data-finance-type-toggle="${index}"><svg><use href="#i-power"/></svg><span>${item.is_active?'停用':'启用'}</span></button>`;return `<tr>${columns.map(column=>`<td class="wrap">${column[2]?column[2](item[column[0]],item):esc(item[column[0]]??'—')}</td>`).join('')}${readOnly?'':`<td><div class="row-actions">${action||'—'}</div></td>`}</tr>`;}).join(''):`<tr><td colspan="${columns.length+(readOnly?0:1)}" class="empty-row"><div class="finance-table-empty"><svg><use href="#i-file-sheet"/></svg><strong>当前DIM或筛选条件下暂无数据</strong><small>未设置的店铺仍会显示在全量列表中</small></div></td></tr>`;
}
function renderFinanceConsolePagination(pagination){const total=Number(pagination?.total||0),size=Number(pagination?.page_size||state.financePageSize),current=Number(pagination?.page||1),pages=Math.max(1,Math.ceil(total/size));$('financeConfigTotal').textContent=`共 ${total} 条`;renderPagination('financeConfigPageNumbers','financeConfigPrevPage','financeConfigNextPage','financeConfigPageInfo','financeConfigPageSize',current,pages,total,page=>{state.financePage=page;loadFinanceConfig();});}
function renderFinanceViewSummaries(summary){
  const global=summary.global||{},actuals=summary.actuals||{},shops=summary.shops||[],gsvRate=financeRate(actuals.gsv_completion_rate),promotionRate=financeRate(actuals.promotion_execution_rate),marketingRate=financeRate(actuals.marketing_execution_rate);
  if($('financeGsvStats'))$('financeGsvStats').innerHTML=[['财务月度总GSV目标',global.gsv_target_amount,'blue'],['店铺目标合计',actuals.shop_gsv_target_amount,'purple'],['实际GSV累计',actuals.actual_gsv_amount,'green'],['总目标完成率',gsvRate,'orange','percent']].map(([label,value,tone,type])=>financeStatCard(label,value,tone,type)).join('');
  if($('financePromotionFlow'))$('financePromotionFlow').innerHTML=[['推广总预算',global.effective_promotion_budget_amount,'n1'],['已分配',global.allocated_promotion_budget_amount,'n2'],['累计充值',global.recharge_amount,'n3'],['实际消耗',actuals.promotion_expense_amount,'n4']].map(([label,value,tone],index)=>{const amount=compactFinanceAmount(value);return `<div class="finance-promotion-flow-node ${tone}"><i>${index+1}</i><small>${label}</small><strong>${amount.value}<em>${amount.unit}</em></strong></div>${index<3?'<svg><use href="#i-right"/></svg>':''}`;}).join('');
  if($('financePromotionStats'))$('financePromotionStats').innerHTML=[['总预算',global.effective_promotion_budget_amount,'blue'],['已分配',global.allocated_promotion_budget_amount,'purple'],['待分配',global.unallocated_promotion_budget_amount,'orange'],['累计充值',global.recharge_amount,'green'],['理论余额',actuals.theoretical_account_balance,'green'],['执行率',promotionRate,'orange','percent']].map(([label,value,tone,type])=>financeStatCard(label,value,tone,type)).join('');
  if($('financeMarketingStats'))$('financeMarketingStats').innerHTML=[['当月营销预算',global.marketing_budget_amount,'blue','money-edit'],['营销费用累计',global.marketing_expense_amount,'orange'],['剩余营销预算',global.marketing_remaining_amount,Number(global.marketing_remaining_amount)<0?'red':'green'],['预算执行率',marketingRate,marketingRate>100?'red':'purple','percent']].map(([label,value,tone,type])=>financeMarketingCard(label,value,tone,type)).join('');
  if($('financeMarketingProgressCopy'))$('financeMarketingProgressCopy').textContent=`已执行 ${financePercent(marketingRate)} · 剩余 ¥${money(global.marketing_remaining_amount)}`;
  if($('financeMarketingProgressBar'))$('financeMarketingProgressBar').innerHTML=financeProgress(marketingRate,marketingRate>100?'orange':'blue',true);requestAnimationFrame(animateFinanceProgress);
}
function financeRouteButton(page,label,attrs=''){return financeCanPage(page)?`<button class="text-button" type="button" data-permission="${financePagePermissions[page]}" data-finance-route="${page}" ${attrs}>${label} <svg><use href="#i-right"/></svg></button>`:'';}
function renderFinanceOverview(summary){
  const item=summary.global||{},actuals=summary.actuals||{},gsv=compactFinanceAmount(actuals.actual_gsv_amount),target=compactFinanceAmount(actuals.gsv_target_amount),spend=compactFinanceAmount(actuals.promotion_expense_amount),budget=compactFinanceAmount(item.effective_promotion_budget_amount),marketingSpend=compactFinanceAmount(item.marketing_expense_amount),marketingBudget=compactFinanceAmount(item.marketing_budget_amount),gsvRate=financeRate(actuals.gsv_completion_rate),promotionRate=financeRate(actuals.promotion_execution_rate),marketingRate=financeRate(actuals.marketing_execution_rate);
  const cards=[['blue','GSV目标完成率',financePercent(gsvRate),`实际 ${gsv.value}${gsv.unit} / 目标 ${target.value}${target.unit}`,financePercent(gsvRate)],['orange','推广预算执行率',financePercent(promotionRate),`已消耗 ${spend.value}${spend.unit} / 有效预算 ${budget.value}${budget.unit}`,promotionRate>100?'超预算':'执行中'],['green','营销预算执行率',financePercent(marketingRate),`已支出 ${marketingSpend.value}${marketingSpend.unit} / 预算 ${marketingBudget.value}${marketingBudget.unit}`,marketingRate>100?'超预算':'正常'],['red','预算预警',String(actuals.alert_count||0),'项预算风险',Number(actuals.alert_count||0)>0?'需关注':'正常']];
  $('financeSummaryCards').innerHTML=cards.map(card=>`<article class="panel finance-kpi-card ${card[0]}"><div class="finance-kpi-label">${esc(card[1])}</div><div class="finance-kpi-value"><strong>${esc(card[2])}</strong><span></span><em class="finance-kpi-badge ${card[0]}">${esc(card[4])}</em></div><p>${esc(card[3])}</p></article>`).join('');
  const flow=[['财务总预算',item.effective_promotion_budget_amount,'blue'],['店铺分配',item.allocated_promotion_budget_amount,'blue'],['累计充值',item.recharge_amount,'green'],['实际消耗',actuals.promotion_expense_amount,'purple']];
  $('financeExecutionCards').innerHTML=`<article class="panel finance-metric-card"><div class="finance-card-head"><div><h3>GSV目标完成</h3><p>实际销售额与财务目标对比</p></div>${financeRouteButton('financeGsv','查看详情')}</div><div class="finance-metric-stats stacked"><span><small>月度目标</small><strong>${money(actuals.gsv_target_amount)}</strong></span><span><small>实际累计</small><strong class="purple">${money(actuals.actual_gsv_amount)}</strong></span><span><small>完成率</small><strong class="purple">${financePercent(gsvRate)}</strong></span></div>${financeProgress(gsvRate,'purple',false)}</article><article class="panel finance-metric-card promotion-card"><div class="finance-card-head"><div><h3>推广预算执行</h3><p>总预算、分配、充值、消耗与余额</p></div>${financeRouteButton('financePromotion','查看详情')}</div><div class="finance-flow">${flow.map((step,index)=>`<div class="finance-flow-step ${step[2]}"><i>${index+1}</i><small>${step[0]}</small><strong>${compactFinanceAmount(step[1]).value}<em>${compactFinanceAmount(step[1]).unit}</em></strong></div>`).join('<svg class="finance-flow-arrow"><use href="#i-right"/></svg>')}</div><div class="finance-budget-facts"><span><small>待分配额度</small><strong class="orange">${money(item.unallocated_promotion_budget_amount)}</strong></span><span><small>待充值额度</small><strong class="orange">${money(item.pending_recharge_amount)}</strong></span><span><small>理论余额</small><strong class="green">${money(actuals.theoretical_account_balance)}</strong></span><span><small>执行率</small><strong class="purple">${financePercent(promotionRate)}</strong></span></div></article><article class="panel finance-metric-card"><div class="finance-card-head"><div><h3>营销预算执行</h3><p>整体预算，不按店铺拆分</p></div>${financeRouteButton('financeMarketing','查看详情')}</div><div class="finance-metric-stats stacked"><span><small>月度营销预算</small><strong>${money(item.marketing_budget_amount)}</strong></span><span><small>已支出营销费用</small><strong class="orange">${money(item.marketing_expense_amount)}</strong></span><span><small>剩余预算</small><strong class="green">${money(item.marketing_remaining_amount)}</strong></span></div>${financeProgress(marketingRate,'orange',false)}</article>`;
  const alerts=summary.alerts||[];$('financeAlertList').innerHTML=alerts.length?alerts.slice(0,5).map(alert=>{const route=alert.resource==='gsv-targets'?'financeGsv':alert.resource==='recharges'?'financeRecharges':'financePromotion';return financeCanPage(route)?`<button type="button" class="finance-alert-item ${esc(alert.level||'warning')}" data-permission="${financePagePermissions[route]}" data-finance-route="${route}"><span class="finance-alert-dot"></span><span><strong>${esc(alert.title||'预算提醒')}</strong><small>${esc(alert.description||'请查看经营配置明细')}</small></span><svg><use href="#i-right"/></svg></button>`:'';}).join('')||'<div class="finance-alert-empty"><span><svg><use href="#i-check-circle"/></svg></span><strong>本月暂无可查看的预算预警</strong></div>':'<div class="finance-alert-empty"><span><svg><use href="#i-check-circle"/></svg></span><strong>本月暂无预算预警</strong><small>预算、充值与目标进度均在正常范围内</small></div>';
   const quick=[];if(financeCanPage('financeGsv')&&financeCanAction('gsv_total'))quick.push(`<button type="button" data-permission="${financeConsoleActions.gsv_total}" data-page-permission="${financePagePermissions.financeGsv}" data-finance-total="gsv-total" data-finance-route="financeGsv"><span class="quick-action-icon purple"><svg><use href="#i-task"/></svg></span><span><strong>设置总 GSV 目标</strong><small>进入 GSV 目标管理</small></span><svg class="quick-arrow"><use href="#i-right"/></svg></button>`);if(financeCanPage('financePromotion')&&financeCanAction('promotion_total'))quick.push(`<button type="button" data-permission="${financeConsoleActions.promotion_total}" data-page-permission="${financePagePermissions.financePromotion}" data-finance-total="promotion-total" data-finance-route="financePromotion"><span class="quick-action-icon blue"><svg><use href="#i-branch"/></svg></span><span><strong>设置/调整推广总预算</strong><small>进入推广预算管理</small></span><svg class="quick-arrow"><use href="#i-right"/></svg></button>`);if(financeCanPage('financeMarketing')&&financeCanAction('marketing_budget'))quick.push(`<button type="button" data-permission="${financeConsoleActions.marketing_budget}" data-page-permission="${financePagePermissions.financeMarketing}" data-finance-total="marketing-budget" data-finance-route="financeMarketing"><span class="quick-action-icon orange"><svg><use href="#i-tags"/></svg></span><span><strong>设置/调整营销预算</strong><small>进入营销预算管理</small></span><svg class="quick-arrow"><use href="#i-right"/></svg></button>`);document.querySelector('.finance-quick-actions').innerHTML=quick.join('')||'<div class="finance-alert-empty"><strong>暂无可执行的快捷操作</strong></div>';requestAnimationFrame(animateFinanceProgress);
}
function renderFinanceMethodology(){const content=$('financeMethodologyContent');if(!content)return;const items=state.financeView==='financeGsv'?['<strong>店铺列表：</strong>直接来自所选月份DIM中的全部有效店铺，未设置目标显示“未设置”。','<strong>财务月度总目标：</strong>财务月度总GSV独立维护，不会被店铺目标合计覆盖。','<strong>实际GSV：</strong>来自订单指标ADS，完成率允许超过100%。']:state.financeView==='financePromotion'||state.financeView==='financeRecharges'||state.financeView==='financeSpend'?['<strong>有效推广预算：</strong>首次设置为初始预算，之后每次修改按前后金额自动生成调整历史。','<strong>待充值：</strong>店铺分配预算 - 店铺累计充值；负数表示超预算充值。','<strong>理论余额：</strong>累计充值 - 实际推广消耗。','<strong>DIM口径：</strong>平台、公司、店铺只来自有效DIM关系，历史月份按当时有效关系展示。']:state.financeView==='financeAdjustments'?['<strong>推广预算调整：</strong>推广总预算后续每次修改均独立记录前后金额、差额、时间、操作人和备注。','<strong>营销预算调整：</strong>营销总预算后续每次修改均独立记录前后金额、差额、时间、操作人和备注。']:['<strong>营销预算：</strong>整体月度粒度，首次设置备注可为空，后续修改必须备注并保留历史。','<strong>营销费用：</strong>只能登记费用类型管理中启用的类型。'];$('financeMethodologyContent').innerHTML=items.map(item=>`<div>• ${item}</div>`).join('');}
function configureFinanceDialog(item={},options={}){closeFinanceAssignDropdown();const resource=options.resource||state.financeResource,mode=options.mode||financeConsoleResourceMeta[resource]?.mode||resource,id=item[financePk[resource]||financePk['shop-plans']]||item.shop_plan_id||item.recharge_id||item.marketing_expense_id||'';state.financeDialogMode=mode;$('financeConfigForm').dataset.resource=resource;$('financeConfigForm').dataset.editId=id||'';$('financeConfigForm').dataset.action=mode==='gsv'?'gsv_detail':mode==='promotion-allocation'?'shop_budget':mode==='recharges'?'promotion_recharge':mode==='marketing-expenses'?'marketing_expense':mode==='gsv-total'?'gsv_total':mode==='promotion-total'?'promotion_total':mode==='marketing-budget'?'marketing_budget':'';const fields={gsv:['budget_month','platform_context','company_context','shop_code','gsv_target_amount','remark'],'gsv-total':['budget_month','gsv_target_amount','remark'],'promotion-total':['budget_month','promotion_budget_amount','remark'],'promotion-allocation':['budget_month','platform_context','company_context','shop_code','promotion_budget_amount','remark'],recharges:['business_date','platform_context','company_context','shop_code','amount','document_no','remark'],'marketing-expenses':['business_date','amount','expense_type','counterparty','document_no','remark'],'marketing-budget':['budget_month','marketing_budget_amount','remark']};document.querySelectorAll('[data-finance-field]').forEach(node=>node.hidden=!(fields[mode]||[]).includes(node.dataset.financeField));$('financeConfigDialogTitle').textContent=mode==='gsv'?(item.target_is_set?'调整店铺GSV目标':'分配店铺GSV目标'):mode==='promotion-allocation'?(item.budget_is_set?'调整店铺预算分配':'分配店铺预算'):mode==='recharges'?'登记推广充值':mode==='gsv-total'?'设置财务月度总GSV目标':mode==='promotion-total'?'设置/调整推广总预算':mode==='marketing-budget'?'设置/调整营销预算':'登记营销费用';$('financeDialogDescription').textContent=financeConsoleResourceMeta[resource]?.description||'保存后即时刷新经营配置指标。';$('financeDialogSubmit').textContent='保存';$('financeDialogNotice').hidden=true;$('financeConfigDialog').classList.toggle('small',['gsv','gsv-total','promotion-total','marketing-budget'].includes(mode));const month=day(item.budget_month)==='—'?(financeConsoleMonth().slice(0,7)||currentMonthValue()):day(item.budget_month).slice(0,7);$('financeFormBudgetMonth').value=month;$('financeFormBusinessDate').value=day(item.recharge_date||item.expense_date)==='—'?currentDateValue():day(item.recharge_date||item.expense_date);$('financeFormPromotionBudget').value=item.promotion_budget_amount??'';$('financeFormMarketingBudget').value=item.marketing_budget_amount??state.financeSummary?.global?.marketing_budget_amount??0;$('financeFormGsvTarget').value=item.gsv_target_amount??'';$('financeFormAmount').value=item.recharge_amount??item.expense_amount??'';$('financeFormPlatform').value=item.platform_code||'';$('financeFormCompany').value=item.company_code||'';$('financeFormShopCode').value=item.shop_code||'';$('financeFormPlatformText').textContent=item.platform_name||'—';$('financeFormCompanyText').textContent=item.company_name||'—';$('financeFormShopText').textContent=item.shop_name||'—';$('financeShopContext').textContent=item.shop_code?`DIM有效关系：${item.platform_name||''} · ${item.company_name||''} · ${item.shop_name||''}`:'请从DIM店铺行进入操作';$('financeFormCounterparty').value=item.counterparty||'';$('financeFormDocumentNo').value=item.document_no||'';$('financeFormRemark').value=item.remark||'';$('financeFormUpdatedAt').value=item.updated_at||'';$('financeFormExpenseType').value='';$('financeFormExpenseTypeLabel').textContent='请选择费用类型';if(item.expense_type){const type=state.financeExpenseTypes.find(row=>row.expense_type_name===item.expense_type||row.expense_type_code===item.expense_type);$('financeFormExpenseType').value=type?.expense_type_code||item.expense_type;$('financeFormExpenseTypeLabel').textContent=type?.expense_type_name||item.expense_type;}$('financeConfigDialog').showModal();}
async function saveFinanceConfig(event){event.preventDefault();const form=$('financeConfigForm'),resource=form.dataset.resource,id=form.dataset.editId||'',action=form.dataset.action||'',mode=state.financeDialogMode;if(!action)return;if(['gsv','promotion-allocation','recharges'].includes(mode)&&!$('financeFormShopCode').value)return toast('当前操作缺少DIM店铺上下文，请从店铺行进入',true);if(mode==='marketing-expenses'&&!$('financeFormExpenseType').value)return toast('请选择启用中的营销费用类型',true);const payload={permission_action:action,updated_at:$('financeFormUpdatedAt').value||null,budget_month:$('financeFormBudgetMonth').value?`${$('financeFormBudgetMonth').value}-01`:null,platform_code:$('financeFormPlatform').value,company_code:$('financeFormCompany').value,shop_code:$('financeFormShopCode').value,promotion_budget_amount:$('financeFormPromotionBudget').value||0,marketing_budget_amount:$('financeFormMarketingBudget').value||0,gsv_target_amount:$('financeFormGsvTarget').value||0,expense_type:$('financeFormExpenseType').value,counterparty:$('financeFormCounterparty').value,document_no:$('financeFormDocumentNo').value,remark:$('financeFormRemark').value};if(mode==='recharges'){payload.recharge_date=$('financeFormBusinessDate').value;payload.recharge_amount=$('financeFormAmount').value;}if(mode==='marketing-expenses'){payload.expense_date=$('financeFormBusinessDate').value;payload.expense_amount=$('financeFormAmount').value;}try{await api(`/api/ingest/finance-config/${resource}${id?`/${encodeURIComponent(id)}`:''}`,{method:id?'PUT':'POST',body:JSON.stringify(payload)});$('financeConfigDialog').close();toast(id?'经营配置已更新':'经营配置已保存');await loadFinanceConfig();}catch(error){toast(error.message,true);}}
function openFinanceExpenseTypeDialog(item=null){$('financeExpenseTypeDialogTitle').textContent=item?'编辑营销费用类型':'新增营销费用类型';$('financeExpenseTypeForm').dataset.editId=item?.expense_type_id||'';$('financeExpenseTypeName').value=item?.expense_type_name||'';$('financeExpenseTypeActive').checked=Boolean(item?.is_active??true);$('financeExpenseTypeRemark').value=item?.remark||'';$('financeExpenseTypeId').value=item?.expense_type_id||'';$('financeExpenseTypeUpdatedAt').value=item?.updated_at||'';$('financeExpenseTypeDialog').showModal();}
async function saveFinanceExpenseType(event){event.preventDefault();const form=$('financeExpenseTypeForm'),id=form.dataset.editId||'',payload={expense_type_name:$('financeExpenseTypeName').value,is_active:$('financeExpenseTypeActive').checked,remark:$('financeExpenseTypeRemark').value,updated_at:$('financeExpenseTypeUpdatedAt').value||null};try{await api(`/api/ingest/finance-config/expense-types${id?`/${id}`:''}`,{method:id?'PUT':'POST',body:JSON.stringify(payload)});$('financeExpenseTypeDialog').close();toast(id?'费用类型已更新':'费用类型已创建');await loadFinanceConfig();}catch(error){toast(error.message,true);}}
async function toggleFinanceExpenseType(index){const item=state.financeItems[index];if(!item)return;try{await api(`/api/ingest/finance-config/expense-types/${item.expense_type_id}`,{method:'PUT',body:JSON.stringify({expense_type_name:item.expense_type_name,is_active:!item.is_active,remark:item.remark,updated_at:item.updated_at})});toast(item.is_active?'费用类型已停用':'费用类型已启用');await loadFinanceConfig();}catch(error){toast(error.message,true);}}
async function deleteFinanceExpenseType(index){const item=state.financeItems[index];if(!item||!confirm(`确认删除费用类型“${item.expense_type_name}”吗？历史营销费用流水会保留原名称。`))return;try{await api(`/api/ingest/finance-config/expense-types/${item.expense_type_id}`,{method:'DELETE'});toast('费用类型已删除');await loadFinanceConfig();}catch(error){toast(error.message,true);}}
async function exportFinanceConfig(){try{const params=financeQueryParams(false);params.set('page','1');params.set('page_size','5000');const data=state.financeResource==='expense-types'?await api('/api/ingest/finance-config/expense-types?page=1&page_size=5000'):await api(`/api/ingest/finance-config/${state.financeResource}?${params}`),items=data.items||[],columns=financeConsoleColumns(state.financeResource),headers=columns.map(column=>column[1]),rows=items.map(item=>columns.map(column=>String(item[column[0]]??''))),csv=[headers,...rows].map(row=>row.map(value=>`"${value.replaceAll('"','""')}"`).join(',')).join('\r\n'),link=document.createElement('a');link.href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));link.download=`${financeConsoleResourceMeta[state.financeResource]?.title||'经营配置'}_${financeConsoleMonth().slice(0,7)||'全部'}.csv`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000);toast('当前明细已导出');}catch(error){toast(error.message,true);}}
// Legacy finance toolbar binding removed; bindFinanceConsole is the single active implementation.
// Legacy finance toolbar body removed.

function bindFinanceConsole(){
  $('financeConfigDialog').addEventListener('close',closeFinanceAssignDropdown);
  $('financeRechargeHistoryDialog').addEventListener('close',()=>{state.financeRechargeHistoryRequestId+=1;});
  document.querySelectorAll('[data-finance-adjustment-tab]').forEach(tab=>{tab.onclick=()=>setFinanceAdjustmentSubpage(tab.dataset.financeAdjustmentTab);});
  document.querySelectorAll('[data-finance-filter]').forEach(trigger=>{trigger.onclick=event=>{event.stopPropagation();openFinanceAssignDropdown(trigger);};});
  $('financeExpenseTypeTrigger').onclick=event=>{event.stopPropagation();openFinanceAssignDropdown(event.currentTarget);};
  $('financeAssignSearch').oninput=event=>renderFinanceAssignOptions(event.target.value);
  $('financeAssignSearch').onkeydown=event=>{if(event.key==='Enter')event.preventDefault();if(event.key==='Escape')closeFinanceAssignDropdown();};
  $('financeAssignOptions').onclick=event=>{const option=event.target.closest('[data-finance-option]');if(!option||!state.financeDropdown)return;const id=option.dataset.financeOption;if(state.financeDropdown.kind==='form_expense'){state.financeDropdown.selected=[id];applyFinanceDropdownSelection();return;}const selected=state.financeDropdown.selected;state.financeDropdown.selected=selected.includes(id)?selected.filter(value=>value!==id):[...selected,id];renderFinanceAssignOptions($('financeAssignSearch').value);};
  $('financeAssignConfirm').onclick=applyFinanceDropdownSelection;$('financeAssignCancel').onclick=closeFinanceAssignDropdown;$('financeAssignDropdown').onclick=event=>event.stopPropagation();
  $('financeMonth').onchange=()=>{state.financePage=1;loadFinanceConfig();};
  $('financeKeyword').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();state.financePage=1;loadFinanceConfig();}};
  $('searchFinanceConfig').onclick=()=>{state.financePage=1;loadFinanceConfig();};
  $('resetFinanceConfig').onclick=()=>{state.financeFilters={platform:[],company:[],shop:[],expense_type:[],finance_operator:[]};$('financeKeyword').value='';$('financeStatus').value='';closeDateRange();clearDateRange('financeDateFrom','financeDateTo');renderFinanceFilterLabels();state.financePage=1;loadFinanceConfig();};
  $('financeConfigForm').onsubmit=saveFinanceConfig;$('financeExpenseTypeForm').onsubmit=saveFinanceExpenseType;
  $('financeConfigBody').onclick=event=>{const history=event.target.closest('[data-finance-history-index]');if(history){openFinanceRechargeHistory(state.financeItems[Number(history.dataset.financeHistoryIndex)]);return;}const action=event.target.closest('[data-finance-action]');if(action){const item=state.financeItems[Number(action.dataset.financeIndex)];if(item)configureFinanceDialog(item,{resource:state.financeResource,mode:financeConsoleResourceMeta[state.financeResource]?.mode});return;}const edit=event.target.closest('[data-finance-type-edit]');if(edit)openFinanceExpenseTypeDialog(state.financeItems[Number(edit.dataset.financeTypeEdit)]);const toggle=event.target.closest('[data-finance-type-toggle]');if(toggle)toggleFinanceExpenseType(Number(toggle.dataset.financeTypeToggle));};
  $('financeToolbarActions').onclick=event=>{const add=event.target.closest('[data-finance-add]');if(add){openFinanceExpenseTypeDialog();return;}const exportButton=event.target.closest('[data-finance-toolbar-export]');if(exportButton)exportFinanceConfig();};
  $('addMarketingExpense').onclick=()=>configureFinanceDialog({}, {resource:'marketing-expenses',mode:'marketing-expenses'});
  $('financeBudgetPage').onclick=event=>{const route=event.target.closest('[data-finance-route]');if(route){switchPage(route.dataset.financeRoute);return;}const marketingBudget=event.target.closest('[data-edit-marketing-budget]');if(marketingBudget){configureFinanceDialog(state.financeSummary?.global||{},{resource:'budgets',mode:'marketing-budget'});return;}const total=event.target.closest('[data-finance-total]');if(total){const mode=total.dataset.financeTotal;configureFinanceDialog(state.financeSummary?.global||{},{resource:'budgets',mode});}};
  document.querySelectorAll('[data-finance-export]').forEach(button=>button.onclick=exportFinanceConfig);
  document.addEventListener('click',event=>{if(state.financeDropdown&&!event.target.closest('#financeAssignDropdown')&&!event.target.closest('[data-finance-filter]')&&!event.target.closest('#financeExpenseTypeTrigger'))closeFinanceAssignDropdown();});
  window.addEventListener('resize',closeFinanceAssignDropdown);
}

 const financeConfigureFinanceDialogBase=configureFinanceDialog;
configureFinanceDialog=function(item={},options={}){
  financeConfigureFinanceDialogBase(item,options);
  if((options.mode||financeConsoleResourceMeta[options.resource||state.financeResource]?.mode)==='recharges'&&!item?.recharge_id)$('financeFormAmount').value='';
  if(!item?.expense_type)return;
  const type=state.financeExpenseTypes.find(row=>row.expense_type_name===item.expense_type||row.expense_type_code===item.expense_type);
  if(!type?.is_active){$('financeFormExpenseType').value='';$('financeFormExpenseTypeLabel').textContent='原费用类型已停用，请选择启用类型';}
};

const financeContextDialogBase=configureFinanceDialog;
configureFinanceDialog=function(item={},options={}){
  financeContextDialogBase(item,options);
  const mode=options.mode||financeConsoleResourceMeta[options.resource||state.financeResource]?.mode;
  const hiddenFields=mode==='gsv'||mode==='promotion-allocation'
    ?['budget_month','platform_context','company_context','shop_code']
    :mode==='recharges'?['platform_context','company_context','shop_code']:[];
  hiddenFields.forEach(field=>document.querySelectorAll(`[data-finance-field="${field}"]`).forEach(node=>{node.hidden=true;}));
};

const financeConsoleTableBase=renderFinanceConsoleTable;
renderFinanceConsoleTable=function(){
  financeConsoleTableBase();
  if(state.financeResource!=='expense-types'||!financeCanAction('expense_type'))return;
  (state.financeItems||[]).forEach((item,index)=>{
    const row=$('financeConfigBody')?.rows[index];
    const toggle=row?.querySelector('[data-finance-type-toggle]');
    toggle?.classList.toggle('success',!item.is_active);
    toggle?.classList.remove('primary');
    const actions=row?.querySelector('.row-actions');
    if(actions&&!actions.querySelector('[data-finance-type-delete]'))actions.insertAdjacentHTML('beforeend',`<button type="button" class="icon-action danger" data-permission="${financeConsoleActions.expense_type}" data-page-permission="${financePagePermissions.financeExpenseTypes}" data-finance-type-delete="${index}"><svg><use href="#i-trash"/></svg><span>删除</span></button>`);
  });
};

const financeOverviewBase=renderFinanceOverview;
renderFinanceOverview=function(summary){
  financeOverviewBase(summary);
  const quickCopy={'gsv-total':'直接设置本月总 GSV 目标','promotion-total':'直接设置/调整推广总预算','marketing-budget':'直接设置/调整营销总预算'};
  document.querySelectorAll('.finance-quick-actions [data-finance-total]').forEach(button=>{
    button.removeAttribute('data-finance-route');
    const copy=quickCopy[button.dataset.financeTotal];
    if(copy)button.querySelector('small')?.replaceChildren(copy);
  });
};

/* ── Shared pagination renderer ── */
function getPageNumbers(current,total,maxVisible=5){if(total<=1)return [1];if(total<=maxVisible)return Array.from({length:total},(_,i)=>i+1);let start=Math.max(1,current-Math.floor(maxVisible/2));let end=start+maxVisible-1;if(end>total){end=total;start=Math.max(1,end-maxVisible+1);}return Array.from({length:end-start+1},(_,i)=>start+i);}
function renderPagination(pageNumId,prevId,nextId,pageInfoId,pageSizeId,current,pages,total,onChange){
  const pageNumbers=$(pageNumId);if(!pageNumbers)return;
  $(pageInfoId).textContent=`第 ${current}/${pages} 页`;
  $(prevId).disabled=current<=1;$(nextId).disabled=current>=pages;
  $(prevId).onclick=()=>{if(current>1)onChange(current-1)};
  $(nextId).onclick=()=>{if(current<pages)onChange(current+1)};
  if(pageSizeId&&$(pageSizeId))$(pageSizeId).onchange=e=>{const size=Number(e.target.value);if(pageSizeId==='feePageSize')state.feePageSize=size;if(pageSizeId==='categoryPageSize')state.categoryPageSize=size;if(pageSizeId==='rawFeePageSize')state.rawFeePageSize=size;if(pageSizeId==='runPageSize')state.runPageSize=size;if(pageSizeId==='etlPageSize')state.etlPageSize=size;if(pageSizeId==='logPageSize')state.logPageSize=size;if(pageSizeId==='financeConfigPageSize')state.financePageSize=size;if(pageSizeId==='financeRechargeHistoryPageSize')state.financeRechargeHistoryPageSize=size;onChange(1);};
  const pages_arr=getPageNumbers(current,pages);
  pageNumbers.innerHTML=pages_arr.map(page=>`<button class="pagination-page-btn ${page===current?'is-active':''}" type="button" data-page="${page}" aria-label="第 ${page} 页" ${page===current?'aria-current="page"':''}>${page}</button>`).join('');
  pageNumbers.querySelectorAll('.pagination-page-btn').forEach(btn=>btn.onclick=()=>onChange(Number(btn.dataset.page)));
}

async function init(){
  document.querySelectorAll('.nav-item[data-page]').forEach(node=>node.onclick=()=>switchPage(node.dataset.page));
  window.addEventListener('hashchange',()=>switchPage(location.hash.slice(1)));
  $('fileInput').onchange=e=>addFiles(e.target.files);
  $('fileBody').onclick=e=>{
    const errorToggle=e.target.closest('[data-error-toggle]');if(errorToggle){e.stopPropagation();toggleErrorDisclosure(errorToggle);return;}
    const copy=e.target.closest('[data-copy-message]');if(copy){e.stopPropagation();void copyMessage(copy.dataset.copyMessage,copy.dataset.copyKind==='warning'?'警告信息已复制':'错误信息已复制');return;}
    const select=e.target.closest('[data-cell-select]');if(select){const item=state.files.find(x=>x.id===select.dataset.itemId);if(item)openCellDropdown(select,item,select.dataset.cellSelect);return;}
    const reset=e.target.closest('[data-reset]');if(reset){resetFileParameters(reset.dataset.reset);return;}
    const remove=e.target.closest('[data-remove]');if(remove){removeFile(remove.dataset.remove);return;}
    const resume=e.target.closest('[data-continue-file]');if(resume){const item=state.files.find(file=>file.id===resume.dataset.continueFile);if(item)void continueUploadedFile(item);return;}
    const submit=e.target.closest('[data-submit-one]');if(submit){const item=state.files.find(x=>x.id===submit.dataset.submitOne);if(item)submitItems([item]);}
  };
  $('fileBody').onchange=e=>{if(e.target.dataset.billDate){const item=state.files.find(file=>file.id===e.target.dataset.billDate);if(item){item.billDate=e.target.value;void persistPendingFile(item);}return;}const id=e.target.dataset.fileCheck;if(!id)return;e.target.checked?state.selectedFiles.add(id):state.selectedFiles.delete(id);renderFiles();const item=state.files.find(file=>file.id===id);if(item)void persistPendingFile(item);};
  $('uploadFileList').onclick=e=>{const button=e.target.closest('[data-upload-remove]');if(button)removeFile(button.dataset.uploadRemove);};
  $('selectAllFiles').onchange=e=>{const eligible=state.files.filter(item=>!isSubmitted(item));state.selectedFiles=new Set(e.target.checked?eligible.map(item=>item.id):[]);renderFiles();void Promise.all(eligible.map(item=>persistPendingFile(item)));};
  $('cellDropdownSearch').oninput=e=>renderDropdownOptions(e.target.value);$('cellDropdownSearch').onkeydown=e=>{if(e.key==='Escape')closeCellDropdown();};
  $('cellDropdownOptions').onclick=e=>{const option=e.target.closest('[data-option-value]');if(option&&state.dropdown)applyFieldSelection(state.dropdown.item,state.dropdown.field,option.dataset.optionValue);};
  $('cellDropdown').onclick=e=>e.stopPropagation();document.addEventListener('click',e=>{if(!e.target.closest('[data-cell-select]')&&!e.target.closest('#cellDropdown'))closeCellDropdown();});window.addEventListener('resize',closeCellDropdown);
  ['dragenter','dragover'].forEach(name=>$('dropZone').addEventListener(name,e=>{e.preventDefault();$('dropZone').classList.add('dragging')}));['dragleave','drop'].forEach(name=>$('dropZone').addEventListener(name,e=>{e.preventDefault();$('dropZone').classList.remove('dragging')}));$('dropZone').ondrop=e=>addFiles(e.dataTransfer.files);
  $('submitFiles').onclick=submitFiles;$('refreshPage').onclick=()=>switchPage(state.currentPage);
  $('openRecalculation').onclick=()=>switchPage('runs');
  $('runBody').onclick=e=>{const recalculate=e.target.closest('[data-recalculate-run]');if(recalculate){e.stopPropagation();void recalculateRun(recalculate.dataset.recalculateRun);return;}const view=e.target.closest('[data-run-detail]');if(view){e.stopPropagation();void showRunDetail(view.dataset.runDetail);return;}const complete=e.target.closest('[data-complete-run]');if(complete){e.stopPropagation();void completeRun(complete.dataset.completeRun);return;}const remove=e.target.closest('[data-delete-run]');if(remove){e.stopPropagation();void deleteRun(remove.dataset.deleteRun);return;}const row=e.target.closest('[data-run-id]');if(!row)return;void showRunDetail(row.dataset.runId);};
  $('runDateField').onchange=event=>{state.runFilters.date_field=event.target.value;state.runPage=1;loadRuns();};$('runStatus').onchange=event=>{state.runFilters.status=event.target.value?[event.target.value]:[];};$('searchRuns').onclick=()=>{state.runFilters.keyword=$('runKeyword').value.trim();state.runPage=1;loadRuns();};$('resetRuns').onclick=()=>{state.runFilters={operator:[],status:[],keyword:'',date_field:'created_at'};$('runDateField').value='created_at';$('runStatus').value='';$('runKeyword').value='';closeDateRange();clearDateRange('runDateFrom','runDateTo');renderPickerLabel('run_operator','runOperator','runOperatorLabel');state.runPage=1;loadRuns();};$('runKeyword').onkeydown=event=>{if(event.key==='Enter')$('searchRuns').click();};
  $('etlDateField').onchange=event=>{state.etlFilters.date_field=event.target.value;state.etlPage=1;loadEtls();};$('etlStatus').onchange=event=>{state.etlFilters.status=event.target.value?[event.target.value]:[];};$('searchEtls').onclick=()=>{state.etlFilters.keyword=$('etlKeyword').value.trim();state.etlPage=1;loadEtls();};$('resetEtls').onclick=()=>{state.etlFilters={operator:[],status:[],keyword:'',date_field:'started_at'};$('etlDateField').value='started_at';$('etlStatus').value='';$('etlKeyword').value='';closeDateRange();clearDateRange('etlDateFrom','etlDateTo');renderPickerLabel('etl_operator','etlOperator','etlOperatorLabel');state.etlPage=1;loadEtls();};$('etlKeyword').onkeydown=event=>{if(event.key==='Enter')$('searchEtls').click();};
  $('etlBody').onclick=e=>{const button=e.target.closest('[data-etl-detail]');if(button){e.stopPropagation();void showEtlDetail(button.dataset.etlDetail);}};
  $('etlTaskBody').onclick=e=>{const copy=e.target.closest('[data-copy-message]');if(copy){e.stopPropagation();void copyMessage(copy.dataset.copyMessage,copy.dataset.copyKind==='warning'?'警告信息已复制':'错误信息已复制');return;}const button=e.target.closest('[data-retry-etl-task]');if(button)retryEtlTask(button.dataset.retryEtlTask);};
  $('ingestFileDetailBody').onclick=e=>{const copy=e.target.closest('[data-copy-message]');if(copy){e.stopPropagation();void copyMessage(copy.dataset.copyMessage,copy.dataset.copyKind==='warning'?'警告信息已复制':'错误信息已复制');return;}const button=e.target.closest('[data-retry-ingest-file]');if(button)retryIngestFile(button.dataset.retryIngestFile,button.dataset.retryIngestRun);};
  $('searchFees').onclick=()=>{state.feePage=1;loadFees()};
  $('resetFees').onclick=()=>{$('feePlatform').value='';$('feeDocument').value='';$('feeStatus').value='';$('feeTreatment').value='';$('feeKeyword').value='';state.feePage=1;loadFees();};
  $('exportFees').onclick=exportFees;$('batchMapFees').onclick=toggleFeeBatchMode;
  $('feeBody').onclick=e=>{const trigger=e.target.closest('[data-assign-trigger]');if(trigger){openAssignDropdown(trigger);return}const editFee=e.target.closest('[data-edit-fee]');if(editFee){openFeeMappingDialog(Number(editFee.dataset.editFee));return}const delFee=e.target.closest('[data-delete-fee]');if(delFee){deleteFeeMapping(Number(delFee.dataset.deleteFee));return}const toggle=e.target.closest('[data-toggle-map]');if(toggle){toggleFee(Number(toggle.dataset.toggleMap));return}const row=e.target.closest('tr[data-fee-index]');if(row&&state.feeBatchMode&&!e.target.closest('button,input,select,textarea,a,.row-actions,.assign-combobox')){const i=Number(row.dataset.feeIndex);state.selectedFees.has(i)?state.selectedFees.delete(i):state.selectedFees.add(i);renderFees();}};
  $('feeBody').onchange=e=>{if(e.target.dataset.feeIndex!==undefined){const i=Number(e.target.dataset.feeIndex);e.target.checked?state.selectedFees.add(i):state.selectedFees.delete(i);renderFees()}};
  $('selectAllFees').onchange=e=>{if(!state.feeBatchMode)return;state.selectedFees=new Set(e.target.checked?state.feeItems.map((_,i)=>i):[]);renderFees()};
  $('assignSearch').oninput=e=>renderAssignOptions(e.target.value);
  $('assignSearch').onkeydown=e=>{if(e.key==='Escape')closeAssignDropdown();};
  $('assignDropdown').onclick=e=>e.stopPropagation();
  document.addEventListener('click',e=>{if(state.assignContext&&!e.target.closest('#assignDropdown')&&!e.target.closest('[data-assign-trigger]')&&!e.target.closest('#feeMappingCategoryTrigger'))closeAssignDropdown();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeAssignDropdown();hideTablePopover();closeDateRange();}});
  document.addEventListener('click',e=>{if(state.dateRangeContext&&!e.target.closest('#dateRangeDropdown')&&!e.target.closest('.date-range-trigger'))closeDateRange();});
  window.addEventListener('resize',()=>{closeAssignDropdown();hideTablePopover();closeDateRange();});
  $('addCategory').onclick=()=>openCategoryDialog();$('categoryForm').onsubmit=saveCategory;$('feeMappingForm').onsubmit=saveFeeMapping;$('feeMappingCategoryTrigger').onclick=()=>openAssignDropdown($('feeMappingCategoryTrigger'));
  $('searchCategories').onclick=()=>{state.categoryPage=1;loadCategoryPage();};$('resetCategories').onclick=()=>{$('categoryPlatform').value='';$('categoryStatus').value='';$('categoryKeyword').value='';state.categoryPage=1;loadCategoryPage();};
  $('categoryBody').onclick=e=>{const edit=e.target.closest('[data-edit-category]');if(edit){openCategoryDialog(state.feeCategories[Number(edit.dataset.editCategory)]);return;}const toggleCat=e.target.closest('[data-toggle-category]');if(toggleCat){toggleCategoryStatus(Number(toggleCat.dataset.toggleCategory));return;}const delCat=e.target.closest('[data-delete-category]');if(delCat){deleteCategory(Number(delCat.dataset.deleteCategory));return;}const view=e.target.closest('[data-view-category-mappings]');if(view)viewCategoryMappings(state.feeCategories[Number(view.dataset.viewCategoryMappings)]);};
  $('searchRawFees').onclick=()=>{state.rawFeePage=1;loadRawFees();};$('resetRawFees').onclick=()=>{$('rawPlatform').value='';$('rawDocument').value='';$('rawStatus').value='';$('rawTreatment').value='';closeDateRange();clearDateRange('rawDateFrom','rawDateTo');$('rawKeyword').value='';state.rawFeePage=1;loadRawFees();};$('exportRawFees').onclick=exportRawFees;
  $('searchLogs').onclick=()=>{state.logPage=1;loadLogs();};$('resetLogs').onclick=()=>{closeDateRange();clearDateRange('logDateFrom','logDateTo');$('logType').value='';state.logOperatorSelections=[];renderPickerLabel('log_operator','logOperator','logOperatorLabel');$('logKeyword').value='';state.logPage=1;loadLogs();};$('logKeyword').onkeydown=e=>{if(e.key==='Enter'){state.logPage=1;loadLogs();}};
  try{const saved=JSON.parse(localStorage.getItem('ingest_upload_coverage')||'null');if(saved){$('uploadImportMode').value=saved.mode==='replace_range'?'replace_range':'fill_gaps';$('uploadCoverageStart').value=saved.start||'';$('uploadCoverageEnd').value=saved.end||'';$('uploadCompleteExport').checked=saved.complete_export===true;}}catch(_error){/* 忽略损坏的本地表单偏好。 */}
  $('uploadImportMode').onchange=saveUploadSettings;$('uploadCompleteExport').onchange=saveUploadSettings;
  document.querySelector('[data-date-range="uploadCoverageStart,uploadCoverageEnd"]').onchange=saveUploadSettings;
  saveUploadSettings();
  document.querySelectorAll('[data-date-range]').forEach(control=>{syncDateRange(control);const trigger=control.querySelector('.date-range-trigger');if(trigger){trigger.onmousedown=e=>e.stopPropagation();trigger.onclick=e=>{e.stopPropagation();openDateRange(control);};}});
  $('dateRangeDropdown').onclick=e=>e.stopPropagation();
  bindFinanceConsole();
  $('financeConfigBody').addEventListener('click',event=>{const remove=event.target.closest('[data-finance-type-delete]');if(remove)deleteFinanceExpenseType(Number(remove.dataset.financeTypeDelete));});
  $('importGsvTargets').onclick=()=>$('financeBatchFile').click();$('financeBatchFile').onchange=e=>importGsvTargets(e.target.files?.[0]);
  document.querySelectorAll('[data-close-dialog]').forEach(button=>button.onclick=()=>closeDetailDialog(button.dataset.closeDialog));
  $('feeMappingDialog').addEventListener('close',closeAssignDropdown);
  DETAIL_DIALOG_IDS.forEach(dialogId=>$(dialogId)?.addEventListener('cancel',()=>invalidateDetailRequest(dialogId)));
  window.addEventListener('health:change',event=>applySharedHealth(event.detail));if(window.appHealthState)applySharedHealth(window.appHealthState);
  $('financeMonth').value=currentMonthValue();bindNativePicker($('financeMonth'));bindNativePicker($('financeFormBudgetMonth'));bindNativePicker($('financeFormBusinessDate'));
  try{const [reports,shops]=await Promise.all([api('/api/ingest/report-types'),api('/api/ingest/shops')]);state.reports=reports.items;state.shops=shops.items;platformOptions();renderFinanceFilterLabels();updateFinanceResourceChrome();loadCategories();try{await ensureFinanceExpenseTypes();}catch(_error){/* 没有费用类型查看权限时不影响其它经营配置页面；打开登记弹窗时会再次尝试加载 */}}catch(e){toast(e.message,true)}
  await restorePendingFiles();
  await syncUploadedFiles();
  renderFiles();switchPage(location.hash.slice(1)||'upload');
  setInterval(()=>{if(state.currentPage==='runs')loadRuns();if(state.currentPage==='etl')loadEtls();if(state.currentPage==='logs')loadLogs();if(state.currentPage==='upload')void syncUploadedFiles();},5000);
  window.addEventListener('online',()=>void syncUploadedFiles());window.addEventListener('focus',()=>void syncUploadedFiles());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void syncUploadedFiles();});
}
init();

// Explicit impact preview and visible source evidence.
let operatingPreviewAction=null,sourceReviewRule=null;
async function previewOperatingChange(payload,apply){
  const data=await api('/api/ingest/fee-mappings/preview',{method:'POST',body:JSON.stringify(payload)});
  $('operatingPreviewScope').textContent=data.scope_note;
  $('operatingPreviewTotals').textContent=`${data.rule_count} 条规则，涉及 ${data.source_rows} 条来源；收入变化 ${money(data.income_delta)} 元，费用变化 ${money(data.expense_delta)} 元。`;
  $('operatingPreviewRows').innerHTML=data.items.length?data.items.map(r=>`<tr><td>${esc(r.stat_month)} / ${esc(r.shop_name)}</td><td>${money(r.income_delta)}</td><td>${money(r.expense_delta)}</td></tr>`).join(''):'<tr><td colspan="3">当前没有已发布金额；新增来源将在重算后体现。</td></tr>';
  payload.preview_token=data.preview_token;operatingPreviewAction=()=>apply(data.preview_token);$('operatingPreviewDialog').showModal();
}
async function showFeeSource(index){
  try{const item=state.feeItems[index],data=await api(`/api/ingest/fee-mappings/${item.mapping_id}/source`),r=data.rule,e=data.evidence;sourceReviewRule=r;
    $('feeSourceContent').innerHTML=`<p><strong>${esc(r.secondary_category_name)}</strong></p><p>来源用途：${esc(r.source_usage_label)}</p><p>${esc(r.source_usage_note)}</p><p>经营归属：${esc(operatingLabel(r.operating_treatment))}（${esc(r.treatment_origin_label)}）；系统建议：${esc(operatingLabel(r.suggested_operating_treatment))}</p><p>此归属${r.treatment_editable?'可以在配置表直接修改':'受已统计来源保护；更正来源关系后才能重新计入'}。</p><p>可核对来源 ${e.source_rows} 条，关联主来源 ${e.matched_rows} 条，缺少共同身份 ${e.missing_identity_rows} 条。</p>${e.identity_note?`<p>${esc(e.identity_note)}</p>`:''}${e.samples?.length?`<ul>${e.samples.map(s=>`<li>批次 ${esc(s.batch_id)} / 来源行 ${esc(s.source_id)} / 订单 ${esc(s.order_no)}</li>`).join('')}</ul>`:''}<p class="muted">文件覆盖和原生流水身份防重始终保留。若已统计关联有误，先核实批次店铺、原始来源和匹配规则，再重新核对。</p>`;
    $('feeSourceCorrection').hidden=r.treatment_editable||!e.correction_available;$('feeSourceReason').value='';$('feeSourceDialog').showModal();
  }catch(e){toast(e.message,true);}
}
document.addEventListener('click',event=>{const source=event.target.closest('[data-source-fee]');if(source)showFeeSource(Number(source.dataset.sourceFee));const job=event.target.closest('[data-policy-etl]');if(job)showEtlDetail(job.dataset.policyEtl);});
document.addEventListener('DOMContentLoaded',()=>{
  $('newSceneRule').onclick=()=>editSceneRule();
  $('searchSceneRules').onclick=renderSceneRules;
  $('resetSceneRules').onclick=()=>{['sceneRuleFilterPlatform','sceneRuleFilterDocument','sceneRuleFilterActive','sceneRuleKeyword'].forEach(id=>$(id).value='');renderSceneRules();};
  $('sceneRuleKeyword').onkeydown=e=>{if(e.key==='Enter')renderSceneRules();};
  $('sceneRuleRows').onclick=event=>{const edit=event.target.closest('[data-edit-scene-rule]');if(edit)editSceneRule(sceneRules[Number(edit.dataset.editSceneRule)]);};
  $('previewSceneRule').onclick=previewSceneRule;$('sceneRuleForm').onsubmit=saveSceneRule;
  $('sceneRuleForm').oninput=()=>{sceneRuleProof=null;$('saveSceneRule').disabled=true;};
  $('applyOperatingPreview').onclick=async()=>{const b=$('applyOperatingPreview');try{b.disabled=true;await operatingPreviewAction();$('operatingPreviewDialog').close();}catch(e){toast(e.message,true);}finally{b.disabled=false;}};
  $('correctFeeSource').onclick=async()=>{const r=sourceReviewRule,reason=$('feeSourceReason').value.trim();if(reason.length<5){toast('请填写至少5字的独立业务依据',true);return;}const payload={items:[r],source_usage:'independent',source_correction_reason:reason};try{await previewOperatingChange(payload,async()=>{await api('/api/ingest/fee-mappings/assign',{method:'POST',body:JSON.stringify(payload)});$('feeSourceDialog').close();await loadFees();toast('来源判定已更正，等待重算生效');});}catch(e){toast(e.message,true);}};
});
