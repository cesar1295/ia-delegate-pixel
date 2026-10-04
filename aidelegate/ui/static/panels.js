'use strict';
(() => {
  class OfficePanels {
    constructor(api) {
      this.api = api;
      this.root = document.getElementById('settings');
      this.tabs = [...document.querySelectorAll('[data-tab]')];
      this.wide = matchMedia('(min-width: 1100px)');
      this.active = this.wide.matches ? 'team' : null;
      this.config = null;
      this.changes = {};
      this.fields = new Map();
      this.tabs.forEach(button => button.onclick = () => this.open(button.dataset.tab, true));
      document.getElementById('settings-open').onclick = () => this.open('settings');
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !this.wide.matches) this.open(null);
      });
      this.wide.addEventListener('change', () => {
        if (this.wide.matches && !this.active) this.active = 'team';
        this.show();
      });
      this.show();
    }
    counts(counts) {
      document.getElementById('sheet-counts').textContent =
        `EN CURSO ${counts.running ?? 0} · REVISIÓN ${counts.review ?? 0} · HOY ${counts.merged_today ?? 0}`;
    }
    open(tab, toggle = false) {
      if (toggle && !this.wide.matches && this.active === tab) tab = null;
      this.active = tab;
      this.show();
      if (tab === 'settings') this.load();
    }
    show() {
      document.getElementById('side-panel').classList.toggle('sheet-open', Boolean(this.active));
      this.tabs.forEach(button => {
        const active = button.dataset.tab === this.active;
        button.classList.toggle('active', active);
        button.setAttribute('aria-expanded', String(active));
        document.getElementById(`${button.dataset.tab}-panel`).hidden = !active;
      });
    }
    fakeConfig() {
      return {main: this.api.agents().find(a => a.role === 'main')?.name || 'claude', user_name: 'Alex',
        ui: {time_mode: 'auto', fixed_hour: 12}, strategy: {mode: 'agy-first', first: 'agy', then: 'codex',
          escalate_after: 3, quota_floor_pct: 15},
        limits: {max_fix_rounds: 3, max_review_rounds: 2, timeout_min: 30, keep_days: 7},
        routing: {feature: 'codex', bugfix: 'codex', test: 'agy', docs: 'agy', security: 'main'},
        agents: Object.fromEntries(this.api.agents().map(a => [a.name,
          {display: a.display, color: a.color, enabled: true, model: '', daily_token_budget: 0}]))};
    }
    async load() {
      if (this.loading || (this.config && Object.keys(this.changes).length)) return;
      this.loading = true;
      this.root.replaceChildren(this.api.node('p', 'loading', 'CARGANDO…'));
      try {
        let data;
        if (this.api.demo) data = {config: this.demoConfig || this.fakeConfig(),
          detected: this.api.agents().map(a => ({name: a.name, installed: true, version: 'demo', session: true}))};
        else {
          const response = await fetch('/api/config', {cache: 'no-store'});
          if (response.status === 404) {
            this.config = null;
            this.fields.clear();
            this.root.replaceChildren(this.api.node('p', 'empty',
              'Actualiza ai-delegate para editar la configuración desde aquí.'));
            return;
          }
          data = await response.json();
          if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        }
        this.config = data.config;
        this.kinds = data.kinds || Object.keys(this.config.routing || {});
        this.detected = data.detected || data.detections || [];
        if (!Array.isArray(this.detected)) {
          this.detected = Object.entries(this.detected).map(([name, info]) => ({name, ...info}));
        }
        this.changes = {};
        this.api.onConfig(this.config);
        this.render();
      } catch (error) { this.root.replaceChildren(this.api.node('p', 'error', `Error de red: ${error.message}`)); }
      finally { this.loading = false; }
    }
    get(path) { return path.split('.').reduce((value, part) => value?.[part], this.config); }
    set(target, path, value) {
      const parts = path.split('.');
      const leaf = parts.pop();
      let current = target;
      for (const part of parts) current = current[part] ||= {};
      current[leaf] = value;
    }
    section(title) {
      const section = this.api.node('section', 'settings-section');
      section.append(this.api.node('h2', '', title));
      this.form.append(section);
      return section;
    }
    field(parent, title, path, type = 'text', options = {}) {
      const {node} = this.api;
      const wrapper = node('div', 'setting-field');
      const label = node('label', '', title.toUpperCase());
      const input = document.createElement(type === 'select' ? 'select' : 'input');
      input.id = `setting-${path.replaceAll('.', '-')}`;
      input.name = path;
      label.htmlFor = input.id;
      if (type === 'select') {
        for (const [value, text] of options.choices || []) {
          const option = node('option', '', text);
          option.value = value;
          input.append(option);
        }
      } else input.type = type;
      if (type === 'checkbox') { input.className = 'setting-switch'; input.checked = this.get(path) !== false; }
      else input.value = this.get(path) ?? options.default ?? '';
      if (type === 'number') {
        if (options.min !== undefined) input.min = options.min;
        if (options.max !== undefined) input.max = options.max;
        input.step = '1';
      }
      if (options.placeholder) input.placeholder = options.placeholder;
      const error = node('div', 'field-error');
      error.id = `${input.id}-error`;
      error.hidden = true;
      input.setAttribute('aria-describedby', error.id);
      input.addEventListener('input', () => {
        const value = type === 'checkbox' ? input.checked
          : type === 'number' || path === 'ui.fixed_hour' ? Number(input.value) : input.value;
        if (value === (this.get(path) ?? options.default ?? (type === 'checkbox' ? true : ''))) {
          delete this.changes[path];
        } else this.changes[path] = value;
        input.removeAttribute('aria-invalid');
        error.hidden = true;
        this.save.disabled = !Object.keys(this.changes).length;
        this.status.textContent = '';
        if (path === 'ui.time_mode') {
          const hour = this.fields.get('ui.fixed_hour');
          hour.input.disabled = value !== 'fixed';
          hour.wrapper.hidden = value !== 'fixed';
        }
      });
      wrapper.append(label, input);
      if (options.suffix) wrapper.append(node('span', '', options.suffix));
      wrapper.append(error);
      parent.append(wrapper);
      this.fields.set(path, {input, error, wrapper});
      return input;
    }
    button(title, cls = 'secondary') {
      const button = this.api.node('button', cls, title);
      button.type = 'button';
      return button;
    }
    render() {
      const {node} = this.api;
      this.fields.clear();
      this.form = node('form', 'settings-form');
      this.form.addEventListener('submit', event => { event.preventDefault(); this.submit(); });
      this.root.replaceChildren(this.form);
      const general = this.section('General');
      this.field(general, 'Tu nombre', 'user_name');
      this.field(general, 'Hora de la oficina', 'ui.time_mode', 'select',
        {default: 'auto', choices: [['auto', 'Automática'], ['fixed', 'Fija']]});
      const hour = this.field(general, 'Hora', 'ui.fixed_hour', 'select',
        {default: 12, choices: Array.from({length: 24}, (_, i) => [String(i), String(i)])});
      hour.disabled = this.get('ui.time_mode') !== 'fixed';
      this.fields.get('ui.fixed_hour').wrapper.hidden = hour.disabled;
      const master = typeof this.config.main === 'object' ? this.config.main.name : this.config.main;
      const agents = Object.entries(this.config.agents || {});
      const detectedAgents = [...agents];
      for (const detected of this.detected) {
        if (!detectedAgents.some(([name]) => name === detected.name)) {
          const agent = this.api.agents().find(agent => agent.name === detected.name) || {};
          detectedAgents.push([detected.name, agent]);
        }
      }
      const agentChoices = agents.map(([name, a]) => [name, a.display || name]);
      const choices = agentChoices.filter(([name]) => name !== master);
      const masterSection = this.section('IA maestra');
      for (const [name, agent] of detectedAgents) {
        const detected = this.detected.find(d => d.name === name);
        const card = node('div', 'settings-card');
        if (name === master) card.classList.add('is-master');
        const title = node('span', 'team-name', agent.display || name);
        title.style.color = agent.color;
        card.append(title);
        if (name === master) card.append(node('span', 'pill', 'MAESTRA'));
        const installed = detected?.installed ?? (detected && 'path' in detected ? Boolean(detected.path) : true);
        const session = detected?.session ?? detected?.logged_in;
        if (!installed) {
          card.classList.add('not-installed');
          card.append(node('p', '', 'NO INSTALADA'));
        }
        else {
          card.append(node('p', 'empty', `Versión: ${detected?.version || '?'} · Sesión: `
            + (session === true ? 'sí' : session === false ? 'no' : 'desconocida')));
          if (name !== master) {
            const change = this.button('HACER MAESTRA');
            change.onclick = () => this.changeMaster(name, agent.display || name, change);
            card.append(change);
          }
        }
        masterSection.append(card);
      }
      const distribution = this.section('Reparto');
      this.field(distribution, 'Estrategia', 'strategy.mode', 'select',
        {default: 'agy-first', choices: [['agy-first', 'Agy primero'], ['routing', 'Por tipo de tarea']]});
      this.field(distribution, 'Programa primero', 'strategy.first', 'select', {choices: agentChoices});
      this.field(distribution, 'Si no puede', 'strategy.then', 'select', {choices: agentChoices});
      this.field(distribution, 'Correcciones antes de escalar', 'strategy.escalate_after', 'number', {min: 1, max: 10});
      this.field(distribution, 'Cambiar de agente si la cuota baja de', 'strategy.quota_floor_pct', 'number',
        {default: 15, min: 0, max: 90, suffix: '%'});
      const agentSection = this.section('Agentes');
      for (const [name, agent] of agents.filter(([name]) => name !== master)) {
        const card = node('div', 'settings-card');
        const title = node('div', 'team-name', agent.display || name);
        title.style.color = agent.color;
        card.append(title);
        agentSection.append(card);
        this.field(card, 'Activo', `agents.${name}.enabled`, 'checkbox');
        this.field(card, 'Nombre visible', `agents.${name}.display`);
        this.field(card, 'Color', `agents.${name}.color`, 'color');
        this.field(card, 'Modelo', `agents.${name}.model`, 'text', {placeholder: 'Predeterminado'});
        if (name === 'agy') this.field(card, 'Presupuesto diario de tokens',
          `agents.${name}.daily_token_budget`, 'number', {min: 0, default: 0});
      }
      const kinds = this.section('Tipos de tarea'), table = node('table'), body = node('tbody');
      const head = node('thead'), row = node('tr');
      row.append(node('th', '', 'tipo'), node('th', '', 'agente'));
      head.append(row);
      for (const kind of this.kinds || Object.keys(this.config.routing || {})) {
        const row = node('tr'), control = node('td');
        row.append(node('td', '', kind), control);
        this.field(control, kind, `routing.${kind}`, 'select', {choices: [...choices, ['main', 'Maestra']]});
        body.append(row);
      }
      table.append(head, body);
      kinds.append(table);
      const limits = this.section('Límites');
      this.field(limits, 'Minutos por ronda', 'limits.timeout_min', 'number', {min: 1, max: 240});
      this.field(limits, 'Rondas de revisión', 'limits.max_review_rounds', 'number', {min: 1, max: 10});
      this.field(limits, 'Días de historial', 'limits.keep_days', 'number', {min: 1, max: 90});
      const connections = this.section('Conexiones'), doctor = this.button('PROBAR CONEXIONES');
      const results = node('div', 'doctor-results');
      results.setAttribute('aria-live', 'polite');
      doctor.onclick = () => this.doctor(doctor, results);
      connections.append(doctor, results);
      const footer = node('div', 'settings-footer');
      this.save = this.button('GUARDAR CAMBIOS', 'primary');
      this.save.type = 'submit';
      this.save.disabled = true;
      this.status = node('div', 'settings-status');
      this.status.setAttribute('role', 'status');
      footer.append(this.save, this.status);
      this.form.append(footer);
    }
    async request(path, body) {
      const token = document.querySelector('meta[name="ai-delegate-token"]')?.content || '';
      const response = await fetch(path, {method: 'POST', headers:
        {'Content-Type': 'application/json', 'X-AI-Delegate-Token': token}, body: JSON.stringify(body)});
      let data;
      try { data = await response.json(); } catch { data = {}; }
      if (!response.ok) {
        const error = new Error(response.status === 403 ? 'La sesión expiró; recarga la página.'
          : data.error || `HTTP ${response.status}`);
        error.status = response.status;
        error.errors = data.errors || data.invalid_keys || [];
        throw error;
      }
      return data;
    }
    async submit() {
      if (!Object.keys(this.changes).length || this.saving) return;
      this.saving = true;
      this.save.disabled = true;
      for (const {input, error} of this.fields.values()) { input.removeAttribute('aria-invalid'); error.hidden = true; }
      const changes = {...this.changes};
      try {
        if (this.api.demo) {
          await new Promise(resolve => setTimeout(resolve, 1000));
          this.demoConfig = structuredClone(this.config);
          for (const [path, value] of Object.entries(this.changes)) this.set(this.demoConfig, path, value);
        } else await this.request('/api/config', {changes});
        this.changes = {};
        await this.load();
        this.status.className = 'settings-status success';
        this.status.textContent = 'GUARDADO ✓';
        setTimeout(() => { if (this.status.textContent === 'GUARDADO ✓') this.status.textContent = ''; }, 2000);
      } catch (error) {
        this.status.className = 'settings-status error';
        this.status.textContent = error.message;
        const invalid = Array.isArray(error.errors)
          ? error.errors.map(e => typeof e === 'string' ? [e, error.message] : [e.field, e.message])
          : Object.entries(error.errors);
        for (const [path, message] of invalid) {
          const field = this.fields.get(path);
          if (field) {
            field.input.setAttribute('aria-invalid', 'true');
            field.error.textContent = String(message);
            field.error.hidden = false;
          }
        }
        this.save.disabled = false;
      } finally { this.saving = false; }
    }
    async changeMaster(name, display, button) {
      if (!confirm(`¿Cambiar la IA maestra a ${display}? Sus instrucciones se moverán.`)) return;
      button.disabled = true;
      try {
        if (this.api.demo) {
          await new Promise(resolve => setTimeout(resolve, 1000));
          this.demoConfig = structuredClone(this.config);
          this.demoConfig.main = name;
        } else {
          await this.request('/api/master', {name});
        }
        this.changes = {};
        this.api.onMaster(name);
        await this.load();
      } catch (error) {
        this.status.className = 'settings-status error';
        this.status.textContent = error.message;
        button.disabled = false;
      }
    }
    async doctor(button, results) {
      button.disabled = true;
      results.className = 'doctor-results';
      results.textContent = 'Probando… (hasta 2 min)';
      try {
        let data;
        if (this.api.demo) {
          await new Promise(resolve => setTimeout(resolve, 1000));
          data = {results: this.api.agents().map(agent => ({
            ok: true, detail: `${agent.display}: conexión disponible`
          }))};
        } else data = await this.request('/api/doctor', {live: true});
        const checks = Array.isArray(data) ? data : data.results || data.checks || [];
        results.replaceChildren(...checks.map(check => {
          const row = this.api.node('div', check.ok ? 'success' : 'error',
            `${check.ok ? '✓' : '✗'} ${check.detail}`);
          if (!check.ok && check.fix) row.append(this.api.node('div', 'empty', check.fix));
          return row;
        }));
      } catch (error) { results.className = 'error'; results.textContent = error.message; }
      finally { button.disabled = false; }
    }
  }
  window.OfficePanels = OfficePanels;
})();
