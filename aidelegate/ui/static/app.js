'use strict';
(() => {
  const art = window.PIXEL_ART;
  const names = ['claude', 'codex', 'agy'];
  const desks = {claude: [136, 118], codex: [40, 128], agy: [232, 128]};
  const accents = {claude: '#d97757', codex: '#3ddc97', agy: '#7b8cff'};
  const known = new Set(['idle', 'sleep', 'working', 'fixing', 'checks', 'review', 'reviewing', 'waiting', 'failed', 'quota', 'celebrate']);
  const emotes = {sleep: 'sleep', fixing: 'alert', checks: 'wait', review: 'question', reviewing: 'look', waiting: 'question', failed: 'fail', quota: 'sleep', celebrate: 'done'};
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const demo = new URLSearchParams(location.search).get('demo') === '1';
  const $ = id => document.getElementById(id);
  const canvas = $('office-canvas'), scene = $('scene');
  const offscreen = document.createElement('canvas');
  offscreen.width = 320; offscreen.height = 180;
  const ctx = offscreen.getContext('2d'), output = canvas.getContext('2d');
  let scale = 1, state = {agents: {}, runs: [], counts: {}, stats: []};
  let modalRequest = 0, opener = null, demoStep = 0;
  const runtime = {}, layers = {};
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const safeState = name => known.has(state.agents[name]?.state) ? state.agents[name].state : 'idle';
  const randBlink = () => 3000 + Math.random() * 2000;
  for (const name of names) {
    runtime[name] = {state: 'idle', started: performance.now(), blinkAt: performance.now() + randBlink(), particles: [], confetti: [], lastParticle: 0};
    const label = node('div', 'agent-name', name.toUpperCase());
    const bubble = node('div', 'bubble');
    const bubbleText = node('span', 'bubble-text'); bubble.append(bubbleText); bubble.hidden = true;
    const hit = node('button', 'agent-hit');
    hit.type = 'button'; hit.setAttribute('aria-label', `Ver tarea de ${name === 'agy' ? 'agy' : name[0].toUpperCase() + name.slice(1)}`);
    label.style.setProperty('--accent', accents[name]); hit.style.setProperty('--accent', accents[name]);
    hit.addEventListener('click', () => openDetail(state.agents[name]?.run_id, hit, name));
    $('scene-layers').append(label, bubble, hit);
    layers[name] = {label, bubble, bubbleText, hit};
  }
  function resize() {
    scale = Math.max(1, Math.floor(scene.parentElement.clientWidth / 320));
    // TODO(diseño): bajo 320px disponibles no cabe una escala entera positiva; conservar 1 y permitir overflow.
    canvas.width = 320 * scale; canvas.height = 180 * scale;
    canvas.style.width = `${canvas.width}px`; canvas.style.height = `${canvas.height}px`;
    scene.style.width = `${canvas.width}px`; scene.style.height = `${canvas.height}px`;
    output.imageSmoothingEnabled = false;
    Object.assign($('board').style, {left: `${112 * scale}px`, top: `${12 * scale}px`, width: `${96 * scale}px`, height: `${46 * scale}px`});
    for (const name of names) {
      const [dx, dy] = desks[name], l = layers[name];
      Object.assign(l.label.style, {left: `${(dx + 24) * scale}px`, top: `${(dy + 24) * scale}px`});
      Object.assign(l.hit.style, {left: `${(dx + 12) * scale}px`, top: `${(dy - 26) * scale}px`, width: `${24 * scale}px`, height: `${40 * scale}px`});
    }
    output.imageSmoothingEnabled = false;
  }
  new ResizeObserver(resize).observe(scene.parentElement);
  function rect(x, y, w, h, color) {ctx.fillStyle = color; ctx.fillRect(x, y, w, h);}
  function outlined(x, y, w, h, color) {
    rect(x - 1, y - 1, w + 2, h + 2, '#1a1726'); rect(x, y, w, h, color);
  }
  function sprite(context, rows, palette, x, y, factor = 1) {
    rows.forEach((row, ry) => [...row].forEach((pixel, rx) => {
      if (pixel !== '.' && palette[pixel]) {
        context.fillStyle = palette[pixel]; context.fillRect(x + rx * factor, y + ry * factor, factor, factor);
      }
    }));
  }
  function faceRows(name, face) {
    const rows = art.characters[name].map(row => [...row]);
    for (const [y, line] of Object.entries(art.faces[face])) {
      [...line].forEach((pixel, x) => {if (pixel !== '_') rows[Number(y)][art.faceOriginCol + x] = pixel;});
    }
    return rows.map(row => row.join(''));
  }
  function faceFor(name, t) {
    const s = safeState(name), r = runtime[name];
    if (s === 'sleep') return 'blink';
    if (s === 'review' || s === 'celebrate') return 'happy';
    if (s === 'failed' || s === 'quota') return 'sad';
    if (!motion.matches && ['idle', 'working', 'reviewing', 'checks'].includes(s)) {
      if (t >= r.blinkAt + 150) r.blinkAt = t + randBlink();
      if (t >= r.blinkAt) return 'blink';
    }
    return 'base';
  }
  function background() {
    rect(0, 0, 320, 180, '#13111c'); rect(0, 0, 320, 80, '#1e1b2e');
    rect(0, 78, 320, 2, '#3a3358');
    for (let y = 80; y < 180; y += 16) for (let x = 0; x < 320; x += 16)
      rect(x, y, 16, Math.min(16, 180 - y), ((x / 16 + (y - 80) / 16) % 2) ? '#413228' : '#3a2b24');
    // TODO(diseño): el enunciado omite el color de pared; se usa --panel.
    rect(20, 14, 56, 40, '#1a1726'); rect(22, 16, 52, 36, '#1d2b53'); rect(62, 20, 4, 4, '#ffec27');
    [[28,22],[40,30],[50,19],[34,40],[58,44]].forEach(([x,y]) => rect(x,y,1,1,'#fff1e8'));
    rect(110,10,100,50,'#c2c3c7'); rect(112,12,96,46,'#fff1e8');
    rect(292,68,12,12,'#b45a3c'); rect(291,66,14,2,'#8a3f2a');
    [[294,54,3,12],[298,50,3,16],[302,56,3,10]].forEach(r => rect(...r,'#2fbf71'));
    [[296,58,2,8],[300,54,2,10]].forEach(r => rect(...r,'#23a571'));
  }
  function position(name, t) {
    const [dx,dy] = desks[name], s = safeState(name), r = runtime[name];
    let offset = 0;
    if (!motion.matches) {
      if (name === 'agy') offset += Math.round(2 * Math.sin(2 * Math.PI * t / 2000));
      if (s === 'working' || s === 'fixing') offset -= Math.floor((t - r.started) / (s === 'fixing' ? 120 : 200)) % 2;
      if (s === 'celebrate' && t - r.started < 1500) offset += [0,-3,-5,-3,0][Math.floor((t-r.started)/100)%5];
    }
    return [dx + 16, dy - 14 + offset];
  }
  function drawAgent(name, t) {
    const [dx,dy] = desks[name], [px,py] = position(name,t), s = safeState(name), r = runtime[name];
    outlined(dx+17,dy-12,14,10,'#4a3f6b');
    sprite(ctx,faceRows(name,faceFor(name,t)), {...art.palettes.common,...art.palettes[name]},px,py);
    rect(dx-1,dy-1,50,16,'#1a1726'); rect(dx,dy,48,4,'#8a5a3b'); rect(dx,dy+4,48,10,'#6b4430');
    rect(dx+2,dy+14,3,8,'#4a2f22'); rect(dx+43,dy+14,3,8,'#4a2f22');
    outlined(dx+17,dy-5,14,6,'#c2c3c7');
    rect(dx+23,dy-3,2,2,['working','fixing','checks'].includes(s) && Math.floor(t/500)%2 ? '#fff1e8' : accents[name]);
    if (emotes[s]) sprite(ctx,art.emotes[emotes[s]],art.palettes.emote,px+12,py-9 + (!motion.matches && s === 'sleep' ? Math.floor(t/600)%2 : 0));
    if (!motion.matches) {
      const active = ['working','fixing','reviewing'].includes(s);
      if (active && t-r.lastParticle >= 600 && r.particles.length < 3) {
        r.particles.push({x:dx+18+Math.floor(Math.random()*11),born:t}); r.lastParticle=t;
      }
      r.particles = r.particles.filter(p => t-p.born < 14*83);
      for (const p of r.particles) sprite(ctx,art.particles[name],art.palettes.particles[name],p.x,dy-8-Math.floor((t-p.born)/83));
      r.confetti = r.confetti.filter(p => t-p.born < 1000);
      for (const p of r.confetti) {
        const frame = (t-p.born)/83;
        rect(Math.round(p.x+p.vx*frame),Math.round(p.y-2*frame+.125*frame*frame),1,1,p.color);
      }
    }
    const l = layers[name], detail = state.agents[name]?.detail;
    l.bubble.hidden = ['idle','sleep'].includes(s) || !detail;
    if (!l.bubble.hidden) {
      l.bubbleText.textContent = detail;
      const anchor = (px+8)*scale, width = l.bubble.offsetWidth;
      const left = Math.max(0,Math.min(anchor-width/2,canvas.width-width));
      l.bubble.style.left = `${left}px`; l.bubble.style.top = `${(py-12)*scale}px`;
      l.bubble.style.setProperty('--tail',`${Math.max(6,Math.min(width-6,anchor-left))}px`);
    }
    const portrait = document.getElementById(`portrait-${name}`);
    if (portrait) {
      const pc = portrait.getContext('2d'); pc.clearRect(0,0,32,32);
      sprite(pc,faceRows(name,faceFor(name,t)),{...art.palettes.common,...art.palettes[name]},0,0,2);
    }
  }
  let lastFrame = -Infinity;
  function frame(t) {
    if (t-lastFrame >= 83) {
      lastFrame = t; background(); names.forEach(name => drawAgent(name,t));
      output.drawImage(offscreen,0,0,canvas.width,canvas.height);
    }
    requestAnimationFrame(frame);
  }
  const statusMap = {
    running:['--warn','EN CURSO'], 'listo-para-revisar':['--review','REVISIÓN'], ok:['--ok','LISTO'], integrado:['--ok','INTEGRADO'],
    'cuota-agotada':['--err','SIN CUOTA'], descartado:['--muted','DESCARTADO'], 'dry-run':['--muted','DRY-RUN'], 'escalado-a-main':['--claude','ESCALADO']
  };
  function stateColor(s) {
    if (['working','fixing','checks'].includes(s)) return '--warn';
    if (['review','reviewing','waiting'].includes(s)) return '--review';
    if (s === 'celebrate') return '--ok';
    if (['failed','quota'].includes(s)) return '--err';
    return '--muted';
  }
  function pill(text,color) {
    const p = node('span','pill',text); p.style.color = color.startsWith('--') ? `var(${color})` : color; return p;
  }
  function statusPill(status) {
    const [color,label] = statusMap[status] || ['--err',String(status || '').replace(/-/g,' ').toUpperCase()];
    return pill(label,color);
  }
  function render(data) {
    state = {agents: data.agents || {}, runs: data.runs || [], counts: data.counts || {}, stats: data.stats || []};
    const t = performance.now();
    for (const name of names) {
      const r = runtime[name], s = safeState(name);
      if (r.state !== s) {
        r.state = s; r.started = t; r.particles = []; r.confetti = []; r.lastParticle = t;
        if (s === 'celebrate' && !motion.matches) {
          const [x,y] = position(name,t);
          r.confetti = Array.from({length:12},(_,i) => ({x:x+8,y:y-2,vx:Math.random()*2-1,born:t,color:art.confetti[i%art.confetti.length]}));
        }
      }
    }
    canvas.setAttribute('aria-label',`Claude: ${safeState('claude')}. Codex: ${safeState('codex')}. agy: ${safeState('agy')}.`);
    $('running-count').textContent = state.counts.running ?? 0;
    $('review-count').textContent = state.counts.review ?? 0;
    $('merged-count').textContent = state.counts.merged_today ?? 0;
    $('team').replaceChildren(...names.map(name => {
      const row = node('div','team-row'), portrait = node('canvas'); portrait.width=32;portrait.height=32;portrait.id=`portrait-${name}`;portrait.setAttribute('aria-hidden','true');
      const title = node('span','team-name',name === 'agy' ? 'agy' : name[0].toUpperCase()+name.slice(1)); title.style.color=accents[name];
      row.append(portrait,title,pill(safeState(name).toUpperCase(),stateColor(safeState(name)))); return row;
    }));
    const focusRun = document.activeElement?.dataset.runId;
    $('runs').replaceChildren(...(state.runs.length ? state.runs.map(run => {
      const card=node('button','run-card');card.type='button';card.dataset.runId=run.run_id;
      card.style.setProperty('--accent',accents[run.agent] || 'var(--muted)');
      const meta=node('span','run-meta');meta.append(node('span','run-repo',`${run.repo || ''} · ${run.kind || ''}`),statusPill(run.status));
      card.append(node('span','run-task',run.task || run.phase_label || ''),meta);
      card.addEventListener('click',()=>openDetail(run.run_id,card,run.agent));return card;
    }) : [node('p','empty','Sin tareas activas.')]));
    if (focusRun) [...$('runs').children].find(c=>c.dataset.runId===focusRun)?.focus();
    if (!state.stats.length) $('stats').replaceChildren(node('p','empty','Sin datos todavía.'));
    else {
      const table=node('table'), head=node('thead'), hr=node('tr');
      ['agente','tipo','total','1ª %'].forEach(label=>{const th=node('th','',label);th.scope='col';hr.append(th);});head.append(hr);
      const body=node('tbody');
      state.stats.forEach(stat=>{const row=node('tr');[stat.agent,stat.kind,stat.total,`${stat.primera_pct ?? 0}%`].forEach(value=>row.append(node('td','',String(value))));body.append(row);});
      table.append(head,body);$('stats').replaceChildren(table);
    }
  }
  function connection(label,color) {$('connection-text').textContent=label;$('connection').style.color=`var(${color})`;}
  async function poll() {
    try {
      const response=await fetch('/api/state',{cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());connection('EN VIVO','--ok');
    } catch {connection('SIN CONEXIÓN','--err');}
  }
  const overlay=$('modal-overlay'), panel=$('detail-panel'), content=$('detail-content');
  function closeDetail() {
    if (overlay.hidden) return;
    modalRequest++;overlay.hidden=true;document.querySelector('.office').inert=false;
    if (opener?.isConnected) opener.focus();
    else if (opener?.dataset.runId) [...$('runs').children].find(c=>c.dataset.runId===opener.dataset.runId)?.focus();
  }
  $('close-detail').addEventListener('click',closeDetail);
  overlay.addEventListener('click',event=>{if(event.target===overlay)closeDetail();});
  document.addEventListener('keydown',event=>{
    if(overlay.hidden)return;
    if(event.key==='Escape'){event.preventDefault();closeDetail();}
    if(event.key==='Tab') {
      const focusable=[...panel.querySelectorAll('button')];const first=focusable[0],last=focusable[focusable.length-1];
      if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
    }
  });
  function detailView(run) {
    content.replaceChildren(node('div','detail-id',run.run_id || ''));
    const pills=node('div','detail-pills');pills.append(statusPill(run.status),pill(run.agent || '',accents[run.agent] || '--muted'),pill(run.kind || '','--muted'),pill(run.mode || '','--muted'));
    content.append(pills,node('p','',run.repo || ''),node('p','',`Checks: ${run.checks_ok === true ? 'ok' : run.checks_ok === false ? 'fallan' : '—'} · Correcciones: ${run.fix_rounds ?? 0}`));
    const diff=typeof run.diffstat==='object' ? JSON.stringify(run.diffstat) : String(run.diffstat ?? '');content.append(node('p','',diff));
    content.append(node('h2','','Resumen'),node('pre','',run.summary || ''));
    if(run.feedback?.length){const list=node('ul');run.feedback.forEach(value=>list.append(node('li','',typeof value==='string'?value:JSON.stringify(value))));content.append(node('h2','','Feedback'),list);}
    content.append(node('h2','','Comandos'));
    for(const command of run.commands || []) {
      const row=node('div','command-row'), button=node('button','copy-button','COPIAR');button.type='button';
      button.addEventListener('click',async()=>{
        try {await navigator.clipboard.writeText(command);button.textContent='COPIADO';setTimeout(()=>button.textContent='COPIAR',1500);}
        catch {const error=node('p','error','No se pudo copiar el comando.');row.append(error);}
      });row.append(node('code','',command),button);content.append(row);
    }
  }
  async function openDetail(id,trigger,agent) {
    const request=++modalRequest;opener=trigger;panel.style.setProperty('--accent',accents[agent] || 'var(--muted)');
    overlay.hidden=false;document.querySelector('.office').inert=true;$('close-detail').focus();
    // TODO(diseño): texto de carga, fallo al copiar y checks sin resultado no especificados.
    content.replaceChildren(node('p','',id ? 'Cargando…' : 'Sin tarea activa'));
    if(!id)return;
    try {
      let run;
      if(demo) run=demoDetail(id);
      else {
        const response=await fetch(`/api/run/${encodeURIComponent(id)}`,{cache:'no-store'});
        run=await response.json();if(!response.ok)throw new Error(run.error || `HTTP ${response.status}`);
      }
      if(request===modalRequest)detailView(run);
    } catch(error) {if(request===modalRequest)content.replaceChildren(node('p','error',`Error de red: ${error.message}`));}
  }
  const timeline=[
    {codex:['working','Agrega filtro por talla al catálogo'],agy:['working','Tests para utils/precio.ts'],claude:['idle','']},
    {codex:['checks','Ejecutando checks'],agy:['review','Tests para utils/precio.ts'],claude:['reviewing','Revisando tests']},
    {codex:['fixing','corrigiendo (1/3)'],agy:['celebrate','Tests integrados'],claude:['working','trabajando (Edit)']},
    {codex:['review','Agrega filtro por talla al catálogo'],agy:['idle',''],claude:['reviewing','Revisando catálogo']},
    {codex:['celebrate','Filtro integrado'],agy:['quota','Sin cuota disponible'],claude:['waiting','Esperando revisión']},
    {codex:['failed','falló: timeout'],agy:['sleep',''],claude:['fixing','terminando: hero de la landing']}
  ];
  const demoStatus={working:'running',fixing:'running',checks:'running',review:'listo-para-revisar',reviewing:'listo-para-revisar',waiting:'listo-para-revisar',celebrate:'integrado',quota:'cuota-agotada',failed:'timeout',sleep:'descartado',idle:'ok'};
  function demoData() {
    const agents={},runs=[];
    names.forEach(name=>{
      const [s,detail]=timeline[demoStep][name],id=`demo-${name}`;
      agents[name]={state:s,detail,run_id:['idle','sleep'].includes(s)?null:id,since:new Date().toISOString()};
      runs.push({run_id:id,agent:name,kind:name==='agy'?'tests':'feature',mode:'auto',repo:'tienda',status:demoStatus[s],phase:s,phase_label:detail,task:name==='codex'?'Agrega filtro por talla al catálogo':name==='agy'?'Tests para utils/precio.ts':'Hero de la landing',fix_rounds:s==='fixing'?1:0,review_rounds:1,checks_ok:['review','celebrate'].includes(s),diffstat:'3 archivos · +42 −8'});
    });
    runs.push({run_id:'demo-integrado',agent:'codex',kind:'fix',mode:'auto',repo:'tienda',status:'integrado',task:'Corrige cálculo del descuento',checks_ok:true,fix_rounds:0,diffstat:'1 archivo · +8 −2'},
      {run_id:'demo-error',agent:'agy',kind:'tests',mode:'auto',repo:'tienda',status:'checks-fallidos',task:'Valida precios negativos',checks_ok:false,fix_rounds:3,diffstat:'2 archivos · +18 −4'},
      {run_id:'demo-descartado',agent:'claude',kind:'feature',mode:'dry-run',repo:'tienda',status:'descartado',task:'Explora navegación',checks_ok:null,fix_rounds:0,diffstat:''});
    return {agents,runs,counts:{running:runs.filter(r=>r.status==='running').length,review:runs.filter(r=>r.status==='listo-para-revisar').length,merged_today:runs.filter(r=>r.status==='integrado').length},stats:names.map(name=>({agent:name,kind:name==='agy'?'tests':'feature',total:8,integrado:6,primera_pct:75,descartado:1,escalado:1}))};
  }
  function demoDetail(id) {
    const run=state.runs.find(run=>run.run_id===id);
    if(!run)throw new Error('Corrida no encontrada');
    return {...run,summary:['Tarea: '+run.task,'Repositorio: '+run.repo,'Se revisó la implementación existente.','Se actualizaron los archivos de la tarea.','Se verificaron los casos principales.','Checks: '+(run.checks_ok?'ok':'pendientes o fallidos'),'Diff: '+run.diffstat,'Estado: '+run.status].join('\n'),feedback:['Revisar los cambios antes de integrar.'],commands:[`ai-delegate show ${id}`,`ai-delegate review ${id}`]};
  }
  motion.addEventListener('change',()=>names.forEach(name=>{runtime[name].particles=[];runtime[name].confetti=[];}));
  new ResizeObserver(resize).observe(scene.parentElement);
  resize();render(state);requestAnimationFrame(frame);
  if(demo){connection('DEMO','--review');render(demoData());setInterval(()=>{demoStep=(demoStep+1)%timeline.length;render(demoData());},4000);}
  else {poll();setInterval(poll,2000);}
})();
