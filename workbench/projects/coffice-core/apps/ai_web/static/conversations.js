(function(){
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const api=async(url,options={})=>{const response=await fetch(url,{headers:{'Content-Type':'application/json'},...options});const result=await response.json();if(!response.ok)throw new Error(result.message||'请求失败');return result.data};
  const titleNode=()=>document.getElementById('activeConversationTitle');
  const clear=()=>{document.getElementById('messages').innerHTML='';document.getElementById('emptyState').hidden=false;titleNode().textContent='新对话'};

  window.aiConversations={
    current:null,
    items:[],
    async load({openFirst=false}={}){
      this.items=await api('/api/ai/conversations');
      if(this.current&&!this.items.some(item=>item.conversation_uuid===this.current))this.current=null;
      const root=document.getElementById('conversationList');
      root.innerHTML=this.items.length?this.items.map(item=>`<div class="conversation-item ${item.conversation_uuid===this.current?'active':''}" data-id="${item.conversation_uuid}"><button type="button" class="conversation-open" title="${esc(item.title)}"><b>${esc(item.title)}</b><small>${new Date(item.updated_at).toLocaleString()}</small></button><div class="conversation-actions"><button type="button" data-conversation-action="rename" title="重命名">✎</button><button type="button" data-conversation-action="delete" class="danger" title="删除">×</button></div></div>`).join(''):'<div class="empty-mini">暂无会话<br><small>点击上方按钮开始分析</small></div>';
      root.querySelectorAll('.conversation-open').forEach(button=>button.onclick=()=>this.open(button.closest('.conversation-item').dataset.id));
      root.querySelectorAll('[data-conversation-action]').forEach(button=>button.onclick=event=>{event.stopPropagation();const id=button.closest('.conversation-item').dataset.id;button.dataset.conversationAction==='rename'?this.rename(id):this.remove(id)});
      const active=this.items.find(item=>item.conversation_uuid===this.current);if(active)titleNode().textContent=active.title;
      if(openFirst&&!this.current&&this.items.length)await this.open(this.items[0].conversation_uuid);
      return this.items;
    },
    async create(){
      const created=await api('/api/ai/conversations',{method:'POST',body:'{}'});this.current=created.conversation_uuid;clear();await this.load();return this.current;
    },
    async open(id){
      this.current=id;const messages=await api(`/api/ai/messages?conversation_uuid=${encodeURIComponent(id)}`);window.aiMessages.render(messages);await this.load();document.getElementById('chatScroller').scrollTop=1e9;
    },
    async rename(id){
      const item=this.items.find(value=>value.conversation_uuid===id),row=document.querySelector(`.conversation-item[data-id="${id}"]`);if(!item||!row||row.querySelector('.conversation-rename'))return;
      const editor=document.createElement('form');editor.className='conversation-rename';editor.innerHTML=`<input maxlength="80" aria-label="新的会话名称" value="${esc(item.title)}"><button type="submit">保存</button><button type="button" data-cancel>取消</button>`;row.append(editor);row.classList.add('editing');const input=editor.querySelector('input');input.focus();input.select();editor.querySelector('[data-cancel]').onclick=()=>{editor.remove();row.classList.remove('editing')};editor.onsubmit=async event=>{event.preventDefault();try{await api(`/api/ai/conversations/${encodeURIComponent(id)}`,{method:'PUT',body:JSON.stringify({title:input.value})});await this.load();window.dispatchEvent(new CustomEvent('ai:toast',{detail:{message:'会话已重命名',type:'success'}}))}catch(error){window.dispatchEvent(new CustomEvent('ai:toast',{detail:{message:error.message,type:'error'}}))}};
    },
    async remove(id){
      const row=document.querySelector(`.conversation-item[data-id="${id}"]`);if(!row||row.querySelector('.conversation-delete-confirm'))return;const confirmBar=document.createElement('div');confirmBar.className='conversation-delete-confirm';confirmBar.innerHTML='<span>确认删除？</span><button type="button" data-confirm>删除</button><button type="button" data-cancel>取消</button>';row.append(confirmBar);row.classList.add('editing');confirmBar.querySelector('[data-cancel]').onclick=()=>{confirmBar.remove();row.classList.remove('editing')};confirmBar.querySelector('[data-confirm]').onclick=async()=>{try{await api(`/api/ai/conversations/${encodeURIComponent(id)}`,{method:'DELETE'});if(this.current===id)this.current=null;const items=await this.load();if(items.length)await this.open(items[0].conversation_uuid);else clear();window.dispatchEvent(new CustomEvent('ai:toast',{detail:{message:'会话已删除',type:'success'}}))}catch(error){window.dispatchEvent(new CustomEvent('ai:toast',{detail:{message:error.message,type:'error'}}))}};
    }
  };
})();
