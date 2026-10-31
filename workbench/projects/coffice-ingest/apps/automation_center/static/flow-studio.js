(function(){
  'use strict';

  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const api=async(path,options={})=>{
    const response=await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    const body=await response.json();
    if(!response.ok)throw new Error(body.message||'请求失败');
    return body.data;
  };
  const toast=(message,type='success')=>window.showAppToast?window.showAppToast(message,type):alert(message);
  const uid=()=>('node_'+Date.now().toString(36)+Math.random().toString(36).slice(2,7));
  const categories={system:'系统与会话',browser:'浏览器',human:'人工协作',report:'报表业务',file:'文件处理',data:'数据与下游',ai:'AI',workflow:'流程容器'};
  const NODE_W=218,NODE_H=126,WORLD_W=4000,WORLD_H=2600;
  const SIDES=['top','right','bottom','left'];
  const state={
    components:[],flows:[],flow:null,nodes:[],edges:[],
    selectedNodes:new Set(),selectedEdges:new Set(),primaryNode:null,
    zoom:1,panX:60,panY:50,dirty:false,loaded:false,
    spaceDown:false,pointerAction:null,connection:null,
    previewVisible:true,runFlowId:null,runMode:'test',menu:null,
    latestRun:null,nodeRuntime:new Map(),runtimeTimer:null,runtimeTicker:null,activeTestRunId:null,
    history:[],historyIndex:-1,historyMuted:false
  };

  const def=code=>state.components.find(item=>item.code===code);
  const studioVisible=()=>{const page=$('flow-studioPage');return !!page&&page.offsetParent!==null};
  const isTyping=target=>target&&['INPUT','TEXTAREA','SELECT'].includes(target.tagName);
  const markDirty=()=>{state.dirty=true;$('flowSaveBtn')?.classList.add('primary')};
  function historySnapshot(){
    return JSON.stringify({
      nodes:state.nodes.map(node=>JSON.parse(JSON.stringify(node))),
      edges:state.edges.map(edge=>JSON.parse(JSON.stringify(edge)))
    });
  }
  function updateHistoryButtons(){
    if($('flowUndoBtn'))$('flowUndoBtn').disabled=state.historyIndex<=0;
    if($('flowRedoBtn'))$('flowRedoBtn').disabled=state.historyIndex<0||state.historyIndex>=state.history.length-1;
  }
  function resetHistory(){
    state.history=[historySnapshot()];state.historyIndex=0;updateHistoryButtons();
  }
  function commitHistory(){
    if(state.historyMuted)return;
    const snapshot=historySnapshot();
    if(state.history[state.historyIndex]===snapshot){updateHistoryButtons();return}
    state.history=state.history.slice(0,state.historyIndex+1);
    state.history.push(snapshot);
    if(state.history.length>80)state.history.shift();
    state.historyIndex=state.history.length-1;updateHistoryButtons();
  }
  function applyHistory(index){
    if(index<0||index>=state.history.length)return;
    const snapshot=JSON.parse(state.history[index]);
    state.historyMuted=true;
    state.nodes=(snapshot.nodes||[]).map(node=>({...node}));
    state.edges=normalizeEdges(snapshot.edges||[]);
    state.historyIndex=index;state.selectedNodes.clear();state.selectedEdges.clear();state.primaryNode=null;
    state.historyMuted=false;markDirty();render();updateHistoryButtons();
  }
  function undo(){if(state.historyIndex>0)applyHistory(state.historyIndex-1)}
  function redo(){if(state.historyIndex<state.history.length-1)applyHistory(state.historyIndex+1)}

  const edgeKey=edge=>[edge.source,edge.source_port||'right',edge.target,edge.target_port||'left'].join('|');
  const selectedNode=()=>state.primaryNode?state.nodes.find(node=>node.id===state.primaryNode):null;

  const runtimeLabels={queued:'排队',running:'运行中',success:'成功',success_with_warnings:'成功·提醒',no_data:'无数据',needs_human:'等待人工',failed:'失败',cancelled:'取消',skipped:'跳过'};
  const runtimeFor=node=>state.nodeRuntime.get(node.id)||null;
  const runtimeText=runtime=>{
    if(!runtime)return'';
    let duration='';
    if(runtime.duration_seconds!=null)duration=' · '+Number(runtime.duration_seconds).toFixed(1)+'s';
    else if(runtime.started_at&&['running','needs_human'].includes(runtime.status))duration=' · '+Math.max(0,(Date.now()-new Date(runtime.started_at).getTime())/1000).toFixed(1)+'s';
    return(runtimeLabels[runtime.status]||runtime.status||'—')+duration;
  };
  function stopRuntimeTimers(){
    if(state.runtimeTimer){clearTimeout(state.runtimeTimer);state.runtimeTimer=null}
    if(state.runtimeTicker){clearInterval(state.runtimeTicker);state.runtimeTicker=null}
  }
  function updateRuntimeClock(){
    state.nodes.forEach(node=>{
      const runtime=runtimeFor(node);
      if(!runtime||!['running','needs_human'].includes(runtime.status))return;
      const card=document.querySelector('.flow-node[data-node="'+CSS.escape(node.id)+'"]');
      const badge=card?.querySelector('.flow-runtime-badge');
      if(badge)badge.textContent=runtimeText(runtime);
    });
  }
  function startRuntimeTicker(){
    if(state.runtimeTicker)return;
    state.runtimeTicker=setInterval(()=>{
      if(!studioVisible()){stopRuntimeTimers();return}
      updateRuntimeClock();
    },200);
  }
  function clearRuntimeOverlay(){
    stopRuntimeTimers();state.activeTestRunId=null;state.latestRun=null;state.nodeRuntime=new Map();
    renderNodes();renderEdges();renderConsole();toast('运行状态已清除');
  }

  function parseVariables(){
    const field=$('flowVariables');
    if(!field)return state.flow?.definition?.variables||{};
    return JSON.parse(field.value||'{}');
  }

  function definition(){
    return{
      nodes:state.nodes.map(node=>({
        id:node.id,component_code:node.component_code,name:node.name,
        x:Math.round(node.x),y:Math.round(node.y),enabled:node.enabled!==false,
        timeout_seconds:Number(node.timeout_seconds||60),retry_count:Number(node.retry_count||0),
        on_error:node.on_error||'stop',condition:node.condition||'',config:node.config||{}
      })),
      edges:state.edges.map(edge=>({
        source:edge.source,target:edge.target,
        source_port:edge.source_port||'right',target_port:edge.target_port||'left',
        label:edge.label||''
      })),
      variables:parseVariables()
    };
  }

  function worldPoint(clientX,clientY){
    const rect=$('flowViewport').getBoundingClientRect();
    return{x:(clientX-rect.left-state.panX)/state.zoom,y:(clientY-rect.top-state.panY)/state.zoom};
  }
  function viewportPoint(clientX,clientY){
    const rect=$('flowViewport').getBoundingClientRect();
    return{x:clientX-rect.left,y:clientY-rect.top};
  }

  function portPoint(node,side){
    if(side==='top')return{x:node.x+NODE_W/2,y:node.y};
    if(side==='bottom')return{x:node.x+NODE_W/2,y:node.y+NODE_H};
    if(side==='left')return{x:node.x,y:node.y+NODE_H/2};
    return{x:node.x+NODE_W,y:node.y+NODE_H/2};
  }

  function nearestPort(node,point){
    let best=null;
    SIDES.forEach(side=>{
      const port=portPoint(node,side);
      const distance=Math.hypot(point.x-port.x,point.y-port.y);
      if(!best||distance<best.distance)best={side,point:port,distance};
    });
    return best;
  }

  function smoothCurve(a,b){
    const dx=b.x-a.x,dy=b.y-a.y;
    if(Math.abs(dx)>=Math.abs(dy)){
      const handle=Math.max(42,Math.min(220,Math.abs(dx)*0.48+Math.abs(dy)*0.08));
      const sign=dx>=0?1:-1;
      return 'M '+a.x+' '+a.y+' C '+(a.x+sign*handle)+' '+a.y+', '+(b.x-sign*handle)+' '+b.y+', '+b.x+' '+b.y;
    }
    const handle=Math.max(42,Math.min(220,Math.abs(dy)*0.48+Math.abs(dx)*0.08));
    const sign=dy>=0?1:-1;
    return 'M '+a.x+' '+a.y+' C '+a.x+' '+(a.y+sign*handle)+', '+b.x+' '+(b.y-sign*handle)+', '+b.x+' '+b.y;
  }

  function connectionSnapAt(clientX,clientY){
    const element=document.elementFromPoint(clientX,clientY);
    const nodeElement=element?.closest?.('.flow-node');
    if(!nodeElement)return null;
    const node=state.nodes.find(item=>item.id===nodeElement.dataset.node);
    if(!node||node.id===state.connection?.source)return null;
    const nearest=nearestPort(node,worldPoint(clientX,clientY));
    return nearest?{node,side:nearest.side,point:nearest.point}:null;
  }

  function clearSnapHighlight(){
    document.querySelectorAll('.flow-port.snap-target').forEach(port=>port.classList.remove('snap-target'));
  }

  function showSnapHighlight(snap){
    clearSnapHighlight();
    if(!snap)return;
    const element=document.querySelector('.flow-node[data-node="'+CSS.escape(snap.node.id)+'"] .flow-port.'+snap.side);
    element?.classList.add('snap-target');
  }
  function edgeVisualState(edge){
    const source=state.nodes.find(node=>node.id===edge.source);
    const target=state.nodes.find(node=>node.id===edge.target);
    const sourceRun=source?runtimeFor(source):null,targetRun=target?runtimeFor(target):null;
    const failed=new Set(['failed','cancelled']);
    const success=new Set(['success','success_with_warnings','no_data','skipped']);
    if(failed.has(targetRun?.status)||failed.has(sourceRun?.status))return'failed';
    if(success.has(targetRun?.status))return'success';
    if(success.has(sourceRun?.status)&&(['queued','running','needs_human'].includes(targetRun?.status)||!targetRun))return'running';
    if(targetRun?.status==='running'||targetRun?.status==='needs_human')return'running';
    return'idle';
  }
  function edgePath(edge){
    const source=state.nodes.find(node=>node.id===edge.source);
    const target=state.nodes.find(node=>node.id===edge.target);
    if(!source||!target)return'';
    const sp=portPoint(source,edge.source_port||'right');
    const tp=portPoint(target,edge.target_port||'left');
    return smoothCurve(sp,tp);
  }
  function connectionPath(){
    if(!state.connection)return'';
    const source=state.nodes.find(node=>node.id===state.connection.source);
    if(!source)return'';
    const sp=portPoint(source,state.connection.port);
    const tp=state.connection.snap?.point||state.connection.pointer||sp;
    return smoothCurve(sp,tp);
  }

  function setTransform(){
    const world=$('flowWorld');
    if(world)world.style.transform='translate('+state.panX+'px,'+state.panY+'px) scale('+state.zoom+')';
    if($('flowZoomLabel'))$('flowZoomLabel').textContent=Math.round(state.zoom*100)+'%';
    renderMinimap();
  }

  function renderEdges(){
    const svg=$('flowEdges');
    if(!svg)return;
    const parts=['<defs>'+
      '<marker id="flow-arrow-idle" viewBox="0 0 10 10" refX="8.2" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M 1 1 L 8 5 L 1 9 z" fill="#a3afbf"></path></marker>'+
      '<marker id="flow-arrow-running" viewBox="0 0 10 10" refX="8.2" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M 1 1 L 8 5 L 1 9 z" fill="#60a5fa"></path></marker>'+
      '<marker id="flow-arrow-success" viewBox="0 0 10 10" refX="8.2" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M 1 1 L 8 5 L 1 9 z" fill="#47a66a"></path></marker>'+
      '<marker id="flow-arrow-failed" viewBox="0 0 10 10" refX="8.2" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M 1 1 L 8 5 L 1 9 z" fill="#d85b5b"></path></marker>'+
      '</defs>'];
    state.edges.forEach(edge=>{
      const key=edgeKey(edge),path=edgePath(edge);
      if(!path)return;
      const selected=state.selectedEdges.has(key)?' selected':'';
      const visual=edgeVisualState(edge);
      parts.push('<g class="flow-edge-group '+visual+selected+'" data-edge-key="'+esc(key)+'"><path class="flow-edge-hit" d="'+path+'"></path><path class="flow-edge '+visual+selected+'" d="'+path+'" marker-end="url(#flow-arrow-'+visual+')"></path></g>');
    });
    if(state.connection){
      const preview=connectionPath();
      if(preview)parts.push('<path class="flow-edge-preview" d="'+preview+'"></path>');
    }
    svg.innerHTML=parts.join('');
    svg.querySelectorAll('.flow-edge-group').forEach(group=>{
      group.onpointerdown=event=>{
        if(event.button!==0)return;
        event.stopPropagation();
        selectEdge(group.dataset.edgeKey,event.shiftKey||event.ctrlKey||event.metaKey);
      };
      group.oncontextmenu=event=>{
        event.preventDefault();event.stopPropagation();
        selectEdge(group.dataset.edgeKey,false);
        showContextMenu(event.clientX,event.clientY,'edge');
      };
    });
  }

  function portMarkup(side){
    return '<span class="flow-port '+side+'" data-side="'+side+'" title="从这里拖拽到目标节点；箭头决定输入/输出方向"></span>';
  }

  function renderNodes(){
    const layer=$('flowNodes');
    if(!layer)return;
    layer.innerHTML=state.nodes.map(node=>{
      const component=def(node.component_code)||{category:'system',description:'自定义草稿组件'};
      const selected=state.selectedNodes.has(node.id)?' selected':'';
      const disabled=node.enabled===false?' disabled':'';
      const runtime=runtimeFor(node),runtimeClass=runtime?' runtime-'+String(runtime.status||'unknown').replace(/_/g,'-'):'';
      return '<article class="flow-node'+selected+disabled+runtimeClass+'" data-node="'+esc(node.id)+'" style="left:'+node.x+'px;top:'+node.y+'px">'+
        portMarkup('top')+portMarkup('right')+portMarkup('bottom')+portMarkup('left')+
        '<div class="flow-node-head"><div class="flow-node-icon">'+esc((component.category||'C').slice(0,3).toUpperCase())+'</div>'+
        '<div><strong>'+esc(node.name)+'</strong><small>'+esc(node.component_code)+'</small></div>'+
        '<button class="flow-node-menu" type="button" aria-label="节点菜单">•••</button></div>'+
        '<div class="flow-node-body">'+esc(component.description||'')+
        '<div class="flow-node-meta"><span>'+esc(node.timeout_seconds)+'s · retry '+esc(node.retry_count)+'</span><span>'+(runtime?'<b class="flow-runtime-badge">'+esc(runtimeText(runtime))+'</b>':(node.enabled===false?'禁用':'启用'))+'</span></div></div></article>';
    }).join('');

    layer.querySelectorAll('.flow-node').forEach(element=>{
      const id=element.dataset.node;
      element.onpointerdown=event=>{
        if(event.target.closest('.flow-port')||event.target.closest('.flow-node-menu'))return;
        if(event.button!==0||state.spaceDown)return;
        event.stopPropagation();
        const additive=event.shiftKey||event.ctrlKey||event.metaKey;
        if(!state.selectedNodes.has(id))selectNode(id,additive);
        else{state.primaryNode=id;renderInspector()}
        beginNodeDrag(event,id);
      };
      element.oncontextmenu=event=>{
        event.preventDefault();event.stopPropagation();
        if(!state.selectedNodes.has(id))selectNode(id,false);
        state.primaryNode=id;
        renderInspector();
        showContextMenu(event.clientX,event.clientY,'node');
      };
      element.querySelector('.flow-node-menu').onclick=event=>{
        event.stopPropagation();
        const rect=event.currentTarget.getBoundingClientRect();
        const anchorX=rect.right||event.clientX,anchorY=rect.bottom||event.clientY;
        if(!state.selectedNodes.has(id))selectNode(id,false);
        showContextMenu(anchorX,anchorY+5,'node');
      };
      element.querySelectorAll('.flow-port').forEach(port=>{
        port.onpointerdown=event=>{
          if(event.button!==0)return;
          event.preventDefault();event.stopPropagation();
          state.connection={source:id,port:port.dataset.side,pointer:worldPoint(event.clientX,event.clientY),snap:null};
          state.selectedNodes=new Set([id]);state.selectedEdges.clear();state.primaryNode=id;
          renderNodes();renderEdges();renderInspector();
        };
      });
    });
    renderEdges();
  }

  function clearSelection(){
    state.selectedNodes.clear();state.selectedEdges.clear();state.primaryNode=null;
    renderNodes();renderInspector();
  }
  function selectNode(id,additive){
    if(!additive){state.selectedNodes.clear();state.selectedEdges.clear()}
    if(additive&&state.selectedNodes.has(id))state.selectedNodes.delete(id);else state.selectedNodes.add(id);
    state.primaryNode=state.selectedNodes.has(id)?id:(state.selectedNodes.values().next().value||null);
    renderNodes();renderInspector();
  }
  function selectEdge(key,additive){
    if(!additive){state.selectedNodes.clear();state.selectedEdges.clear();state.primaryNode=null}
    if(additive&&state.selectedEdges.has(key))state.selectedEdges.delete(key);else state.selectedEdges.add(key);
    renderNodes();renderInspector();
  }
  function deleteSelection(){
    if(!state.selectedNodes.size&&!state.selectedEdges.size)return;
    const ids=new Set(state.selectedNodes),edgeKeys=new Set(state.selectedEdges);
    state.nodes=state.nodes.filter(node=>!ids.has(node.id));
    state.edges=state.edges.filter(edge=>!ids.has(edge.source)&&!ids.has(edge.target)&&!edgeKeys.has(edgeKey(edge)));
    state.selectedNodes.clear();state.selectedEdges.clear();state.primaryNode=null;
    markDirty();commitHistory();render();
  }
  function duplicateSelection(){
    const selected=state.nodes.filter(node=>state.selectedNodes.has(node.id));
    if(!selected.length)return;
    const map=new Map(),copies=[];
    selected.forEach(node=>{
      const copy=JSON.parse(JSON.stringify(node));
      copy.id=uid();copy.name+=' · 副本';copy.x+=36;copy.y+=36;map.set(node.id,copy.id);copies.push(copy);
    });
    const copiedEdges=state.edges.filter(edge=>map.has(edge.source)&&map.has(edge.target)).map(edge=>({...edge,source:map.get(edge.source),target:map.get(edge.target)}));
    state.nodes.push(...copies);state.edges.push(...copiedEdges);
    state.selectedNodes=new Set(copies.map(node=>node.id));state.selectedEdges.clear();state.primaryNode=copies[0]?.id||null;
    markDirty();commitHistory();render();
  }
  function setSelectedEnabled(enabled){
    state.nodes.forEach(node=>{if(state.selectedNodes.has(node.id))node.enabled=enabled});
    markDirty();commitHistory();render();
  }

  function beginNodeDrag(event,id){
    const selected=state.selectedNodes.has(id)?Array.from(state.selectedNodes):[id];
    const origins=new Map();
    state.nodes.forEach(node=>{if(selected.includes(node.id))origins.set(node.id,{x:node.x,y:node.y})});
    state.pointerAction={type:'node-drag',startX:event.clientX,startY:event.clientY,origins};
  }

  function beginPan(event){
    state.pointerAction={type:'pan',startX:event.clientX,startY:event.clientY,panX:state.panX,panY:state.panY};
    $('flowViewport')?.classList.add('is-panning');
  }

  function pointInRect(point,bounds){
    return point.x>=bounds.left&&point.x<=bounds.right&&point.y>=bounds.top&&point.y<=bounds.bottom;
  }
  function segmentIntersectsRect(a,b,bounds){
    if(pointInRect(a,bounds)||pointInRect(b,bounds))return true;
    const cross=(p1,p2,p3)=>((p2.x-p1.x)*(p3.y-p1.y)-(p2.y-p1.y)*(p3.x-p1.x));
    const hit=(p1,p2,p3,p4)=>{
      const d1=cross(p1,p2,p3),d2=cross(p1,p2,p4),d3=cross(p3,p4,p1),d4=cross(p3,p4,p2);
      return ((d1===0||d2===0||d1*d2<0)&&(d3===0||d4===0||d3*d4<0));
    };
    const tl={x:bounds.left,y:bounds.top},tr={x:bounds.right,y:bounds.top},br={x:bounds.right,y:bounds.bottom},bl={x:bounds.left,y:bounds.bottom};
    return hit(a,b,tl,tr)||hit(a,b,tr,br)||hit(a,b,br,bl)||hit(a,b,bl,tl);
  }

  function beginBoxSelect(event,{contextOnClick=false}={}){
    const point=viewportPoint(event.clientX,event.clientY);
    state.pointerAction={type:'box',pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,startViewport:point,moved:false,additive:event.shiftKey||event.ctrlKey||event.metaKey,contextOnClick};
    const viewport=$('flowViewport');
    if(viewport?.setPointerCapture&&event.pointerId!=null){try{viewport.setPointerCapture(event.pointerId)}catch(_){}}
    const box=$('flowSelectionBox');
    if(box){box.hidden=false;box.style.left=point.x+'px';box.style.top=point.y+'px';box.style.width='0px';box.style.height='0px'}
  }

  function updatePointerAction(event){
    const action=state.pointerAction;
    if(!action)return;
    if(action.type==='pan'){
      state.panX=action.panX+(event.clientX-action.startX);
      state.panY=action.panY+(event.clientY-action.startY);
      setTransform();return;
    }
    if(action.type==='minimap'){
      const px=Math.max(0,Math.min(action.box.width,event.clientX-action.box.left));
      const py=Math.max(0,Math.min(action.box.height,event.clientY-action.box.top));
      const worldX=action.view.x+(px/action.box.width)*action.view.width;
      const worldY=action.view.y+(py/action.box.height)*action.view.height;
      const vp=$('flowViewport').getBoundingClientRect();
      state.panX=vp.width/2-worldX*state.zoom;state.panY=vp.height/2-worldY*state.zoom;
      setTransform();return;
    }
    if(action.type==='node-drag'){
      const dx=(event.clientX-action.startX)/state.zoom,dy=(event.clientY-action.startY)/state.zoom;
      state.nodes.forEach(node=>{
        const origin=action.origins.get(node.id);
        if(origin){node.x=Math.max(-2000,origin.x+dx);node.y=Math.max(-2000,origin.y+dy)}
      });
      markDirty();renderNodes();renderMinimap();return;
    }
    if(action.type==='box'){
      if(Math.hypot(event.clientX-action.startX,event.clientY-action.startY)>5)action.moved=true;
      const current=viewportPoint(event.clientX,event.clientY),start=action.startViewport;
      const left=Math.min(start.x,current.x),top=Math.min(start.y,current.y),width=Math.abs(current.x-start.x),height=Math.abs(current.y-start.y);
      const box=$('flowSelectionBox');
      if(box){box.style.left=left+'px';box.style.top=top+'px';box.style.width=width+'px';box.style.height=height+'px'}
    }
  }

  function finishPointerAction(event){
    const action=state.pointerAction;
    if(!action)return;
    state.pointerAction=null;
    const viewport=$('flowViewport');
    if(action.pointerId!=null&&viewport?.hasPointerCapture?.(action.pointerId)){try{viewport.releasePointerCapture(action.pointerId)}catch(_){}}
    viewport?.classList.remove('is-panning');
    $('flowMinimap')?.classList.remove('is-dragging');
    if(action.type==='node-drag'){commitHistory();return}
    if(action.type==='box'){
      const box=$('flowSelectionBox');if(box)box.hidden=true;
      if(!action.moved){
        if(action.contextOnClick)showContextMenu(event.clientX,event.clientY,'canvas');
        else clearSelection();
        return;
      }
      const startWorld=worldPoint(action.startX,action.startY),endWorld=worldPoint(event.clientX,event.clientY);
      const bounds={left:Math.min(startWorld.x,endWorld.x),right:Math.max(startWorld.x,endWorld.x),top:Math.min(startWorld.y,endWorld.y),bottom:Math.max(startWorld.y,endWorld.y)};
      if(!action.additive){state.selectedNodes.clear();state.selectedEdges.clear()}
      state.nodes.forEach(node=>{
        const fullyContained=node.x>=bounds.left&&node.x+NODE_W<=bounds.right&&node.y>=bounds.top&&node.y+NODE_H<=bounds.bottom;
        if(fullyContained)state.selectedNodes.add(node.id);
      });
      state.edges.forEach(edge=>{
        if(state.selectedNodes.has(edge.source)&&state.selectedNodes.has(edge.target))state.selectedEdges.add(edgeKey(edge));
      });
      state.primaryNode=state.selectedNodes.values().next().value||null;
      renderNodes();renderInspector();
    }
  }

  function finishConnection(event){
    if(!state.connection)return;
    const connection=state.connection;
    const snap=connection.snap||connectionSnapAt(event.clientX,event.clientY);
    state.connection=null;clearSnapHighlight();
    if(snap&&snap.node.id!==connection.source){
      const edge={source:connection.source,target:snap.node.id,source_port:connection.port,target_port:snap.side,label:''};
      if(!state.edges.some(item=>item.source===edge.source&&item.target===edge.target)){
        state.edges.push(edge);state.selectedEdges=new Set([edgeKey(edge)]);state.selectedNodes.clear();state.primaryNode=null;markDirty();commitHistory();
      }
    }
    renderNodes();renderInspector();
  }

  function showContextMenu(x,y,type){
    hideContextMenu();
    const menu=document.createElement('div');
    menu.className='flow-context-menu';
    const item=(label,action,danger)=>'<button type="button" data-action="'+action+'" class="'+(danger?'danger':'')+'">'+label+'</button>';
    if(type==='node'){
      menu.innerHTML=item('复制所选节点','duplicate')+
        item(state.nodes.filter(node=>state.selectedNodes.has(node.id)).some(node=>node.enabled===false)?'启用所选':'禁用所选','toggle')+
        '<span class="flow-context-separator"></span>'+item('删除所选','delete',true);
    }else if(type==='edge'){
      menu.innerHTML=item('删除连线','delete-edge',true);
    }else{
      menu.innerHTML=item('全选','select-all')+item('适应画布','fit')+item(state.previewVisible?'隐藏小地图':'显示小地图','preview')+
        (state.selectedNodes.size||state.selectedEdges.size?'<span class="flow-context-separator"></span>'+item('删除所选','delete',true):'');
    }
    menu.style.visibility='hidden';
    menu.style.left=Math.max(8,Number(x)||8)+'px';
    menu.style.top=Math.max(8,Number(y)||8)+'px';
    document.body.appendChild(menu);
    const width=Math.max(180,menu.offsetWidth||190),height=Math.max(44,menu.offsetHeight);
    menu.style.left=Math.max(8,Math.min(Number(x)||8,window.innerWidth-width-8))+'px';
    menu.style.top=Math.max(8,Math.min(Number(y)||8,window.innerHeight-height-8))+'px';
    requestAnimationFrame(()=>{if(menu.isConnected)menu.style.visibility='visible'});
    menu.onclick=event=>{
      const action=event.target.closest('button')?.dataset.action;if(!action)return;
      if(action==='duplicate')duplicateSelection();
      if(action==='toggle'){
        const hasDisabled=state.nodes.filter(node=>state.selectedNodes.has(node.id)).some(node=>node.enabled===false);
        setSelectedEnabled(hasDisabled);
      }
      if(action==='delete')deleteSelection();
      if(action==='delete-edge'){deleteSelection()}
      if(action==='select-all'){state.selectedNodes=new Set(state.nodes.map(node=>node.id));state.selectedEdges=new Set(state.edges.map(edgeKey));state.primaryNode=state.nodes[0]?.id||null;renderNodes();renderInspector()}
      if(action==='fit')fit();
      if(action==='preview')toggleMinimap();
      hideContextMenu();
    };
    state.menu=menu;
  }
  function hideContextMenu(){if(state.menu){state.menu.remove();state.menu=null}}

  function renderInspector(){
    const root=$('flowInspectorBody');if(!root)return;
    const selectedNodes=state.nodes.filter(node=>state.selectedNodes.has(node.id));
    if(selectedNodes.length>1||state.selectedEdges.size>1||(selectedNodes.length&&state.selectedEdges.size)){
      root.innerHTML='<div class="flow-selection-summary"><strong>已选择 '+selectedNodes.length+' 个节点 / '+state.selectedEdges.size+' 条连线</strong><p>拖动任一已选节点可整体移动；Delete 批量删除。</p></div>'+
        '<div class="flow-inspector-actions"><button class="button" id="selectionEnable">启用节点</button><button class="button" id="selectionDisable">禁用节点</button></div>'+
        '<div class="flow-inspector-actions"><button class="button" id="selectionDuplicate">复制节点</button><button class="button danger" id="selectionDelete">删除所选</button></div>';
      $('selectionEnable').onclick=()=>setSelectedEnabled(true);$('selectionDisable').onclick=()=>setSelectedEnabled(false);
      $('selectionDuplicate').onclick=duplicateSelection;$('selectionDelete').onclick=deleteSelection;return;
    }
    if(!selectedNodes.length&&state.selectedEdges.size===1){
      const key=Array.from(state.selectedEdges)[0],edge=state.edges.find(item=>edgeKey(item)===key);
      if(!edge){root.innerHTML='';return}
      root.innerHTML='<div class="flow-selection-summary"><strong>连线</strong><p>'+esc(edge.source)+' · '+esc(edge.source_port||'right')+' → '+esc(edge.target)+' · '+esc(edge.target_port||'left')+'</p></div>'+
        '<label class="flow-field"><span>连线标签</span><input id="edgeLabel" value="'+esc(edge.label||'')+'"></label>'+
        '<div class="flow-inspector-actions"><button class="button danger" id="edgeDelete">删除连线</button></div>';
      $('edgeLabel').onchange=()=>{edge.label=$('edgeLabel').value.slice(0,120);markDirty();renderEdges()};
      $('edgeDelete').onclick=deleteSelection;return;
    }
    const node=selectedNodes[0]||null;
    if(!node){
      root.innerHTML='<label class="flow-field"><span>流程名称</span><input id="flowNameField" value="'+esc(state.flow?.flow_name||'未命名流程')+'"></label>'+
        '<label class="flow-field"><span>说明</span><textarea id="flowDescriptionField">'+esc(state.flow?.description||'')+'</textarea></label>'+
        '<label class="flow-field"><span>Lane</span><select id="flowLaneField"><option value="interactive">interactive</option><option value="overnight">overnight</option><option value="etl">etl</option></select></label>'+
        '<label class="flow-field"><span>全局变量 JSON</span><textarea id="flowVariables">{}</textarea></label>'+
        '<div class="flow-help">组件库只展示可独立编排能力；脚本内部原子步骤仍会记录在运行树中，但不会污染拖拽组件库。</div>';
      if(state.flow){$('flowLaneField').value=state.flow.execution_lane||'interactive';$('flowVariables').value=JSON.stringify(state.flow.definition?.variables||{},null,2)}
      ['flowNameField','flowDescriptionField','flowLaneField','flowVariables'].forEach(id=>{if($(id))$(id).onchange=markDirty});
      return;
    }
    const component=def(node.component_code)||{};
    root.innerHTML='<label class="flow-field"><span>节点名称</span><input id="nodeName" value="'+esc(node.name)+'"></label>'+
      '<label class="flow-field"><span>component_code</span><input value="'+esc(node.component_code)+'" readonly></label>'+
      '<div class="flow-grid2"><label class="flow-field"><span>超时秒数</span><input id="nodeTimeout" type="number" min="1" value="'+esc(node.timeout_seconds)+'"></label>'+
      '<label class="flow-field"><span>重试次数</span><input id="nodeRetry" type="number" min="0" max="5" value="'+esc(node.retry_count)+'"></label></div>'+
      '<label class="flow-field"><span>失败策略</span><select id="nodeOnError"><option value="stop">停止 Flow</option><option value="continue">继续</option><option value="needs_human">转人工</option></select></label>'+
      '<label class="flow-field"><span>运行条件</span><input id="nodeCondition" value="'+esc(node.condition||'')+'" placeholder="受限表达式，留空为总是执行"></label>'+
      '<label class="flow-field"><span>组件配置 JSON</span><textarea id="nodeConfig">'+esc(JSON.stringify(node.config||{},null,2))+'</textarea></label>'+
      '<label class="flow-switch"><input id="nodeEnabled" type="checkbox" '+(node.enabled!==false?'checked':'')+'>启用节点</label>'+
      '<div class="flow-help">'+esc(component.description||'自定义草稿组件。注册后才能发布。')+'</div>'+
      '<div class="flow-inspector-actions"><button class="button" id="nodeDuplicate">复制</button><button class="button danger" id="nodeDelete">删除</button></div>';
    $('nodeOnError').value=node.on_error||'stop';
    ['nodeName','nodeTimeout','nodeRetry','nodeOnError','nodeCondition','nodeEnabled','nodeConfig'].forEach(id=>{
      $(id).onchange=()=>{
        try{
          node.name=$('nodeName').value;node.timeout_seconds=Math.max(1,Number($('nodeTimeout').value||60));
          node.retry_count=Math.max(0,Math.min(5,Number($('nodeRetry').value||0)));node.on_error=$('nodeOnError').value;
          node.condition=$('nodeCondition').value;node.enabled=$('nodeEnabled').checked;node.config=JSON.parse($('nodeConfig').value||'{}');
          markDirty();commitHistory();renderNodes();renderConsole();
        }catch(error){toast('组件配置 JSON 无效','error')}
      };
    });
    $('nodeDuplicate').onclick=duplicateSelection;$('nodeDelete').onclick=deleteSelection;
  }

  function validateFlow(){
    const issues=[],ids=new Set(state.nodes.map(node=>node.id));
    state.edges.forEach(edge=>{if(!ids.has(edge.source)||!ids.has(edge.target)||edge.source===edge.target)issues.push({type:'error',text:'存在无效连线'})});
    const indegree=new Map(state.nodes.map(node=>[node.id,0]));
    state.edges.forEach(edge=>indegree.set(edge.target,(indegree.get(edge.target)||0)+1));
    const starts=state.nodes.filter(node=>node.enabled!==false&&(indegree.get(node.id)||0)===0);
    if(!state.nodes.length)issues.push({type:'error',text:'流程没有组件'});
    else if(starts.length!==1)issues.push({type:'warn',text:'当前有 '+starts.length+' 个入口节点，推荐一个明确入口'});
    if(state.nodes.some(node=>node.component_code.startsWith('custom.')))issues.push({type:'warn',text:'存在 custom.* 草稿组件，注册 Handler 后才能发布'});
    const missing=state.nodes.filter(node=>node.enabled!==false&&!node.component_code.startsWith('custom.')&&!def(node.component_code));
    if(missing.length)issues.push({type:'error',text:'存在未注册组件：'+missing.map(node=>node.component_code).join('、')});
    if(!issues.some(item=>item.type==='error'))issues.unshift({type:'ok',text:'结构检查通过'});
    renderConsole(issues);return issues;
  }
  function silentIssues(){
    const issues=[];
    if(!state.nodes.length)issues.push({type:'error',text:'流程没有组件'});
    const missing=state.nodes.filter(node=>node.enabled!==false&&!node.component_code.startsWith('custom.')&&!def(node.component_code));
    if(missing.length)issues.push({type:'warn',text:'含未注册组件：请迁移或删除后再发布'});
    if(!issues.length)issues.push({type:'ok',text:'画布可保存；发布时服务端会再次校验 DAG 与 Handler'});
    return issues;
  }
  function renderConsole(issues){
    const root=$('flowConsole');if(!root)return;issues=issues||silentIssues();
    root.innerHTML='<div class="flow-console-grid"><div class="flow-stat"><small>组件</small><strong>'+state.nodes.length+'</strong></div>'+
      '<div class="flow-stat"><small>连线</small><strong>'+state.edges.length+'</strong></div>'+
      '<div class="flow-stat"><small>版本</small><strong>v'+(state.flow?.version||1)+'</strong></div>'+
      '<div class="flow-stat"><small>状态</small><strong>'+esc(state.flow?.status||'draft')+'</strong></div></div>'+
      '<div class="flow-validation">'+issues.map(item=>'<div class="flow-validation-item '+(item.type==='ok'?'':item.type)+'">'+esc(item.text)+'</div>').join('')+'</div>';
  }

  function render(){
    renderNodes();renderInspector();renderConsole();setTransform();renderMinimap();
  }

  function renderLibrary(){
    const query=($('flowComponentSearch')?.value||'').trim().toLowerCase(),groups={};
    state.components.filter(component=>!query||((component.name+' '+component.code+' '+component.description).toLowerCase().includes(query))).forEach(component=>(groups[component.category]??=[]).push(component));
    $('flowLibrary').innerHTML=Object.entries(groups).map(([category,items])=>
      '<div class="flow-category"><div class="flow-category-title"><span>'+esc(categories[category]||category)+'</span><span>'+items.length+'</span></div>'+
      items.map(component=>
        '<div class="flow-component" draggable="true" data-code="'+esc(component.code)+'" title="可独立放入 Flow 并发布执行">'+
          '<span class="flow-component-icon">'+esc((category||'C').slice(0,3).toUpperCase())+'</span><span><strong>'+esc(component.name)+
          ' <em class="flow-capability ready">可编排</em></strong><small>'+esc(component.code)+'</small></span><span class="flow-drag">⠿</span></div>'
      ).join('')+'</div>').join('');
    $('flowLibrary').querySelectorAll('.flow-component').forEach(element=>{
      element.ondragstart=event=>{event.dataTransfer.setData('text/component',element.dataset.code);event.dataTransfer.effectAllowed='copy'};
    });
  }

  function normalizeEdges(edges){
    return(edges||[]).map(edge=>({...edge,source_port:SIDES.includes(edge.source_port)?edge.source_port:'right',target_port:SIDES.includes(edge.target_port)?edge.target_port:'left'}));
  }
  function loadFlowIntoState(flow){
    stopRuntimeTimers();state.activeTestRunId=null;
    state.flow=flow;const definition=flow.definition||{};
    state.nodes=(definition.nodes||[]).map(node=>({...node,component_code:node.component_code||node.code,x:Number(node.x||0),y:Number(node.y||0),enabled:node.enabled!==false,timeout_seconds:Number(node.timeout_seconds||def(node.component_code)?.timeout_seconds||60),retry_count:Number(node.retry_count||0),config:node.config||{}}));
    state.edges=normalizeEdges(definition.edges);state.selectedNodes.clear();state.selectedEdges.clear();state.primaryNode=null;state.dirty=false;
    state.latestRun=null;state.nodeRuntime=new Map();
    if($('flowSelect'))$('flowSelect').value=flow.flow_id;
    renderFlowPicker();
    render();resetHistory();
  }

  function mapRunToNodes(run){
    state.nodeRuntime=new Map();state.latestRun=run||null;
    if(!run)return;
    const topLevel=(run.steps||[]).flatMap(step=>(step.components||[]).filter(component=>!component.parent_component_run_id));
    const unmatched=[...topLevel];
    state.nodes.forEach(node=>{
      let index=unmatched.findIndex(component=>component.input_snapshot?.node_id===node.id);
      if(index<0)index=unmatched.findIndex(component=>component.component_code===node.component_code);
      if(index>=0){state.nodeRuntime.set(node.id,unmatched[index]);unmatched.splice(index,1)}
    });
  }

  async function pollRun(runId,{quiet=false}={}){
    if(!runId)return;
    if(state.runtimeTimer){clearTimeout(state.runtimeTimer);state.runtimeTimer=null}
    try{
      const run=await api('/api/automation/runs/'+runId);
      if(state.activeTestRunId&&state.activeTestRunId!==runId)return;
      mapRunToNodes(run);renderNodes();renderEdges();renderConsole();startRuntimeTicker();
      if(['queued','running','needs_human'].includes(run.status)){
        state.runtimeTimer=setTimeout(()=>pollRun(runId,{quiet:true}).catch(()=>{}),800);
      }else{
        if(state.runtimeTicker){clearInterval(state.runtimeTicker);state.runtimeTicker=null}
        renderNodes();renderEdges();
        if(!quiet)toast('测试运行已完成：'+(runtimeLabels[run.status]||run.status));
      }
    }catch(error){
      if(!quiet)toast('加载测试运行失败：'+error.message,'error');
    }
  }
  async function refreshFlows(selectId){
    const data=await api('/api/automation/flows');state.flows=data.items||[];
    $('flowSelect').innerHTML=state.flows.map(flow=>'<option value="'+esc(flow.flow_id)+'">'+esc(flow.flow_name)+' · v'+flow.version+' · '+esc(flow.status)+'</option>').join('')||'<option value="">暂无流程</option>';
    renderFlowPicker();
    const pending=sessionStorage.getItem('automation.flow.open');if(pending)sessionStorage.removeItem('automation.flow.open');
    const target=selectId||pending||state.flow?.flow_id||state.flows[0]?.flow_id;
    if(target)await openFlow(target);else{state.flow=null;state.nodes=[];state.edges=[];render()}
  }
  function renderFlowPicker(){
    const label=flow=>'<span class="flow-picker-name">'+esc(flow.flow_name)+'</span><span class="status-tag ready">v'+esc(flow.version)+'</span><span class="status-tag '+(flow.status==='published'?'success':'draft')+'">'+(flow.status==='published'?'已发布':'草稿')+'</span>';
    const selected=state.flow||state.flows.find(flow=>flow.flow_id===$('flowSelect').value);
    $('flowPickerLabel').innerHTML=selected?label(selected):'暂无流程';
    $('flowPickerOptions').innerHTML=state.flows.map(flow=>'<button type="button" role="option" aria-selected="'+(flow.flow_id===selected?.flow_id)+'" data-flow-choice="'+esc(flow.flow_id)+'">'+label(flow)+'</button>').join('');
  }
  async function openFlow(id){
    if(!id){state.flow=null;state.nodes=[];state.edges=[];mapRunToNodes(null);render();return}
    const flow=await api('/api/automation/flows/'+id);loadFlowIntoState(flow);setTimeout(fit,20);
  }
  async function openExternal(flowId){
    if(!flowId)return;
    if(location.hash!=='#flow-studio'){sessionStorage.setItem('automation.flow.open',flowId);location.hash='flow-studio';return}
    await load();await openFlow(flowId);
  }

  async function newFlow(){
    const name=prompt('新流程名称','新的自动化 Flow');if(!name)return;
    const flow=await api('/api/automation/flows',{method:'POST',body:JSON.stringify({flow_name:name,execution_lane:'interactive',definition:{nodes:[],edges:[],variables:{}}})});
    await refreshFlows(flow.flow_id);toast('流程草稿已创建');
  }
  async function save(){
    if(!state.flow)return newFlow();
    let variables;try{variables=parseVariables()}catch(error){return toast('变量 JSON 无效','error')}
    const body={flow_name:$('flowNameField')?.value||state.flow.flow_name,description:$('flowDescriptionField')?.value||state.flow.description||'',execution_lane:$('flowLaneField')?.value||state.flow.execution_lane,definition:{...definition(),variables}};
    const flow=await api('/api/automation/flows/'+state.flow.flow_id,{method:'PUT',body:JSON.stringify(body)});
    loadFlowIntoState(flow);await refreshFlows(flow.flow_id);state.dirty=false;$('flowSaveBtn')?.classList.remove('primary');toast('流程草稿已保存');
  }
  async function publish(){
    await save();const issues=validateFlow();if(issues.some(item=>item.type==='error'))return toast('流程存在阻塞问题','error');
    try{
      const flow=await api('/api/automation/flows/'+state.flow.flow_id+'/publish',{method:'POST',body:'{}'});
      loadFlowIntoState(flow);await refreshFlows(flow.flow_id);toast('流程已发布，并已出现在自动化任务列表');
      window.dispatchEvent(new CustomEvent('automation:jobs-changed'));
    }catch(error){toast(error.message,'error')}
  }

  async function openRunDialog(flowId,mode='test'){
    ensureBound();
    const target=flowId||state.flow?.flow_id;if(!target)return toast('请先选择流程','error');
    const flow=state.flow?.flow_id===target?state.flow:await api('/api/automation/flows/'+target);
    if(mode==='production'&&flow.status!=='published')return toast('正式运行需要先发布版本','error');
    if(target===state.flow?.flow_id&&state.dirty)return toast('请先保存草稿再测试运行','error');
    state.runFlowId=target;state.runMode=mode;
    if($('flowRunDialogTitle'))$('flowRunDialogTitle').textContent=mode==='test'?'测试运行 Flow':'运行已发布 Flow';
    if($('flowRunSubmitBtn'))$('flowRunSubmitBtn').textContent=mode==='test'?'开始测试运行':'加入执行队列';
    if($('flowRunHint'))$('flowRunHint').textContent=mode==='test'?'测试运行会留在当前画布显示节点、连线和实时耗时，不进入正式执行记录。':'正式运行会进入自动化任务执行记录。';
    $('flowRunBusinessDate').value=new Date().toLocaleDateString('sv-SE');$('flowRunStartDate').value='';$('flowRunEndDate').value='';$('flowRunDialog').showModal();
  }

  function addNode(code,x,y){
    const component=def(code)||{name:code,timeout_seconds:60};
    const node={id:uid(),component_code:code,name:component.name,x,y,enabled:true,timeout_seconds:component.timeout_seconds||60,retry_count:1,on_error:'stop',condition:'',config:Object.fromEntries((component.config_schema||[]).map(field=>[field.key,field.default]))};
    state.nodes.push(node);state.selectedNodes=new Set([node.id]);state.selectedEdges.clear();state.primaryNode=node.id;markDirty();commitHistory();render();
  }
  function customNode(){
    let code=(prompt('自定义组件编码（必须 custom. 开头）','custom.business.step')||'').trim();
    if(!/^custom\.[a-z0-9_.-]+$/.test(code))return toast('组件编码格式无效','error');
    const name=prompt('组件名称','自定义业务步骤')||code;
    const node={id:uid(),component_code:code,name,x:120+state.nodes.length*25,y:100+state.nodes.length*20,enabled:true,timeout_seconds:60,retry_count:0,on_error:'stop',condition:'',config:{}};
    state.nodes.push(node);state.selectedNodes=new Set([node.id]);state.primaryNode=node.id;markDirty();commitHistory();render();
  }

  function fit(){
    const viewport=$('flowViewport');if(!viewport)return;
    if(!state.nodes.length){state.zoom=1;state.panX=50;state.panY=40;setTransform();return}
    const rect=viewport.getBoundingClientRect(),minX=Math.min(...state.nodes.map(node=>node.x)),minY=Math.min(...state.nodes.map(node=>node.y)),maxX=Math.max(...state.nodes.map(node=>node.x+NODE_W)),maxY=Math.max(...state.nodes.map(node=>node.y+NODE_H));
    state.zoom=Math.max(.3,Math.min(1.3,Math.min((rect.width-110)/(maxX-minX||1),(rect.height-110)/(maxY-minY||1))));
    state.panX=(rect.width-(maxX-minX)*state.zoom)/2-minX*state.zoom;state.panY=(rect.height-(maxY-minY)*state.zoom)/2-minY*state.zoom;setTransform();
  }
  function zoomAt(factor,clientX,clientY){
    const viewport=$('flowViewport'),rect=viewport.getBoundingClientRect(),cx=clientX??(rect.left+rect.width/2),cy=clientY??(rect.top+rect.height/2);
    const before=worldPoint(cx,cy),next=Math.max(.3,Math.min(2,state.zoom*factor));state.zoom=next;
    state.panX=(cx-rect.left)-before.x*next;state.panY=(cy-rect.top)-before.y*next;setTransform();
  }

  function toggleMinimap(){
    state.previewVisible=!state.previewVisible;$('flowMinimap')?.classList.toggle('hidden',!state.previewVisible);
    if($('flowPreviewToggle'))$('flowPreviewToggle').textContent=state.previewVisible?'隐藏小地图':'显示小地图';
    renderMinimap();
  }
  function renderMinimap(){
    const root=$('flowMinimapSvg');if(!root||!state.previewVisible)return;
    const viewport=$('flowViewport');if(!viewport)return;
    const nodes=state.nodes;
    let minX=0,minY=0,maxX=1200,maxY=700;
    if(nodes.length){minX=Math.min(...nodes.map(node=>node.x))-120;minY=Math.min(...nodes.map(node=>node.y))-120;maxX=Math.max(...nodes.map(node=>node.x+NODE_W))+120;maxY=Math.max(...nodes.map(node=>node.y+NODE_H))+120}
    const width=Math.max(500,maxX-minX),height=Math.max(300,maxY-minY);
    root.setAttribute('viewBox',[minX,minY,width,height].join(' '));
    const lines=state.edges.map(edge=>{
      const source=state.nodes.find(node=>node.id===edge.source),target=state.nodes.find(node=>node.id===edge.target);if(!source||!target)return'';
      const a=portPoint(source,edge.source_port||'right'),b=portPoint(target,edge.target_port||'left');
      return'<line x1="'+a.x+'" y1="'+a.y+'" x2="'+b.x+'" y2="'+b.y+'" class="minimap-edge"></line>';
    }).join('');
    const cards=nodes.map(node=>'<rect x="'+node.x+'" y="'+node.y+'" width="'+NODE_W+'" height="'+NODE_H+'" rx="10" class="minimap-node '+(state.selectedNodes.has(node.id)?'selected':'')+'"></rect>').join('');
    const vpRect=viewport.getBoundingClientRect(),vx=-state.panX/state.zoom,vy=-state.panY/state.zoom,vw=vpRect.width/state.zoom,vh=vpRect.height/state.zoom;
    root.innerHTML=lines+cards+'<rect x="'+vx+'" y="'+vy+'" width="'+vw+'" height="'+vh+'" class="minimap-viewport"></rect>';
  }

  async function toggleFullscreen(){
    const page=$('flow-studioPage');if(!page)return;
    try{
      if(document.fullscreenElement)await document.exitFullscreen();
      else if(page.requestFullscreen)await page.requestFullscreen();
      else page.classList.toggle('flow-fullscreen-fallback');
    }catch(error){page.classList.toggle('flow-fullscreen-fallback')}
    setTimeout(()=>{fit();updateFullscreenButton()},80);
  }
  function updateFullscreenButton(){
    const active=!!document.fullscreenElement||$('flow-studioPage')?.classList.contains('flow-fullscreen-fallback');
    if($('flowFullscreenBtn'))$('flowFullscreenBtn').textContent=active?'退出全屏':'全屏';
  }

  function ensureBound(){
    if(!state.loaded){bind();state.loaded=true}
  }

  function bind(){
    $('closeFlowRunDialog').onclick=$('cancelFlowRunDialog').onclick=()=>{$('flowRunDialog').close();state.runFlowId=null};
    $('flowRunForm').onsubmit=async event=>{
      event.preventDefault();
      try{
        const flowId=state.runFlowId||state.flow?.flow_id,profileName=$('flowRunProfile').value.trim(),businessDate=$('flowRunBusinessDate').value,startDate=$('flowRunStartDate').value||null,endDate=$('flowRunEndDate').value||null;
        if(!flowId)return toast('未选择 Flow','error');if(!profileName||!businessDate)return toast('Profile 和业务基准日不能为空','error');
        if(Boolean(startDate)!==Boolean(endDate))return toast('开始和结束日期必须同时填写','error');
        const mode=state.runMode||'test',path='/api/automation/flows/'+flowId+(mode==='test'?'/test-run':'/run');
        const run=await api(path,{method:'POST',body:JSON.stringify({profile_name:profileName,business_date:businessDate,start_date:startDate,end_date:endDate})});
        $('flowRunDialog').close();state.runFlowId=null;
        if(mode==='test'){
          stopRuntimeTimers();state.latestRun=null;state.nodeRuntime=new Map();state.activeTestRunId=run.automation_run_id;
          renderNodes();renderEdges();renderConsole();toast('测试运行已开始：'+String(run.automation_run_id).slice(0,8));
          pollRun(run.automation_run_id).catch(error=>toast(error.message,'error'));
        }else{
          toast('正式 Flow 已入队：'+run.automation_run_id);location.hash='runs';
        }
      }catch(error){toast(error.message,'error')}
    };
    $('flowSelect').onchange=()=>openFlow($('flowSelect').value).catch(error=>toast(error.message,'error'));
    const closePicker=()=>{$('flowPickerOptions').hidden=true;$('flowPickerTrigger').setAttribute('aria-expanded','false');};
    $('flowPickerTrigger').onclick=()=>{const menu=$('flowPickerOptions');menu.hidden=!menu.hidden;$('flowPickerTrigger').setAttribute('aria-expanded',String(!menu.hidden));if(!menu.hidden)(menu.querySelector('[aria-selected="true"]')||menu.querySelector('button'))?.focus();};
    $('flowPickerOptions').onclick=event=>{const button=event.target.closest('[data-flow-choice]');if(!button)return;$('flowSelect').value=button.dataset.flowChoice;closePicker();$('flowPickerTrigger').focus();$('flowSelect').dispatchEvent(new Event('change'));};
    $('flowPicker').onkeydown=event=>{if(event.key==='Escape'){closePicker();$('flowPickerTrigger').focus();}if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&!$('flowPickerOptions').hidden){event.preventDefault();const options=[...$('flowPickerOptions').querySelectorAll('button')],index=options.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?options.length-1:(index+(event.key==='ArrowDown'?1:-1)+options.length)%options.length;options[next]?.focus();}};
    document.addEventListener('click',event=>{if(!$('flowPicker').contains(event.target))closePicker();});
    $('flowNewBtn').onclick=()=>newFlow().catch(error=>toast(error.message,'error'));
    $('flowSaveBtn').onclick=()=>save().catch(error=>toast(error.message,'error'));
    $('flowPublishBtn').onclick=()=>publish().catch(error=>toast(error.message,'error'));
    $('flowRunBtn').onclick=()=>openRunDialog(null,'test').catch(error=>toast(error.message,'error'));
    $('flowUndoBtn').onclick=undo;$('flowRedoBtn').onclick=redo;
    $('flowValidateBtn').onclick=validateFlow;
    $('flowVersionsBtn').onclick=()=>{if(!state.flow)return toast('请先选择流程','error');window.AutomationOpsCenter?.showFlowVersions(state.flow.flow_id)};
    $('flowFitBtn').onclick=fit;
    $('flowZoomIn').onclick=()=>zoomAt(1.12);$('flowZoomOut').onclick=()=>zoomAt(.88);
    $('flowCustomBtn').onclick=customNode;$('flowComponentSearch').oninput=renderLibrary;
    $('flowFullscreenBtn').onclick=toggleFullscreen;$('flowRuntimeRefreshBtn').onclick=clearRuntimeOverlay;$('flowPreviewToggle').onclick=toggleMinimap;

    $('flowExportBtn').onclick=()=>{if(!state.flow)return;const blob=new Blob([JSON.stringify({flow:{...state.flow,definition:definition()}},null,2)],{type:'application/json'}),anchor=document.createElement('a');anchor.href=URL.createObjectURL(blob);anchor.download=(state.flow.flow_code||'flow')+'.json';anchor.click();URL.revokeObjectURL(anchor.href)};
    $('flowImportBtn').onclick=()=>$('flowImportFile').click();
    $('flowImportFile').onchange=event=>{
      const file=event.target.files?.[0];if(!file)return;const reader=new FileReader();
      reader.onload=()=>{try{const body=JSON.parse(reader.result),flow=body.flow||body;if(!flow.definition)throw new Error('缺少 definition');state.nodes=flow.definition.nodes||[];state.edges=normalizeEdges(flow.definition.edges||[]);markDirty();commitHistory();render();toast('已导入到当前草稿，请保存')}catch(error){toast(error.message,'error')}};
      reader.readAsText(file,'utf-8');event.target.value='';
    };

    const viewport=$('flowViewport');
    viewport.ondragover=event=>{event.preventDefault();viewport.classList.add('drag-over')};
    viewport.ondragleave=()=>viewport.classList.remove('drag-over');
    viewport.ondrop=event=>{event.preventDefault();viewport.classList.remove('drag-over');const code=event.dataTransfer.getData('text/component');if(!code)return;const point=worldPoint(event.clientX,event.clientY);addNode(code,point.x-NODE_W/2,point.y-NODE_H/2)};
    viewport.onwheel=event=>{event.preventDefault();zoomAt(event.deltaY<0?1.08:.92,event.clientX,event.clientY)};
    viewport.onpointerdown=event=>{
      hideContextMenu();
      if(state.connection)return;
      const blank=!event.target.closest('.flow-node')&&!event.target.closest('.flow-edge-group')&&!event.target.closest('.flow-minimap');
      if((event.button===0&&state.spaceDown)||event.button===1){event.preventDefault();beginPan(event);return}
      if(blank&&event.button===0){
        event.preventDefault();event.stopPropagation();beginBoxSelect(event,{contextOnClick:false});return;
      }
      if(blank&&event.button===2){
        event.preventDefault();event.stopPropagation();beginBoxSelect(event,{contextOnClick:true});return;
      }
    };
    viewport.oncontextmenu=event=>event.preventDefault();

    document.addEventListener('pointermove',event=>{
      if(state.connection){
        state.connection.pointer=worldPoint(event.clientX,event.clientY);
        state.connection.snap=connectionSnapAt(event.clientX,event.clientY);
        showSnapHighlight(state.connection.snap);
        renderEdges();
      }
      updatePointerAction(event);
    });
    document.addEventListener('pointerup',event=>{
      if(state.connection)finishConnection(event);
      if(state.pointerAction)finishPointerAction(event);
    });
    document.addEventListener('mousedown',event=>{if(state.menu&&!event.target.closest('.flow-context-menu'))hideContextMenu()});
    document.addEventListener('keydown',event=>{
      if(!studioVisible()||isTyping(event.target))return;
      if(event.code==='Space'){event.preventDefault();state.spaceDown=true;viewport.classList.add('pan-mode')}
      const command=event.ctrlKey||event.metaKey;
      if(command&&!event.altKey&&event.key.toLowerCase()==='z'){event.preventDefault();if(event.shiftKey)redo();else undo();return}
      if(command&&!event.altKey&&event.key.toLowerCase()==='y'){event.preventDefault();redo();return}
      if((event.key==='Delete'||event.key==='Backspace')&&(state.selectedNodes.size||state.selectedEdges.size)){event.preventDefault();deleteSelection()}
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='a'){event.preventDefault();state.selectedNodes=new Set(state.nodes.map(node=>node.id));state.selectedEdges=new Set(state.edges.map(edgeKey));state.primaryNode=state.nodes[0]?.id||null;renderNodes();renderInspector()}
      if(event.key==='Escape'){state.connection=null;clearSnapHighlight();hideContextMenu();if($('flow-studioPage')?.classList.contains('flow-fullscreen-fallback')){$('flow-studioPage').classList.remove('flow-fullscreen-fallback');updateFullscreenButton();setTimeout(fit,40)}else clearSelection();renderEdges()}
    });
    document.addEventListener('keyup',event=>{if(event.code==='Space'){state.spaceDown=false;viewport.classList.remove('pan-mode')}});window.addEventListener('blur',()=>{state.spaceDown=false;viewport.classList.remove('pan-mode')});
    document.addEventListener('fullscreenchange',()=>{updateFullscreenButton();setTimeout(fit,50)});

    $('flowMinimapSvg').addEventListener('pointerdown',event=>{
      if(event.button!==0)return;
      event.preventDefault();event.stopPropagation();
      const svg=event.currentTarget,box=svg.getBoundingClientRect(),view=svg.viewBox.baseVal;
      state.pointerAction={type:'minimap',box:{left:box.left,top:box.top,width:box.width,height:box.height},view:{x:view.x,y:view.y,width:view.width,height:view.height}};
      $('flowMinimap')?.classList.add('is-dragging');
      updatePointerAction(event);
    });
  }

  async function load(){
    ensureBound();
    const components=await api('/api/automation/components');state.components=components.items||[];renderLibrary();await refreshFlows();setTimeout(fit,60);
  }

  window.AutomationFlowStudio={
    load,
    open:openExternal,
    run:flowId=>openRunDialog(flowId,'production'),
    test:flowId=>openRunDialog(flowId,'test'),
    current:()=>state.flow
  };
})();
