/* Warrior admin: the barber's view of bookings, schedule and services. */
(() => {
  'use strict';
  const W = window.Warrior;
  const { api, el } = W;
  const $ = (selector, root = document) => root.querySelector(selector);

  const DOW = ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag'];
  const state = { today: null, day: null, services: [], schedule: null, bookings: [] };

  // ------------------------------------------------------------- utilities
  const toastBox = $('[data-toast]');
  let toastTimer;
  function toast(text, isError) {
    toastBox.textContent = text;
    toastBox.classList.toggle('error', Boolean(isError));
    toastBox.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastBox.hidden = true; }, isError ? 6000 : 3000);
  }

  /** Run an admin action; show errors as a toast; go to login if logged out. */
  async function run(action, success) {
    try {
      const result = await action();
      if (success) toast(success);
      return result;
    } catch (problem) {
      if (problem.status === 401) showLogin();
      else toast(problem.message, true);
      return null;
    }
  }

  const mondayOf = (iso) => W.addDays(iso, -((W.toDate(iso).getDay() + 6) % 7));
  const nowStamp = () => { const d = new Date(); return `${W.isoDate(d)}T${W.pad(d.getHours())}:${W.pad(d.getMinutes())}`; };
  const warnConflicts = (count) => {
    if (count) alert(`OBS: ${count} bokning${count === 1 ? '' : 'ar'} ligger i den här perioden. De avbokas inte automatiskt – boka om eller avboka dem under Bokningar.`);
  };
  const input = (attrs) => el('input', attrs);
  const labelled = (label, control, extraClass = '') => el('div', { class: `field ${extraClass}` }, [el('label', { text: label }), control]);

  // ------------------------------------------------------------------ login
  const loginView = $('[data-login]');
  const appView = $('[data-app]');

  function showLogin() {
    appView.hidden = true;
    loginView.hidden = false;
    $('#password').focus();
  }

  $('[data-login-form]').addEventListener('submit', async (event) => {
    event.preventDefault();
    const error = $('[data-login-error]');
    error.hidden = true;
    try {
      await api('/api/admin/login', { method: 'POST', body: { password: $('#password').value } });
      $('#password').value = '';
      start();
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
    }
  });

  $('[data-logout]').addEventListener('click', async () => {
    await api('/api/admin/logout', { method: 'POST' }).catch(() => {});
    showLogin();
  });

  // ------------------------------------------------------------------- tabs
  const panels = { bookings: $('[data-panel="bookings"]'), schedule: $('[data-panel="schedule"]'), services: $('[data-panel="services"]') };
  document.querySelectorAll('[data-tab]').forEach((tab) => tab.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach((other) => other.setAttribute('aria-selected', String(other === tab)));
    Object.entries(panels).forEach(([name, panel]) => { panel.hidden = name !== tab.dataset.tab; });
    ({ bookings: loadBookings, schedule: loadSchedule, services: loadServices })[tab.dataset.tab]();
  }));

  // --------------------------------------------------------------- bookings
  function hoursFor(day) {
    const override = state.schedule.overrides.find((o) => o.day === day);
    const row = override || state.schedule.hours[(W.toDate(day).getDay() + 6) % 7];
    const text = row.closed ? 'Stängt' : `Öppet ${row.open_time} – ${row.close_time}`;
    return override ? `${text} (avvikande dag${override.note ? `: ${override.note}` : ''})` : text;
  }

  async function loadBookings() {
    const monday = mondayOf(state.day);
    const [bookings, schedule] = await Promise.all([
      run(() => api(`/api/admin/bookings?from=${monday}&to=${W.addDays(monday, 7)}`)),
      run(() => api('/api/admin/schedule')),
    ]);
    if (!bookings || !schedule) return;
    state.bookings = bookings.bookings;
    state.schedule = schedule;
    renderBookings();
  }

  function goTo(day) { state.day = day; loadBookings(); }

  function bookingItem(booking) {
    const cancelled = booking.status === 'cancelled';
    const past = booking.end < nowStamp();
    const actions = cancelled
      ? [el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Återställ', onclick: () => setStatus(booking, 'booked') })]
      : [
        el('button', { class: 'btn btn-gold btn-sm', type: 'button', text: 'Boka om / ändra', onclick: () => openDialog(booking) }),
        el('button', { class: 'btn btn-danger btn-sm', type: 'button', text: 'Avboka', onclick: () => setStatus(booking, 'cancelled') }),
      ];
    return el('article', { class: `item${cancelled ? ' cancelled' : ''}${past ? ' past' : ''}` }, [
      el('div', { class: 'at' }, [W.timeOf(booking.start), el('small', { text: `till ${W.timeOf(booking.end)}` })]),
      el('div', {}, [
        el('h3', {}, [
          booking.customer_name,
          cancelled ? el('span', { class: 'tag', text: 'Avbokad' }) : null,
          booking.source === 'admin' ? el('span', { class: 'tag', text: 'Egen' }) : null,
        ]),
        el('p', {}, [
          `${booking.service} · ${booking.price_sek} kr`,
          booking.phone ? ' · ' : null,
          booking.phone ? el('a', { href: `tel:${booking.phone}`, text: booking.phone }) : null,
        ]),
        booking.email ? el('p', {}, el('a', { href: `mailto:${booking.email}`, text: booking.email })) : null,
        booking.note ? el('p', { class: 'note', text: `"${booking.note}"` }) : null,
        el('div', { class: 'item-actions' }, actions),
      ]),
    ]);
  }

  function blockItem(block, day) {
    const from = block.start_at.slice(0, 10) === day ? W.timeOf(block.start_at) : '00:00';
    const to = block.end_at.slice(0, 10) === day ? W.timeOf(block.end_at) : '24:00';
    return el('article', { class: 'item block' }, [
      el('div', { class: 'at' }, [from, el('small', { text: `till ${to}` })]),
      el('div', {}, [el('h3', { text: block.note || 'Blockerad tid' }), el('p', { text: 'Går inte att boka. Ändras under Schema.' })]),
    ]);
  }

  function renderBookings() {
    const day = state.day;
    const monday = mondayOf(day);
    const ofDay = (d) => state.bookings.filter((b) => b.start.slice(0, 10) === d);
    const active = (d) => ofDay(d).filter((b) => b.status === 'booked').length;

    const week = el('div', { class: 'week' }, DOW.map((name, index) => {
      const d = W.addDays(monday, index);
      const count = active(d);
      return el('button', {
        type: 'button', class: d === state.today ? 'is-today' : null, 'aria-pressed': String(d === day),
        'aria-label': `${W.longDate(d)}, ${count} bokningar`, onclick: () => goTo(d),
      }, [
        el('span', { class: 'dow', text: name.slice(0, 3) }),
        el('span', { class: 'num', text: String(W.toDate(d).getDate()) }),
        el('span', { class: `count${count ? ' has' : ''}`, text: String(count) }),
      ]);
    }));

    const blocks = state.schedule.time_off.filter((t) => t.start_at < `${day}T24:00` && t.end_at > `${day}T00:00`);
    const items = [
      ...ofDay(day).map((b) => ({ at: b.start, node: bookingItem(b) })),
      ...blocks.map((t) => ({ at: t.start_at, node: blockItem(t, day) })),
    ].sort((a, b) => a.at.localeCompare(b.at)).map((item) => item.node);

    panels.bookings.replaceChildren(
      el('div', { class: 'day-nav' }, [
        el('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Föregående dag', text: '‹', onclick: () => goTo(W.addDays(day, -1)) }),
        el('h2', { text: day === state.today ? `Idag, ${W.longDate(day)}` : W.longDate(day) }),
        el('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Nästa dag', text: '›', onclick: () => goTo(W.addDays(day, 1)) }),
        input({ type: 'date', value: day, 'aria-label': 'Gå till datum', onchange: (event) => event.target.value && goTo(event.target.value) }),
        day !== state.today ? el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Idag', onclick: () => goTo(state.today) }) : null,
        el('button', { class: 'btn btn-gold btn-sm', type: 'button', text: '+ Ny bokning', onclick: () => openDialog(null) }),
      ]),
      week,
      el('p', { class: 'day-meta', text: `${hoursFor(day)} · ${active(day)} bokning${active(day) === 1 ? '' : 'ar'}` }),
      items.length
        ? el('div', { class: 'agenda' }, items)
        : el('p', { class: 'empty', text: 'Inga bokningar den här dagen.' }),
    );
  }

  async function setStatus(booking, status) {
    if (status === 'cancelled' && !confirm(`Avboka ${booking.customer_name} ${W.when(booking.start)}?`)) return;
    const done = await run(
      () => api(`/api/admin/bookings/${booking.id}`, { method: 'PATCH', body: { status } }),
      status === 'cancelled' ? 'Bokningen är avbokad.' : 'Bokningen är återställd.',
    );
    if (done) loadBookings();
  }

  // ------------------------------------------------- booking dialog (new/edit)
  const dialog = $('[data-booking-dialog]');
  const form = $('[data-booking-form]');
  const f = form.elements;
  const dialogError = $('[data-dialog-error]');
  let editing = null;

  async function refreshTimes(keep) {
    const select = f.time;
    if (!f.service_id.value || !f.date.value) return;
    const query = new URLSearchParams({ service_id: f.service_id.value, date: f.date.value });
    if (editing) query.set('exclude_id', editing.id);
    const data = await run(() => api(`/api/admin/availability?${query}`));
    const slots = data ? data.slots : [];
    select.replaceChildren(...slots.map((slot) => el('option', { value: slot, text: slot })));
    if (!slots.length) select.append(el('option', { value: '', text: 'Inga lediga tider' }));
    if (keep && slots.includes(keep)) select.value = keep;
    else if (keep) { f.use_custom.checked = true; f.custom.value = keep; }  // e.g. a time outside the hours
    syncCustom();
  }

  function syncCustom() {
    f.custom.hidden = !f.use_custom.checked;
    f.time.hidden = f.use_custom.checked;
  }

  function openDialog(booking) {
    editing = booking;
    form.reset();
    dialogError.hidden = true;
    $('[data-dialog-title]').textContent = booking ? 'Ändra bokning' : 'Ny bokning';
    $('[data-dialog-save]').textContent = booking ? 'Spara ändringar' : 'Boka';
    const usable = state.services.filter((s) => s.active || (booking && s.id === booking.service_id));
    f.service_id.replaceChildren(...usable.map((s) => el('option', { value: s.id, text: `${s.name} (${s.duration_min} min, ${s.price_sek} kr)` })));
    if (booking) {
      f.service_id.value = booking.service_id;
      f.date.value = booking.start.slice(0, 10);
      f.customer_name.value = booking.customer_name;
      f.phone.value = booking.phone;
      f.email.value = booking.email;
      f.note.value = booking.note;
    } else {
      f.date.value = state.day;
    }
    refreshTimes(booking ? W.timeOf(booking.start) : null);
    dialog.showModal();
  }

  f.service_id.addEventListener('change', () => refreshTimes(f.time.value));
  f.date.addEventListener('change', () => refreshTimes(f.time.value));
  f.use_custom.addEventListener('change', () => {
    if (f.use_custom.checked && !f.custom.value) f.custom.value = f.time.value;
    syncCustom();
  });
  $('[data-dialog-close]').addEventListener('click', () => dialog.close());

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const time = f.use_custom.checked ? f.custom.value : f.time.value;
    if (!time) { dialogError.textContent = 'Välj en tid.'; dialogError.hidden = false; return; }
    const body = {
      service_id: Number(f.service_id.value), start: `${f.date.value}T${time}`,
      customer_name: f.customer_name.value, phone: f.phone.value, email: f.email.value, note: f.note.value,
    };
    try {
      if (editing) await api(`/api/admin/bookings/${editing.id}`, { method: 'PATCH', body });
      else await api('/api/admin/bookings', { method: 'POST', body });
      dialog.close();
      toast(editing ? 'Bokningen är uppdaterad.' : 'Bokningen är sparad.');
      goTo(f.date.value);
    } catch (problem) {
      if (problem.status === 401) { dialog.close(); showLogin(); return; }
      dialogError.textContent = problem.message;
      dialogError.hidden = false;
    }
  });

  // --------------------------------------------------------------- schedule
  async function loadSchedule() {
    const schedule = await run(() => api('/api/admin/schedule'));
    if (!schedule) return;
    state.schedule = schedule;
    panels.schedule.replaceChildren(weekCard(), overridesCard(), timeOffCard(), rulesCard());
  }

  function weekCard() {
    const rows = state.schedule.hours.map((row) => {
      const closed = input({ type: 'checkbox', checked: Boolean(row.closed) });
      const open = input({ type: 'time', value: row.open_time, step: 300, 'aria-label': `${DOW[row.weekday]} öppnar` });
      const close = input({ type: 'time', value: row.close_time, step: 300, 'aria-label': `${DOW[row.weekday]} stänger` });
      const node = el('div', { class: `week-row${row.closed ? ' is-closed' : ''}` }, [
        el('span', { class: 'name', text: DOW[row.weekday] }), open, close,
        el('label', { class: 'check' }, [closed, 'Stängt']),
      ]);
      closed.addEventListener('change', () => node.classList.toggle('is-closed', closed.checked));
      return { node, read: () => ({ open_time: open.value, close_time: close.value, closed: closed.checked }) };
    });
    return el('section', { class: 'card' }, [
      el('h2', { text: 'Ordinarie vecka' }),
      el('p', { class: 'hint', text: 'Dina vanliga arbetstider. Kunder kan bara boka inom de här tiderna.' }),
      el('div', { class: 'week-form' }, rows.map((r) => r.node)),
      el('div', { class: 'card-actions' }, el('button', { class: 'btn btn-gold', type: 'button', text: 'Spara veckan', onclick: async () => {
        await run(() => api('/api/admin/hours', { method: 'PUT', body: { hours: rows.map((r) => r.read()) } }), 'Veckoschemat är sparat.');
      } })),
    ]);
  }

  function removable(title, sub, onRemove) {
    return el('li', {}, [
      el('div', {}, [title, sub ? el('small', { text: sub }) : null]),
      el('button', { class: 'btn btn-ghost btn-sm', type: 'button', text: 'Ta bort', onclick: onRemove }),
    ]);
  }

  function overridesCard() {
    const day = input({ type: 'date', min: state.today, required: true });
    const open = input({ type: 'time', value: '10:00', step: 300 });
    const close = input({ type: 'time', value: '16:00', step: 300 });
    const closed = input({ type: 'checkbox' });
    const note = input({ type: 'text', maxlength: 120, placeholder: 't.ex. Julafton' });
    closed.addEventListener('change', () => { open.disabled = close.disabled = closed.checked; });
    const add = el('form', { class: 'inline-form' }, [
      labelled('Datum', day), labelled('Öppnar', open), labelled('Stänger', close), labelled('Anteckning', note, 'grow'),
      el('label', { class: 'check' }, [closed, 'Stängt hela dagen']),
      el('button', { class: 'btn btn-gold', type: 'submit', text: 'Lägg till' }),
    ]);
    add.addEventListener('submit', async (event) => {
      event.preventDefault();
      const saved = await run(() => api(`/api/admin/overrides/${day.value}`, { method: 'PUT', body: {
        closed: closed.checked, open_time: open.value, close_time: close.value, note: note.value,
      } }), 'Dagen är sparad.');
      if (saved) { warnConflicts(saved.conflicts); loadSchedule(); }
    });
    const list = state.schedule.overrides.map((o) => removable(
      W.longDate(o.day), [o.closed ? 'Stängt' : `${o.open_time} – ${o.close_time}`, o.note].filter(Boolean).join(' · '),
      async () => { if (await run(() => api(`/api/admin/overrides/${o.day}`, { method: 'DELETE' }), 'Borttagen.')) loadSchedule(); },
    ));
    return el('section', { class: 'card' }, [
      el('h2', { text: 'Avvikande dagar' }),
      el('p', { class: 'hint', text: 'En enskild dag med andra tider än vanligt, eller helt stängt (helgdag, ledig dag).' }),
      list.length ? el('ul', { class: 'row-list' }, list) : null,
      add,
    ]);
  }

  function timeOffCard() {
    const from = input({ type: 'datetime-local', required: true, step: 300, value: `${state.today}T12:00` });
    const to = input({ type: 'datetime-local', required: true, step: 300, value: `${state.today}T13:00` });
    const note = input({ type: 'text', maxlength: 120, placeholder: 't.ex. Lunch, semester' });
    const add = el('form', { class: 'inline-form' }, [
      labelled('Från', from), labelled('Till', to), labelled('Anteckning', note, 'grow'),
      el('button', { class: 'btn btn-gold', type: 'submit', text: 'Blockera' }),
    ]);
    add.addEventListener('submit', async (event) => {
      event.preventDefault();
      const saved = await run(() => api('/api/admin/time-off', { method: 'POST', body: {
        start: from.value.slice(0, 16), end: to.value.slice(0, 16), note: note.value,
      } }), 'Tiden är blockerad.');
      if (saved) { warnConflicts(saved.conflicts); loadSchedule(); }
    });
    const list = state.schedule.time_off.map((t) => removable(
      t.start_at.slice(0, 10) === t.end_at.slice(0, 10)
        ? `${W.shortDate(t.start_at)} ${W.timeOf(t.start_at)} – ${W.timeOf(t.end_at)}`
        : `${W.shortDate(t.start_at)} ${W.timeOf(t.start_at)} – ${W.shortDate(t.end_at)} ${W.timeOf(t.end_at)}`,
      t.note,
      async () => { if (await run(() => api(`/api/admin/time-off/${t.id}`, { method: 'DELETE' }), 'Borttagen.')) loadSchedule(); },
    ));
    return el('section', { class: 'card' }, [
      el('h2', { text: 'Blockerad tid' }),
      el('p', { class: 'hint', text: 'Tid du inte vill ha bokningar på: lunch, ärenden eller flera dagars semester.' }),
      list.length ? el('ul', { class: 'row-list' }, list) : null,
      add,
    ]);
  }

  function rulesCard() {
    const s = state.schedule.settings;
    const number = (value, min, max) => input({ type: 'number', value, min, max, required: true });
    const step = number(s.slot_step_min, 5, 120);
    const notice = number(s.min_notice_min, 0, 10080);
    const ahead = number(s.max_days_ahead, 1, 365);
    const cancel = number(s.cancel_notice_min, 0, 10080);
    const rules = el('form', { class: 'inline-form' }, [
      labelled('Tider visas var (minuter)', step),
      labelled('Senast bokning före start (minuter)', notice),
      labelled('Bokningsbart framåt (dagar)', ahead),
      labelled('Kund kan av-/omboka senast (minuter före)', cancel),
      el('button', { class: 'btn btn-gold', type: 'submit', text: 'Spara regler' }),
    ]);
    rules.addEventListener('submit', async (event) => {
      event.preventDefault();
      await run(() => api('/api/admin/settings', { method: 'PUT', body: {
        slot_step_min: step.value, min_notice_min: notice.value, max_days_ahead: ahead.value, cancel_notice_min: cancel.value,
      } }), 'Reglerna är sparade.');
    });
    return el('section', { class: 'card' }, [
      el('h2', { text: 'Bokningsregler' }),
      el('p', { class: 'hint', text: 'Gäller kunder som bokar på webbplatsen. Du själv kan alltid boka fritt här i admin.' }),
      rules,
    ]);
  }

  // --------------------------------------------------------------- services
  async function loadServices() {
    const data = await run(() => api('/api/admin/services'));
    if (!data) return;
    state.services = data.services;
    panels.services.replaceChildren(el('section', { class: 'card' }, [
      el('h2', { text: 'Tjänster' }),
      el('p', { class: 'hint', text: 'Det kunderna kan boka. Längden styr hur lång tid som reserveras i kalendern.' }),
      ...state.services.map((service) => serviceForm(service)),
      el('h3', { text: 'Ny tjänst', style: 'margin:24px 0 12px' }),
      serviceForm(null),
    ]));
  }

  function serviceForm(service) {
    const name = input({ type: 'text', required: true, maxlength: 60, value: service ? service.name : '' });
    const minutes = input({ type: 'number', required: true, min: 5, max: 480, step: 5, value: service ? service.duration_min : 30 });
    const price = input({ type: 'number', required: true, min: 0, max: 100000, value: service ? service.price_sek : 200 });
    const description = input({ type: 'text', maxlength: 200, value: service ? service.description : '' });
    const active = input({ type: 'checkbox', checked: service ? Boolean(service.active) : true });
    const node = el('form', { class: 'service-form' }, [
      labelled('Namn', name, 'name-field'), labelled('Längd (min)', minutes), labelled('Pris (kr)', price),
      labelled('Beskrivning', description, 'wide'),
      el('div', { class: 'foot' }, [
        el('label', { class: 'check' }, [active, 'Visas och kan bokas på webbplatsen']),
        el('button', { class: `btn ${service ? 'btn-ghost' : 'btn-gold'} btn-sm`, type: 'submit', text: service ? 'Spara' : 'Lägg till' }),
      ]),
    ]);
    node.addEventListener('submit', async (event) => {
      event.preventDefault();
      const body = {
        name: name.value, description: description.value, duration_min: Number(minutes.value),
        price_sek: Number(price.value), active: active.checked, sort: service ? service.sort : state.services.length + 1,
      };
      const saved = await run(
        () => api(service ? `/api/admin/services/${service.id}` : '/api/admin/services', { method: service ? 'PUT' : 'POST', body }),
        service ? 'Tjänsten är sparad.' : 'Tjänsten är tillagd.',
      );
      if (saved) loadServices();
    });
    return node;
  }

  // ------------------------------------------------------------------ start
  async function start() {
    let me;
    try { me = await api('/api/admin/me'); } catch { me = { admin: false }; }
    if (!me.admin) return showLogin();
    const info = await run(() => api('/api/info'));
    const services = await run(() => api('/api/admin/services'));
    if (!info || !services) return;
    state.today = info.today;
    state.day = state.day || info.today;
    state.services = services.services;
    loginView.hidden = true;
    appView.hidden = false;
    loadBookings();
  }

  start();
})();
