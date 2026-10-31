(function(){
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function inline(value){return value.replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')}
  function markdown(value){
    const code=[];let safe=esc(value).replace(/```([^\n]*)\n?([\s\S]*?)```/g,(_,language,body)=>{const index=code.push(`<pre><div class="code-head"><span>${language||'代码'}</span><button type="button" data-copy-code>复制</button></div><code>${body.replace(/^\n|\n$/g,'')}</code></pre>`)-1;return `\n@@CODE${index}@@\n`});
    const lines=safe.split(/\r?\n/),blocks=[];
    for(let index=0;index<lines.length;){const line=lines[index];
      if(/^@@CODE\d+@@$/.test(line)){blocks.push(code[Number(line.match(/\d+/)[0])]);index++;continue}
      if(/^#{1,3} /.test(line)){const level=line.match(/^#+/)[0].length;blocks.push(`<h${level}>${inline(line.slice(level+1))}</h${level}>`);index++;continue}
      if(/^[-*] /.test(line)){const items=[];while(index<lines.length&&/^[-*] /.test(lines[index]))items.push(`<li>${inline(lines[index++].slice(2))}</li>`);blocks.push(`<ul>${items.join('')}</ul>`);continue}
      if(line.includes('|')&&index+1<lines.length&&/^\s*\|?\s*:?-+/.test(lines[index+1])){const headers=line.split('|').filter(Boolean),rows=[];index+=2;while(index<lines.length&&lines[index].includes('|'))rows.push(lines[index++].split('|').filter(Boolean));blocks.push(`<div class="markdown-table"><table><thead><tr>${headers.map(cell=>`<th>${inline(cell.trim())}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${inline(cell.trim())}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);continue}
      if(!line.trim()){index++;continue}const paragraph=[];while(index<lines.length&&lines[index].trim()&&!/^(@@CODE\d+@@|#{1,3} |[-*] )/.test(lines[index]))paragraph.push(lines[index++]);blocks.push(`<p>${inline(paragraph.join('<br>'))}</p>`);
    }return blocks.join('');
  }
  function bindCodeCopy(node){node.querySelectorAll('[data-copy-code]').forEach(button=>button.onclick=async()=>{await navigator.clipboard.writeText(button.closest('pre').querySelector('code').textContent);button.textContent='已复制';setTimeout(()=>button.textContent='复制',1200)})}
  function create(role,content,status){const node=document.createElement('article');node.className=`message ${role}`;node.innerHTML=`<div class="message-avatar">${role==='user'?'我':'AI'}</div><div class="message-column"><div class="message-role">${role==='user'?'你':'经营分析助手'}</div><div class="message-body"><div class="message-content ${status==='streaming'?'typing':''}">${markdown(content)}</div></div></div>`;document.getElementById('messages').append(node);document.getElementById('emptyState').hidden=true;bindCodeCopy(node);return node}
  function actions(node,items){let bar=node.querySelector('.message-actions');if(!bar){bar=document.createElement('div');bar.className='message-actions';node.querySelector('.message-column').append(bar)}bar.innerHTML=items.map(item=>`<button type="button" data-message-action="${item.action}">${item.label}</button>`).join('');items.forEach(item=>bar.querySelector(`[data-message-action="${item.action}"]`).onclick=item.handler)}
  window.aiMessages={
    render(items){const root=document.getElementById('messages');root.innerHTML='';items.forEach(item=>{const node=create(item.role,item.content,item.status);if(item.source_summary?.length)this.sources(node,item.source_summary);if(item.role==='assistant')actions(node,[{action:'copy',label:'复制回答',handler:()=>navigator.clipboard.writeText(item.content)}])});document.getElementById('emptyState').hidden=Boolean(items.length)},
    create,
    update(node,text,streaming=true){const content=node.querySelector('.message-content');content.classList.toggle('typing',streaming);content.innerHTML=markdown(text);bindCodeCopy(node)},
    actions,
    sources(node,items){const details=document.createElement('details');details.className='message-sources';details.innerHTML=`<summary>分析依据（${items.length}）</summary>${items.map(item=>`<div class="source-item" title="${esc((item.tables||[]).join(', '))}">${esc(item.source_code)} · ${esc((item.tables||[]).join(', '))} · ${esc(item.rows)} 行 · ${esc(item.elapsed_ms)} ms · SQL ${esc(item.sql_hash?.slice(0,12))}</div>`).join('')}`;node.querySelector('.message-body').append(details)}
  };
})();
