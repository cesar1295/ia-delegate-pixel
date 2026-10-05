'use strict';
(() => {
  const art = window.PIXEL_ART;
  const params = new URLSearchParams(location.search);
  const demo = params.get('demo') === '1';
  const demoMain = ['codex', 'agy'].includes(params.get('maestra')) ? params.get('maestra') : 'claude';
  const $ = id => document.getElementById(id);
  const canvas = $('office-canvas');
  let names = [], state = {agents: {}, runs: [], counts: {}, stats: []};
  const accents = {claude: '#d97757', codex: '#3ddc97', agy: '#7b8cff'};
  const known = new Set(['idle', 'sleep', 'drawing', 'working', 'fixing', 'checks', 'review', 'reviewing', 'waiting',
    'failed', 'quota', 'celebrate']);
  const safeState = name => known.has(state.agents[name]?.state) ? state.agents[name].state : 'idle';
  let modalRequest = 0, opener = null, demoStep = 0, firstEvents = true;
  const seen = new Set(), cache = {};
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  function formatTime(s) {
    if (s == null) return 'sin dato';
    const sec = Math.round(Number(s));
    if (sec >= 3600) {
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      return `${h} h ${m} min`;
    }
    if (sec >= 60) return `${Math.floor(sec / 60)} min`;
    return `${sec} s`;
  }
  function formatTokens(t) {
    if (t == null) return 'sin dato';
    const num = Number(t);
    if (num >= 1000000) {
      const m = num / 1000000;
      return `${m % 1 === 0 ? m.toFixed(0) : m.toFixed(1).replace(/\.0$/, '')} M`;
    }
    if (num >= 1000) {
      const k = num / 1000;
      if (k >= 100 || k % 1 === 0 || num % 1000 === 0) return `${Math.round(k)} k`;
      return `${k.toFixed(1).replace(/\.0$/, '')} k`;
    }
    return String(num);
  }
  function formatHHMM(ts) {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      if (!isNaN(d.getTime())) {
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
      }
    } catch {}
    const match = String(ts).match(/T?(\d{2}:\d{2})/);
    return match ? match[1] : '';
  }
  function sprite(context, rows, palette, x, y, factor = 1) {
    rows.forEach((row, ry) => [...row].forEach((pixel, rx) => {
      if (pixel !== '.' && palette[pixel]) {
        context.fillStyle = palette[pixel]; context.fillRect(x + rx * factor, y + ry * factor, factor, factor);
      }
    }));
  }
  function faceRows(name, face) {
    const rows = art.characters[art.characters[name] ? name : 'generic'].map(row => [...row]);
    for (const [y, line] of Object.entries(art.faces[face])) {
      [...line].forEach((pixel, x) => {if (pixel !== '_') rows[Number(y)][art.faceOriginCol + x] = pixel;});
    }
    return rows.map(row => row.join(''));
  }
  const statusMap = {
    running:['--warn','EN CURSO'], 'listo-para-revisar':['--review','REVISIÓN'], ok:['--ok','LISTO'],
    integrado:['--ok','INTEGRADO'],
    'sin-cambios':['--err','SIN CAMBIOS'], 'cuota-agotada':['--err','SIN CUOTA'], descartado:['--muted',
    'DESCARTADO'], 'dry-run':['--muted','DRY-RUN'], 'escalado-a-main':['--muted','ESCALADO']
  };
  function stateColor(s) {
    if (['working','fixing','checks'].includes(s)) return '--warn';
    if (['drawing','review','reviewing','waiting'].includes(s)) return '--review';
    if (s === 'celebrate') return '--ok';
    if (['failed','quota'].includes(s)) return '--err';
    return '--muted';
  }
  function pill(text,color) {
    const p = node('span','pill',text); p.style.color = color.startsWith('--') ? `var(${color})` : color; return p;
  }
  function statusPill(status) {
    const [color,label] = statusMap[status] || ['--err',String(status || '').replace(/-/g,' ').toUpperCase()];
    const main = names.find(name => state.agents[name].role === 'main');
    return pill(label, status === 'escalado-a-main' && main ? accents[main] : color);
  }
  function render(data) {
    const agents = Array.isArray(data.agents) ? data.agents : [];
    state = {agents: Object.fromEntries(agents.map(agent => [agent.name,agent])),
      runs: data.runs || [], counts: data.counts || {}, stats: data.stats || []};
    names = agents.map(agent => agent.name);
    agents.forEach(agent => { accents[agent.name] = agent.color; });
    if (data.ui) engine.setConfig({ui: data.ui});
    engine.update(agents);
    for (const event of data.events || []) {
      if (!seen.has(event.id) && !firstEvents) engine.enqueue(event);
      seen.add(event.id);
    }
    firstEvents = false;
    canvas.setAttribute('aria-label',names.map(name => {
      const agent = state.agents[name], pct = agent.quota?.remaining_pct;
      return `${agent.display}: ${stateLabels[safeState(name)].toLowerCase()}, cuota ${pct == null ? '?' : pct+'%'}`;
    }).join('. '));
    $('running-count').textContent = state.counts.running ?? 0;
  $('review-count').textContent = state.counts.review ?? 0;
  $('merged-count').textContent = state.counts.merged_today ?? 0;
  window.officePanels?.counts(state.counts);
  if (changed('team',agents)) $('team').replaceChildren(...names.map(name => {
    const agent = state.agents[name], row = node('div','team-row'), portrait = node('canvas','portrait');
    portrait.width=32; portrait.height=32; portrait.id=`portrait-${name}`;
    portrait.setAttribute('aria-hidden','true');
    sprite(portrait.getContext('2d'), faceRows(name, 'base'), palette(name), 0, 0, 2);
    const info = node('div','team-info'), heading = node('div','team-heading');
    const title = node('span','team-name',agent.display.toUpperCase()); title.style.color=agent.color;
    heading.append(title,pill(stateLabels[safeState(name)],stateColor(safeState(name))));
    info.append(heading);
    if (agent.detail) info.append(node('div','team-detail',agent.detail));
    if (agent.role === 'main' && agent.pending) {
      // TODO(diseño): presentar .team-pending en --warn con IBM Plex Mono 11px.
      const hhmm = formatHHMM(agent.pending.since);
      const pendingEl = node('button', 'team-pending', `⚠ escalada pendiente desde ${hhmm}: ${agent.pending.task}`);
      pendingEl.type = 'button';
      pendingEl.addEventListener('click', () => openDetail(agent.pending.run_id, pendingEl, agent.name));
      info.append(pendingEl);
    }
    info.append(quotaBar(agent));
    const timeText = (!agent.time || agent.time.today_s == null)
      ? '⏱ sin dato'
      : `⏱ hoy ${formatTime(agent.time.today_s)} · semana ${formatTime(agent.time.week_s)}`;
    info.append(node('div', 'team-time', timeText));
    if (agent.images_today > 0) info.append(node('div', 'team-time', `🖼 ${agent.images_today} imágenes hoy`));
    if (agent.usage && agent.usage.tokens_today != null) {
      const tokensFormatted = formatTokens(agent.usage.tokens_today);
      const usageText = agent.role === 'main'
        ? `≈ ${tokensFormatted} tokens hoy`
        : `≈ ${tokensFormatted} tokens hoy · ${agent.usage.rounds_today ?? 0} rondas`;
      info.append(node('div', 'team-tokens', usageText));
    }
    if (agent.subagents?.length) info.append(node('div','subagent-count',`${agent.subagents.length} subagentes`));
    row.append(portrait,info); return row;
  }));
    if (changed('runs',state.runs)) {
      const focusRun = document.activeElement?.dataset.runId;
      $('runs').replaceChildren(...(state.runs.length ? state.runs.slice(0,12).map(run => {
        const card=node('button','run-card');card.type='button';card.dataset.runId=run.run_id;
        card.style.setProperty('--accent',accents[run.agent] || 'var(--muted)');
        const meta=node('span','run-meta');meta.append(node('span','run-repo',
        `${run.repo || ''} · ${run.kind || ''}`),statusPill(run.status));
        card.append(node('span','run-task',run.task || run.phase_label || ''),meta);
        card.addEventListener('click',()=>openDetail(run.run_id,card,run.agent));return card;
      }) : [node('p','empty','Todavía no hay tareas. Delega una con ai-delegate.')]));
      if (focusRun) [...$('runs').children].find(c=>c.dataset.runId===focusRun)?.focus();
    }
    if (changed('stats', [state.stats, names.map(n => [n, state.agents[n].time, state.agents[n].usage])])) {
      const container = $('stats');
      const children = [];
      if (!state.stats.length) {
        children.push(node('p','empty','Sin datos todavía.'));
      } else {
        const table=node('table'), head=node('thead'), hr=node('tr');
        ['agente','tipo','total','1ª %'].forEach(label=>{const th=node('th','',label);th.scope='col';
          hr.append(th);});head.append(hr);
        const body=node('tbody');
        state.stats.forEach(stat=>{const row=node('tr');[stat.agent,stat.kind,stat.total,
          `${stat.primera_pct ?? 0}%`].forEach(value=>row.append(node('td','',String(value))));body.append(row);});
        table.append(head,body);
        children.push(table);
      }

      const timeHeading = node('h2', '', 'Tiempo');
      timeHeading.style.marginTop = '16px';
      const timeTable = node('table'), tHead = node('thead'), tHr = node('tr');
      ['IA', 'hoy', 'semana', 'total', 'tokens hoy'].forEach(label => {
        const th = node('th', '', label); th.scope = 'col';
        tHr.append(th);
      });
      tHead.append(tHr);
      const tBody = node('tbody');
      names.forEach(name => {
        const agent = state.agents[name];
        const tr = node('tr');
        const iaName = agent.display || name;
        const today = formatTime(agent.time?.today_s);
        const week = formatTime(agent.time?.week_s);
        const total = formatTime(agent.time?.total_s);
        const tokensToday = formatTokens(agent.usage?.tokens_today);
        [iaName, today, week, total, tokensToday].forEach(val => tr.append(node('td', '', String(val))));
        tBody.append(tr);
      });
      timeTable.append(tHead, tBody);
      children.push(timeHeading, timeTable);
      container.replaceChildren(...children);
    }
  }
  function connection(label,color) {$('connection-text').textContent=label;$('connection').style.color=`var(${color})`;}
  async function poll() {
    if (demo) return;
    let data;
    try {
      const response = await fetch('/api/state', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      data = await response.json();
    } catch {
      connection('SIN CONEXIÓN', '--err');
      return;
    }
    try {
      render(data);
      connection('EN VIVO', '--ok');
    } catch (err) {
      console.error(err);
      connection('ERROR DE INTERFAZ', '--warn');
    }
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
    const pills=node('div','detail-pills');pills.append(statusPill(run.status),pill(run.agent || '',
    accents[run.agent] || '--muted'),pill(run.kind || '','--muted'),pill(run.mode || '','--muted'));
    content.append(pills,node('p','',run.repo || ''),node('p','',
    `Checks: ${run.checks_ok === true ? 'ok' : run.checks_ok === false ? 'fallan' : 'sin checks'}`
    + ` · Correcciones: ${run.fix_rounds ?? 0}`));
    if (run.checks_ok == null) content.lastChild.classList.add('empty');
    const diff=typeof run.diffstat==='object' ? JSON.stringify(run.diffstat) : String(run.diffstat ?? '');
    content.append(node('p','',diff));
    content.append(node('h2','','Resumen'),node('pre','',run.summary || ''));
    if(run.feedback?.length){const list=node('ul');run.feedback.forEach(value=>list.append(node('li','',
      typeof value==='string'?value:JSON.stringify(value))));content.append(node('h2','','Feedback'),list);}
    content.append(node('h2','','Comandos'));
    for(const command of run.commands || []) {
      const row=node('div','command-row'), button=node('button','copy-button','COPIAR');button.type='button';
      button.addEventListener('click',async()=>{
        try {await navigator.clipboard.writeText(command);button.textContent='COPIADO';
          setTimeout(()=>button.textContent='COPIAR',1500);}
        catch {button.textContent='NO SE PUDO';button.classList.add('error');
          setTimeout(()=>{button.textContent='COPIAR';button.classList.remove('error');},1500);}
      });row.append(node('code','',command),button);content.append(row);
    }
  }
  async function openDetail(id,trigger,agent) {
    const request=++modalRequest;opener=trigger;panel.style.setProperty('--accent',accents[agent] || 'var(--muted)');
    overlay.hidden=false;document.querySelector('.office').inert=true;$('close-detail').focus();
    content.replaceChildren(node('p',id ? 'loading' : '',id ? 'CARGANDO…' : 'Sin tarea activa'));
    if(!id)return;
    try {
      let run;
      if(demo) run=demoDetail(id);
      else {
        const response=await fetch(`/api/run/${encodeURIComponent(id)}`,{cache:'no-store'});
        run=await response.json();if(!response.ok)throw new Error(run.error || `HTTP ${response.status}`);
      }
      if(request===modalRequest)detailView(run);
    } catch(error) {if(request===modalRequest)content.replaceChildren(node('p','error',
      `Error de red: ${error.message}`));}
  }
  const stateLabels = {idle:'LIBRE',sleep:'DORMIDO',drawing:'DIBUJANDO',working:'TRABAJANDO',fixing:'CORRIGIENDO',
    checks:'CHECKS',review:'POR REVISAR',reviewing:'REVISANDO',waiting:'ESPERANDO',failed:'FALLÓ',
    quota:'SIN CUOTA',celebrate:'¡LISTO!'};
  function changed(key,value) {
    const json=JSON.stringify(value);
    if (cache[key]===json) return false;
    cache[key]=json; return true;
  }
  function blend(color,target,amount) {
    const value=parseInt(color.slice(1),16), end=parseInt(target.slice(1),16);
    return '#'+[16,8,0].map(shift => Math.round(((value>>shift)&255)*(1-amount)
    +((end>>shift)&255)*amount).toString(16).padStart(2,'0')).join('');
  }
  function palette(name) {
    const agent=state.agents[name], common=art.palettes.common;
    if (art.characters[name]) return {...common,...art.palettes[name],...art.palettes.pants[name]};
    const color=agent.look?.color || agent.color;
    return {...common,h:agent.look?.hair || '#3a3a48',c:color,C:blend(color,'#000000',.25),
      a:blend(color,'#ffffff',.45),r:common.s,p:'#3a3a48',P:'#2a2a36'};
  }
  function quotaColor(pct) {return art.palettes.mug_fill[pct>=50?'high':pct>=20?'mid':'low'];}
  function quotaLines(agent) {
    const quota=agent.quota;
    const lines=[];
    if (!quota || quota.remaining_pct==null) {
      lines.push('sin dato de cuota');
    } else {
      if (quota.estimated) lines.push('estimado');
      for (const window of quota.windows || []) {
        const date=window.resets_at ? new Date(window.resets_at) : null;
        const reset=date ? date.toLocaleString('es',{...(date.toDateString()===new Date().toDateString()
          ? {hour:'2-digit',minute:'2-digit'} : {day:'numeric',month:'short'})}) : '?';
        lines.push(`${window.label}: queda ${window.used_pct==null?'?':100-window.used_pct}% · reinicia ${reset}`);
      }
    }
    if (agent.usage && agent.usage.tokens_today != null) {
      lines.push(`uso: ${formatTokens(agent.usage.tokens_today)} tokens hoy`);
    }
    if (agent.time && agent.time.today_s != null) {
      lines.push(`tiempo hoy: ${formatTime(agent.time.today_s)}`);
    }
    return lines.length ? lines : ['sin dato de cuota', '?'];
  }
  function quotaBar(agent) {
    const row=node('div','quota-row'), bar=node('div','quota-bar'), quota=agent.quota;
    const pct=quota?.remaining_pct;
    for (let i=0;i<10;i++) {
      const segment=node('span');
      segment.style.background=pct!=null && i<Math.round(pct/10)?quotaColor(pct):'var(--line)';
      bar.append(segment);
    }
    if (quota?.stale) {
      bar.style.opacity = '0.5';
    }
    let valueText = 'SIN DATO';
    if (pct != null) {
      valueText = `${quota.estimated?'~':''}${pct}%`;
    } else if (agent.usage && agent.usage.tokens_today != null) {
      valueText = `USO: ${formatTokens(agent.usage.tokens_today).toUpperCase()} HOY`;
    }
    row.append(bar,node('span','quota-value',valueText));
    if (quota?.stale && quota?.ts) {
      const minutes = Math.max(1, Math.round((Date.now() - new Date(quota.ts).getTime()) / 60000));
      row.append(node('span','quota-reset',`(hace ${minutes} min)`));
    } else {
      const window=(quota?.windows || []).filter(w=>w.used_pct!=null && w.resets_at)
        .sort((a,b)=>b.used_pct-a.used_pct)[0];
      if (window) {
        const minutes=Math.max(0,Math.ceil((new Date(window.resets_at)-Date.now())/60000));
        row.append(node('span','quota-reset',`reinicia en ${Math.floor(minutes/60)} h ${minutes%60} min`));
      }
    }
    return row;
  }
  const demoEvents = [];
  function demoData() {
    const resets = new Date(Date.now()+7980000).toISOString();
    const agents = [
    {name:'claude',display:'Claude',color:'#d97757',role:'main'},
    {name:'codex',display:'Codex',color:'#3ddc97',role:'agent'},
    {name:'agy',display:'agy',color:'#7b8cff',role:'agent'},
    {name:'opencode',display:'OpenCode',color:'#f0a500',role:'agent',
      look:{hair:'#2e5d4b',color:'#f0a500'}}
    ];
    agents.forEach(agent => {
      agent.role = agent.name === demoMaster ? 'main' : 'agent';
    });
    agents.sort((a, b) => Number(b.role === 'main') - Number(a.role === 'main'));
    agents.forEach(agent => {
      agent.state = agent.role === 'main' ? 'waiting' : 'working';
      agent.detail = agent.role === 'main' ? 'esperando a Alex' : 'Implementando tarea';
      agent.run_id = `demo-${agent.name}`; agent.subagents = [];
      agent.quota = null;
    });
    const claudeAgent = agents.find(a => a.name === 'claude');
    if (claudeAgent) {
      claudeAgent.quota = {remaining_pct:77,estimated:false,stale:false,ts:new Date().toISOString(),windows:[
        {label:'5 h',used_pct:23.0,resets_at:resets},{label:'7 d',used_pct:8.0,resets_at:resets}]};
      claudeAgent.usage = {tokens_5h:450000,tokens_today:2400000,tokens_week:9800000,rounds_today:0};
      claudeAgent.time = {today_s:4320,week_s:24000,total_s:86400};
    }
    const codexAgent = agents.find(a => a.name === 'codex');
    if (codexAgent) {
      codexAgent.quota = {remaining_pct:93,estimated:false,windows:[
        {label:'5 h',used_pct:7.0,resets_at:resets},{label:'7 d',used_pct:1.0,resets_at:resets}]};
      codexAgent.usage = {tokens_5h:220000,tokens_today:1200000,tokens_week:4300000,rounds_today:34};
      codexAgent.time = {today_s:2100,week_s:8100,total_s:36300};
    }
    const agyAgent = agents.find(a => a.name === 'agy');
    if (agyAgent) {
      agyAgent.quota = {source:'budget',remaining_pct:null,estimated:true,windows:[
        {label:'hoy: 850000 tokens',used_pct:null,resets_at:null}]};
      agyAgent.usage = {tokens_5h:150000,tokens_today:850000,tokens_week:2100000,rounds_today:18};
      agyAgent.time = {today_s:40,week_s:300,total_s:1800};
    }
    const opencodeAgent = agents.find(a => a.name === 'opencode');
    if (opencodeAgent) {
      opencodeAgent.quota = {remaining_pct:50,estimated:true,windows:[]};
      opencodeAgent.usage = {tokens_5h:50000,tokens_today:920,tokens_week:5000,rounds_today:2};
      opencodeAgent.time = {today_s:30,week_s:120,total_s:400};
    }
    if (demoStep >= 1 && demoStep < 5 && claudeAgent) claudeAgent.subagents = [{label:'Revisión'},{label:'Análisis'}];
    if (demoStep >= 2 && codexAgent) codexAgent.subagents = [{label:'Checks'}];
    if (demoStep === 3 && agyAgent) {
      agyAgent.state = 'drawing'; agyAgent.detail = 'generando imágenes'; agyAgent.images_today = 3;
    }
    if (demoStep >= 4 && agyAgent) {
      agyAgent.state = 'quota';
    }
    if (demoStep === 6) {
      if (codexAgent) { codexAgent.state='celebrate'; codexAgent.detail='¡integrado!'; }
      if (agyAgent) { agyAgent.state='quota'; }
    }
    if (demoStep >= 2 && opencodeAgent) { opencodeAgent.state = 'idle'; opencodeAgent.since = new Date(Date.now()-130000).toISOString(); }
    if (demoConfig) {
      agents.forEach(agent => {
        const config = demoConfig.agents[agent.name];
        if (config) { agent.display = config.display; agent.color = config.color; }
        if (agent.role === 'main') agent.detail = `esperando a ${demoConfig.user_name}`;
      });
    }
    const runs = agents.map(agent => ({run_id:agent.run_id,agent:agent.name,kind:'feature',mode:'write',
      repo:'tienda',task:agent.detail,status:agent.state==='celebrate'?'integrado':'running',checks_ok:true}));
    runs.push({run_id:'demo-read',agent:'agy',kind:'tests',mode:'read',repo:'tienda',
      task:'Revisar precios',status:'listo-para-revisar',checks_ok:null});
    return {agents,runs,events:demoEvents,counts:{running:3,review:1,merged_today:demoStep===6?1:0},
      stats:agents.map(agent => ({agent:agent.name,kind:'feature',total:8,primera_pct:75}))};
  }
  function demoDetail(id) {
    const run=state.runs.find(run=>run.run_id===id);
    if (!run) throw new Error('Corrida no encontrada');
    return {...run,summary:[run.task,run.repo,'Implementación revisada.','Archivos actualizados.',
      'Casos verificados.','Checks: ok','Diff: +42 −8',run.status].join('\n'),
      feedback:['Revisar los cambios antes de integrar.'],
      commands:['diff','feedback','merge','discard'].map(command => `ai-delegate ${command} ${id}`)};
  }

  let demoConfig = null;
  const engine = new window.OfficeEngine({palette, faceRows, openDetail, quotaLines, quotaColor});
  window.officePanels = new window.OfficePanels({demo, node, agents: () => Object.values(state.agents),
    onConfig: config => {
      engine.setConfig(config);
      if (demo) { demoConfig = config; render(demoData()); }
    }, onMaster: name => {
      if (demo) { demoMaster = name; render(demoData()); }
      else poll();
    }});
  let demoMaster = demoMain;
  window.render = render;
  render({agents:[]});
  firstEvents = true;
  let pollTimer;
  async function schedulePoll() {
    await poll();
    pollTimer = setTimeout(schedulePoll, document.hidden ? 10000 : 2000);
  }
  document.addEventListener('visibilitychange', () => {
    engine.visibility();
    if (!demo) { clearTimeout(pollTimer); schedulePoll(); }
  });
  if (demo) {
    connection('DEMO','--review'); render(demoData());
    setInterval(() => {
      demoStep=demoStep%6+1;
      const types=['assigned','assigned','delivered','feedback','delivered','merged'];
      const worker = demoMaster === 'codex' ? 'claude' : 'codex';
      const other = demoMaster === 'agy' ? 'claude' : 'agy';
      const targets=[worker,'opencode',other,worker,worker,worker];
      demoEvents.push({id:demoEvents.length+1,type:types[demoStep-1],agent:targets[demoStep-1]});
      render(demoData());
    },5000);
  } else {
    schedulePoll();
  }
})();
