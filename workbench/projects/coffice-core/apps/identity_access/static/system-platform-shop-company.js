(function(){
  const A=window.SystemApp;
  let mappings=[],mappingPage=1,mappingPageSize=10;
  let filterRows=[],dropdown=null;
  const filters={platform:[],company:[],shop:[]};
  const filterNames={platform:'平台',company:'公司',shop:'店铺'};
  const filterIds={platform:'mappingPlatform',company:'mappingCompany',shop:'mappingShop'};
  const get=id=>document.getElementById(id);
  const dateOnly=value=>value?String(value).slice(0,10):'—';
  const isoDate=value=>{const date=new Date(value);return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`};
  const addDays=(value,days)=>{const date=new Date(`${dateOnly(value)}T00:00:00`);date.setDate(date.getDate()+days);return isoDate(date)};
  const nextVersionDate=item=>{const today=isoDate(new Date()),afterCurrent=addDays(item.valid_from,1);return afterCurrent>today?afterCurrent:today};
  const canManage=()=>Boolean(window.currentUser?.is_super_admin||window.currentPermissions?.has('system.platform_shop_company.manage'));
  const statusMeta={
    current:['当前有效','on'],future:['未来生效','future'],expired:['已过期','expired'],inactive:['已停用','inactive'],
  };
  const status=value=>{const meta=statusMeta[value]||[value||'未知',''];return `<span class="status-pill mapping-status ${meta[1]}">${A.esc(meta[0])}</span>`};
  const namedCode=(name,code)=>`<span class="mapping-name">${A.esc(name)}</span><small class="mapping-code">${A.esc(code)}</small>`;
  const mappingMessage='DIM映射已保存；请通过现有ETL刷新ADS和看板数据';

  function filterOptions(kind){
    let rows=filterRows;
    if(kind!=='platform'&&filters.platform.length)rows=rows.filter(row=>filters.platform.includes(row.platform_code));
    if(kind==='shop'&&filters.company.length)rows=rows.filter(row=>filters.company.includes(row.company_code));
    return [...new Map(rows.map(row=>[row[`${kind}_code`],{
      id:row[`${kind}_code`],label:row[`${kind}_name`],
      search:`${row[`${kind}_name`]} ${row[`${kind}_code`]} ${kind==='shop'?row.account_id||'':''}`,
    }])).values()].filter(item=>item.id);
  }

  function renderFilterLabels(){
    Object.keys(filters).forEach(kind=>{
      const values=filters[kind],options=filterOptions(kind),labels=values.map(id=>options.find(item=>item.id===id)?.label||id);
      get(filterIds[kind]).value=values.join(',');
      const label=get(filterIds[kind]+'Label');
      label.textContent=labels.length?(labels.length===1?labels[0]:`${labels[0]} 等 ${labels.length} 项`):`全部${filterNames[kind]}`;
      get(filterIds[kind]+'Trigger').title=labels.length?labels.join('、'):`全部${filterNames[kind]}`;
    });
  }

  function closeFilterDropdown(){
    dropdown?.trigger.setAttribute('aria-expanded','false');
    get('mappingFilterDropdown').hidden=true;dropdown=null;
  }

  function placeFilterDropdown(){
    if(!dropdown)return;
    const panel=get('mappingFilterDropdown'),rect=dropdown.trigger.getBoundingClientRect(),width=Math.min(320,window.innerWidth-16),height=panel.offsetHeight||360;
    panel.style.width=`${width}px`;
    panel.style.left=`${Math.max(8,Math.min(rect.left,window.innerWidth-width-8))}px`;
    panel.style.top=`${rect.bottom+6+height<=window.innerHeight-8?rect.bottom+6:Math.max(8,rect.top-height-6)}px`;
  }

  function renderFilterOptions(){
    if(!dropdown)return;
    const keyword=get('mappingFilterSearch').value.trim().toLowerCase(),items=dropdown.items.filter(item=>!keyword||item.search.toLowerCase().includes(keyword));
    get('mappingFilterOptions').innerHTML=items.length?items.map(item=>{
      const selected=dropdown.selected.includes(item.id);
      return `<button type="button" class="mapping-filter-option ${selected?'selected':''}" data-mapping-option="${A.esc(item.id)}" role="option" aria-selected="${selected}"><input type="checkbox" tabindex="-1" aria-hidden="true" ${selected?'checked':''}><span>${A.esc(item.label)}</span></button>`;
    }).join(''):'<div class="mapping-filter-empty">未找到匹配项，不会创建新数据</div>';
    get('mappingFilterSummary').textContent=dropdown.selected.length?`已选择 ${dropdown.selected.length} 项`:'未选择';
    placeFilterDropdown();
  }

  function openFilterDropdown(trigger){
    if(dropdown?.trigger===trigger){closeFilterDropdown();return;}
    closeFilterDropdown();
    const kind=trigger.dataset.mappingFilter;
    dropdown={trigger,kind,items:filterOptions(kind),selected:[...filters[kind]]};
    trigger.setAttribute('aria-expanded','true');get('mappingFilterSearch').value='';
    get('mappingFilterOptions').setAttribute('aria-label',`${filterNames[kind]}选项`);
    get('mappingFilterDropdown').hidden=false;renderFilterOptions();get('mappingFilterSearch').focus();
  }

  async function loadMappings(page=mappingPage,size=mappingPageSize){
    mappingPage=Math.max(1,page);mappingPageSize=size;
    const query=new URLSearchParams({
      keyword:get('mappingKeyword').value,
      platform_codes:filters.platform.join(','),
      company_codes:filters.company.join(','),
      shop_codes:filters.shop.join(','),
      status:get('mappingStatus').value,
      page:String(mappingPage),page_size:String(mappingPageSize),
    });
    const data=await A.api('/api/system/platform-shop-companies?'+query);
    mappings=data.items;
    filterRows=data.filter_options||[];renderFilterLabels();
    const manage=canManage();
    get('mappingRows').innerHTML=mappings.length?mappings.map(item=>{
      const canVersion=manage&&item.is_active&&item.valid_to===null;
      const canExpire=manage&&(item.mapping_status==='current'||item.mapping_status==='future');
      const actions=manage?`${A.action(`mapping-edit:${item.shop_company_sk}`,'编辑','edit')}${canVersion?A.action(`mapping-version:${item.shop_company_sk}`,'新增版本','copy') : ''}${canExpire?A.action(`mapping-expire:${item.shop_company_sk}`,'删除','trash','danger'):''}`:'—';
      return `<tr><td>${namedCode(item.platform_name,item.platform_code)}</td><td>${namedCode(item.company_name,item.company_code)}</td><td>${namedCode(item.shop_name,item.shop_code)}</td><td>${A.esc(item.shop_type)}</td><td><span class="mapping-account" title="${A.esc(item.account_id)}">${A.esc(item.account_id)}</span></td><td><span class="mapping-period">${dateOnly(item.valid_from)} 至 ${item.valid_to?dateOnly(item.valid_to):'长期'}</span></td><td>${status(item.mapping_status)}</td><td>${A.date(item.updated_at)}</td><td><div class="row-actions">${actions}</div></td></tr>`;
    }).join(''):'<tr><td colspan="9" class="empty">暂无平台店铺公司映射</td></tr>';
    const pages=Math.max(1,Math.ceil(data.total/mappingPageSize));
    if(!mappings.length&&mappingPage>1)return loadMappings(mappingPage-1,mappingPageSize);
    A.pagination('mapping',mappingPage,pages,data.total,(next,nextSize)=>loadMappings(next,nextSize));
  }

  function fullForm(item,version=false){
    const effective=version?nextVersionDate(item):isoDate(new Date());
    return `<div class="form-grid">
      <label>平台编码<input name="platform_code" maxlength="32" value="${A.esc(item?.platform_code||'')}" placeholder="例如 douyin 或自定义编码" required></label>
      <label>平台名称<input name="platform_name" maxlength="64" value="${A.esc(item?.platform_name||'')}" required></label>
      <label>公司编码<input name="company_code" maxlength="32" value="${A.esc(item?.company_code||'')}" required></label>
      <label>公司名称<input name="company_name" maxlength="255" value="${A.esc(item?.company_name||'')}" required></label>
      <label>店铺编码<input name="shop_code" maxlength="128" value="${A.esc(item?.shop_code||'')}" required></label>
      <label>店铺名称<input name="shop_name" maxlength="255" value="${A.esc(item?.shop_name||'')}" required></label>
      <label>店铺类型<input name="shop_type" maxlength="64" value="${A.esc(item?.shop_type||'')}" placeholder="旗舰店、专卖店等" required></label>
      <label>平台账号ID<input name="account_id" maxlength="128" value="${A.esc(item?.account_id||'')}" required></label>
      <label>生效日期<input name="valid_from" type="date" value="${A.esc(effective)}" required></label>
      <p class="form-help full">${version?'同一平台和店铺会自动截止上一版本；修改平台或店铺编码会建立新的店铺身份。':'平台编码允许自定义，但不会自动建立对应的指标ETL。'}</p>
    </div>`;
  }

  function metadataForm(item){
    return `<div class="mapping-context">${namedCode(item.platform_name,item.platform_code)}<span> / </span>${namedCode(item.shop_name,item.shop_code)}<span> / </span><small>${A.esc(item.company_code)}</small></div><div class="form-grid">
      <label>平台名称<input name="platform_name" maxlength="64" value="${A.esc(item.platform_name)}" required></label>
      <label>公司名称<input name="company_name" maxlength="255" value="${A.esc(item.company_name)}" required></label>
      <label>店铺名称<input name="shop_name" maxlength="255" value="${A.esc(item.shop_name)}" required></label>
      <label>店铺类型<input name="shop_type" maxlength="64" value="${A.esc(item.shop_type)}" required></label>
      <label class="full">平台账号ID<input name="account_id" maxlength="128" value="${A.esc(item.account_id)}" required></label>
      <p class="form-help full">编码、公司归属或生效日期变更请使用“新增版本”。</p>
    </div>`;
  }

  function openCreate(){
    A.modal('新增平台店铺公司映射',fullForm(null),async form=>{
      await A.api('/api/system/platform-shop-companies',{method:'POST',body:JSON.stringify(Object.fromEntries(form))});
      await loadMappings(1,mappingPageSize);return mappingMessage;
    });
  }

  function openEdit(item){
    A.modal('编辑映射描述信息',metadataForm(item),async form=>{
      await A.api(`/api/system/platform-shop-companies/${item.shop_company_sk}`,{method:'PUT',body:JSON.stringify(Object.fromEntries(form))});
      await loadMappings();return mappingMessage;
    });
  }

  function openVersion(item){
    A.modal('新增映射版本',fullForm(item,true),async form=>{
      const payload={...Object.fromEntries(form),create_version:true};
      await A.api(`/api/system/platform-shop-companies/${item.shop_company_sk}`,{method:'PUT',body:JSON.stringify(payload)});
      await loadMappings();return mappingMessage;
    });
  }

  get('mappingRows').onclick=async event=>{
    const button=event.target.closest('[data-action]');if(!button)return;
    const {scope,action,id}=A.parseAction(button.dataset.action);if(scope!=='mapping')return;
    const item=mappings.find(row=>row.shop_company_sk===Number(id));if(!item)return;
    try{
      if(action==='edit')openEdit(item);
      if(action==='version')openVersion(item);
      if(action==='expire'&&confirm(`确定删除“${item.platform_name} / ${item.shop_name} / ${item.company_name}”这条映射吗？`)){
        await A.api(`/api/system/platform-shop-companies/${item.shop_company_sk}`,{method:'DELETE'});
        await loadMappings();A.toast(mappingMessage);
      }
    }catch(error){A.toast(error.message,'error')}
  };
  get('addMapping').onclick=openCreate;
  get('searchMappings').onclick=()=>loadMappings(1,mappingPageSize);
  get('resetMappings').onclick=()=>{closeFilterDropdown();Object.keys(filters).forEach(kind=>filters[kind]=[]);get('mappingKeyword').value='';get('mappingStatus').value='current';renderFilterLabels();loadMappings(1,mappingPageSize)};
  get('mappingKeyword').addEventListener('keydown',event=>{if(event.key==='Enter')loadMappings(1,mappingPageSize)});
  document.querySelectorAll('[data-mapping-filter]').forEach(trigger=>trigger.onclick=()=>openFilterDropdown(trigger));
  get('mappingFilterSearch').oninput=renderFilterOptions;
  get('mappingFilterOptions').onclick=event=>{
    const option=event.target.closest('[data-mapping-option]');if(!option||!dropdown)return;
    const id=option.dataset.mappingOption;
    dropdown.selected=dropdown.selected.includes(id)?dropdown.selected.filter(value=>value!==id):[...dropdown.selected,id];renderFilterOptions();
  };
  get('mappingFilterConfirm').onclick=()=>{
    if(!dropdown)return;
    filters[dropdown.kind]=[...dropdown.selected];closeFilterDropdown();renderFilterLabels();loadMappings(1,mappingPageSize);
  };
  get('mappingFilterCancel').onclick=closeFilterDropdown;
  get('mappingFilterDropdown').onclick=event=>event.stopPropagation();
  document.addEventListener('click',event=>{if(dropdown&&!event.target.closest('#mappingFilterDropdown')&&!event.target.closest('[data-mapping-filter]'))closeFilterDropdown()});
  document.addEventListener('keydown',event=>{if(dropdown&&event.key==='Escape'){const trigger=dropdown.trigger;closeFilterDropdown();trigger.focus()}});
  window.addEventListener('resize',closeFilterDropdown);window.addEventListener('scroll',event=>{if(!get('mappingFilterDropdown').contains(event.target))closeFilterDropdown()},true);window.addEventListener('hashchange',closeFilterDropdown);
  get('mappingStatus').onchange=()=>loadMappings(1,mappingPageSize);
  Object.assign(A.pages,{platformShopCompany:loadMappings});
})();
