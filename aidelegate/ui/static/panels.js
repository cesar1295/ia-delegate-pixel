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
        ui: {time_mode: 'auto', fixed_hour: 12}, strategy: {mode: 'routing', first: 'agy', then: 'codex',
          escalate_after: 2},
        limits: {max_fix_rounds: 3, max_review_rounds: 2, timeout_min: 30, keep_days: 7},
        agents: Object.fromEntries(this.api.agents().map(a => [a.name,
          {display: a.display, color: a.color, enabled: true, model: '', daily_token_budget: 0,
           type: a.type || a.name,
           permissions: a.name === 'codex' ? {edit: true, network: false}
             : a.name === 'agy' ? {edit: true, groups: ['lectura']}
             : {edit: true}}]))};
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
        this.claudeCalibration = data.claude_calibration || {budget: null, samples: 0};
        this.catalog = data.catalog || data.agy_catalog || {
          lectura: ["ls", "tree", "pwd", "cat", "head", "tail", "wc", "grep", "git status", "git log", "git diff", "git show", "git ls-files", "git grep", "git blame", "git rev-parse"],
          pruebas: ["npm test", "npm run test", "npm run lint", "npm run typecheck", "pnpm test", "pnpm run lint", "yarn test", "yarn lint", "pytest", "python3 -m pytest", "python -m pytest"],
          instalacion: ["npm install", "npm ci", "pnpm install", "yarn install", "pip install", "python3 -m pip install"]
        };
        this.alwaysDenied = data.always_denied || ["rm", "sudo", "git push", "git commit", "git reset", "git checkout", "git clean"];
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
        if (name === master && name === 'claude') this.renderClaudeBudget(card);
        masterSection.append(card);
      }
      const distribution = this.section('Escalamiento');
      distribution.append(node('p', 'permissions-help',
        'La IA maestra decide a qué agente va cada tarea según su complejidad. Aquí defines a quién pasa si un agente no la resuelve.'));
      this.field(distribution, 'Primer agente de la cadena', 'strategy.first', 'select', {choices: agentChoices});
      this.field(distribution, 'Si no lo resuelve, pasa a', 'strategy.then', 'select', {choices: agentChoices});
      this.field(distribution, 'Correcciones antes de escalar', 'strategy.escalate_after', 'number', {min: 1, max: 10});
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
        if (name === 'claude') this.renderClaudeBudget(card);
        this.renderPermissions(card, name, agent);
      }
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
    renderClaudeBudget(card) {
      this.field(card, 'Presupuesto de tokens por 5 h', 'agents.claude.five_hour_token_budget',
        'number', {min: 0, default: 0, suffix: '0 = automático'});
      const {budget, samples} = this.claudeCalibration || {};
      // TODO(diseño): texto de calibración en Plex Mono 11px y --muted.
      card.append(this.api.node('p', 'permissions-help', budget
        ? `Automático: ${(budget / 1000000).toFixed(1)} M calibrado con ${samples} mediciones`
        : 'Automático: sin mediciones todavía (usa Claude Code en la terminal una vez para calibrar)'));
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
    renderPermissions(card, name, agent) {
      const {node} = this.api;
      const agentType = agent.type || name;

      const permHeader = node('div', 'permissions-header', 'PERMISOS');
      card.append(permHeader);

      if (agentType === 'generic') {
        const genericText = node('p', 'permissions-generic-text', 'Lo define su propia CLI.');
        const deniedLine = node('p', 'permissions-denied',
          '🔒 Siempre bloqueados: rm, sudo, git push, git commit, git reset, git checkout, git clean');
        card.append(genericText, deniedLine);
        return;
      }

      const perms = {
        edit: agent.permissions?.edit ?? true,
        network: agent.permissions?.network ?? false,
        groups: [...(agent.permissions?.groups || ['lectura'])],
      };

      const editField = node('div', 'setting-field');
      const editLabel = node('label', '', 'PUEDE EDITAR ARCHIVOS');
      const editInput = document.createElement('input');
      editInput.type = 'checkbox';
      editInput.className = 'setting-switch';
      editInput.checked = perms.edit !== false;
      const editHelp = node('p', 'permissions-help',
        editInput.checked ? 'Edita solo dentro de su carpeta de trabajo (worktree).'
                          : 'Solo lectura: no recibirá tareas de programación.');
      editInput.addEventListener('change', () => {
        perms.edit = editInput.checked;
        editHelp.textContent = editInput.checked
          ? 'Edita solo dentro de su carpeta de trabajo (worktree).'
          : 'Solo lectura: no recibirá tareas de programación.';
      });
      editField.append(editLabel, editInput, editHelp);
      card.append(editField);

      if (agentType === 'codex') {
        const netField = node('div', 'setting-field');
        const netLabel = node('label', '', 'INTERNET EN SU SANDBOX');
        const netInput = document.createElement('input');
        netInput.type = 'checkbox';
        netInput.className = 'setting-switch';
        netInput.checked = Boolean(perms.network);
        const netHelp = node('p', 'permissions-help', 'Apagado: no puede descargar nada.');
        netInput.addEventListener('change', () => {
          perms.network = netInput.checked;
        });
        netField.append(netLabel, netInput, netHelp);
        card.append(netField);
      }

      if (agentType === 'agy') {
        const groupsWrapper = node('div', 'permissions-groups');
        const catalog = this.catalog || {
          lectura: ["ls", "tree", "pwd", "cat", "head", "tail", "wc", "grep", "git status", "git log", "git diff", "git show", "git ls-files", "git grep", "git blame", "git rev-parse"],
          pruebas: ["npm test", "npm run test", "npm run lint", "npm run typecheck", "pnpm test", "pnpm run lint", "yarn test", "yarn lint", "pytest", "python3 -m pytest", "python -m pytest"],
          instalacion: ["npm install", "npm ci", "pnpm install", "yarn install", "pip install", "python3 -m pip install"]
        };

        const groupDefs = [
          {id: 'lectura', label: 'Lectura', disabled: true, warn: false},
          {id: 'pruebas', label: 'Pruebas', disabled: false, warn: false},
          {id: 'instalacion', label: 'Instalación', disabled: false, warn: true}
        ];

        for (const g of groupDefs) {
          const item = node('div', 'permissions-group-item');
          const header = node('label', 'permissions-checkbox-label');
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.className = 'perm-checkbox';
          if (g.disabled) {
            cb.checked = true;
            cb.disabled = true;
          } else {
            cb.checked = perms.groups.includes(g.id);
            cb.addEventListener('change', () => {
              if (cb.checked) {
                if (!perms.groups.includes(g.id)) perms.groups.push(g.id);
              } else {
                perms.groups = perms.groups.filter(x => x !== g.id);
              }
            });
          }
          header.append(cb, node('span', 'permissions-group-name', g.label));
          if (g.warn) {
            header.append(node('span', 'perm-warn', '⚠ descarga código'));
          }
          const cmds = catalog[g.id] || [];
          const cmdsStr = cmds.join(', ');
          const list = node('span', 'perm-cmd-list', cmdsStr);
          list.title = cmdsStr;
          list.tabIndex = 0;
          item.append(header, list);
          groupsWrapper.append(item);
        }
        card.append(groupsWrapper);
      }

      const deniedLine = node('p', 'permissions-denied',
        '🔒 Siempre bloqueados: rm, sudo, git push, git commit, git reset, git checkout, git clean');
      card.append(deniedLine);

      const footer = node('div', 'permissions-card-footer');
      const saveBtn = this.button('GUARDAR PERMISOS', 'secondary');
      const statusEl = node('span', 'permissions-status');
      statusEl.setAttribute('role', 'status');
      saveBtn.onclick = () => this.savePermissions(name, perms, saveBtn, statusEl);
      footer.append(saveBtn, statusEl);
      card.append(footer);
    }
    async savePermissions(agentName, perms, button, statusEl, confirmed = false) {
      button.disabled = true;
      statusEl.textContent = '';
      statusEl.className = 'permissions-status';
      try {
        const agent = this.config.agents?.[agentName] || {};
        const type = agent.type || agentName;
        const changes = {};
        if (type === 'codex') {
          changes.edit = perms.edit ?? true;
          changes.network = perms.network ?? false;
        } else if (type === 'agy') {
          changes.edit = perms.edit ?? true;
          changes.groups = perms.groups ?? ['lectura'];
        } else if (type === 'claude') {
          changes.edit = perms.edit ?? true;
        }

        if (this.api.demo) {
          const current = (this.demoConfig || this.config)?.agents?.[agentName]?.permissions || {};
          let needsConfirm = false;
          let confirmMsg = '';
          const display = agent.display || agentName;
          if (changes.edit === true && current.edit === false) {
            needsConfirm = true;
            confirmMsg = `${display} podrá editar archivos en su carpeta de trabajo.`;
          } else if (type === 'codex' && changes.network === true && current.network !== true) {
            needsConfirm = true;
            confirmMsg = 'Codex tendrá acceso a internet dentro de su sandbox (por ejemplo para instalar dependencias).';
          } else if (type === 'agy' && changes.groups?.includes('pruebas') && !current.groups?.includes('pruebas')) {
            needsConfirm = true;
            const catalog = this.catalog || {};
            confirmMsg = `agy podrá ejecutar: ${(catalog.pruebas || []).join(', ')}.`;
          } else if (type === 'agy' && changes.groups?.includes('instalacion') && !current.groups?.includes('instalacion')) {
            needsConfirm = true;
            const catalog = this.catalog || {};
            confirmMsg = `agy podrá instalar dependencias con: ${(catalog.instalacion || []).join(', ')}. Esto descarga código de internet.`;
          }
          if (needsConfirm && !confirmed) {
            if (window.confirm(confirmMsg)) {
              return this.savePermissions(agentName, perms, button, statusEl, true);
            }
            button.disabled = false;
            return;
          }
          await new Promise(r => setTimeout(r, 400));
          this.demoConfig = structuredClone(this.demoConfig || this.config);
          if (!this.demoConfig.agents[agentName]) this.demoConfig.agents[agentName] = {};
          this.demoConfig.agents[agentName].permissions = changes;
          statusEl.className = 'permissions-status success';
          statusEl.textContent = 'GUARDADO ✓';
          setTimeout(() => { if (statusEl.textContent === 'GUARDADO ✓') statusEl.textContent = ''; }, 2000);
          return;
        }

        const token = document.querySelector('meta[name="ai-delegate-token"]')?.content || '';
        const res = await fetch('/api/permissions', {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-AI-Delegate-Token': token},
          body: JSON.stringify({agent: agentName, changes, confirm: confirmed})
        });

        if (res.status === 409) {
          const data = await res.json();
          if (window.confirm(data.message)) {
            return this.savePermissions(agentName, perms, button, statusEl, true);
          }
          button.disabled = false;
          return;
        }

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || `HTTP ${res.status}`);
        }

        statusEl.className = 'permissions-status success';
        statusEl.textContent = 'GUARDADO ✓';
        if (this.config.agents?.[agentName]) {
          this.config.agents[agentName].permissions = data.permissions;
        }
        setTimeout(() => { if (statusEl.textContent === 'GUARDADO ✓') statusEl.textContent = ''; }, 2000);
      } catch (err) {
        statusEl.className = 'permissions-status error';
        statusEl.textContent = err.message;
      } finally {
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
