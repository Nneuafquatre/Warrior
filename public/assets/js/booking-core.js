/* Shared helpers for the booking pages: API calls, Swedish dates,
   and the day + time picker used when booking and when rebooking. */
window.Warrior = (() => {
  'use strict';

  const DOW_SHORT = ['sön', 'mån', 'tis', 'ons', 'tors', 'fre', 'lör'];
  const DOW_LONG = ['söndag', 'måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag'];
  const MON_SHORT = ['jan', 'feb', 'mars', 'apr', 'maj', 'juni', 'juli', 'aug', 'sep', 'okt', 'nov', 'dec'];
  const MON_LONG = ['januari', 'februari', 'mars', 'april', 'maj', 'juni', 'juli', 'augusti', 'september', 'oktober', 'november', 'december'];

  const pad = (n) => String(n).padStart(2, '0');
  // Dates travel as "YYYY-MM-DD" strings; build local Dates by hand so the
  // browser's timezone can never shift them a day.
  const toDate = (iso) => { const [y, m, d] = iso.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); };
  const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const addDays = (iso, n) => { const d = toDate(iso); d.setDate(d.getDate() + n); return isoDate(d); };
  const longDate = (iso) => { const d = toDate(iso); return `${DOW_LONG[d.getDay()]} ${d.getDate()} ${MON_LONG[d.getMonth()]}`; };
  const shortDate = (iso) => { const d = toDate(iso); return `${DOW_SHORT[d.getDay()]} ${d.getDate()} ${MON_SHORT[d.getMonth()]}`; };
  const timeOf = (stamp) => stamp.slice(11, 16);
  const when = (stamp) => `${longDate(stamp)} kl. ${timeOf(stamp)}`;

  /** Small DOM builder. Text always goes in as text, never as HTML. */
  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === false || value == null) continue;
      if (key === 'text') node.textContent = value;
      else if (key === 'class') node.className = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of [].concat(children)) {
      if (child != null && child !== false) node.append(child);
    }
    return node;
  }

  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#i-${name}`);
    svg.append(use);
    return svg;
  }

  async function api(path, { method = 'GET', body } = {}) {
    let response;
    try {
      response = await fetch(path, {
        method,
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'fetch', ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new Error('Kunde inte nå bokningen. Kontrollera din uppkoppling och försök igen.');
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || 'Något gick fel. Försök igen.');
      error.status = response.status;
      throw error;
    }
    return data;
  }

  /** Rows for the "Tjänst / Tid / Pris" box. */
  function summary(rows) {
    return el('div', { class: 'summary' }, rows.map(([k, v]) =>
      el('div', {}, [el('span', { class: 'k', text: k }), el('span', { class: 'v', text: v })])));
  }

  /**
   * Day strip + time grid.
   * options: mount, serviceId, today, maxDays, token (when moving an existing
   * booking), onPick(startStamp | null)
   */
  function createPicker(options) {
    const { mount, today, maxDays, token, onPick } = options;
    let serviceId = options.serviceId;
    let days = [];           // [{date, slots}]
    let pickedDate = null;
    let pickedTime = null;
    let request = 0;         // ignore answers from outdated requests

    const strip = el('div', { class: 'days', role: 'group', 'aria-label': 'Välj dag' });
    const dayLabel = el('p', { class: 'picked-day' });
    const grid = el('div', { class: 'times', role: 'group', 'aria-label': 'Välj tid' });
    const message = el('p', { class: 'notice', hidden: true });
    mount.replaceChildren(strip, message, dayLabel, grid);

    function say(text, isError) {
      message.textContent = text || '';
      message.hidden = !text;
      message.classList.toggle('error', Boolean(isError));
    }

    function renderTimes() {
      const day = days.find((d) => d.date === pickedDate);
      dayLabel.textContent = day ? longDate(day.date) : '';
      grid.replaceChildren(...(day ? day.slots : []).map((slot) => el('button', {
        type: 'button', class: 'time', text: slot, 'aria-pressed': String(slot === pickedTime),
        onclick: () => { pickedTime = slot; renderTimes(); onPick(`${pickedDate}T${slot}`); },
      })));
    }

    function renderDays() {
      const buttons = days.map((day) => {
        const d = toDate(day.date);
        return el('button', {
          type: 'button', class: 'day', disabled: day.slots.length === 0,
          'aria-pressed': String(day.date === pickedDate),
          'aria-label': longDate(day.date) + (day.slots.length ? '' : ', fullbokat eller stängt'),
          onclick: () => { pickedDate = day.date; pickedTime = null; onPick(null); renderDays(); renderTimes(); },
        }, [
          el('span', { class: 'dow', text: day.date === today ? 'idag' : DOW_SHORT[d.getDay()] }),
          el('span', { class: 'num', text: String(d.getDate()) }),
          el('span', { class: 'mon', text: MON_SHORT[d.getMonth()] }),
        ]);
      });
      if (days.length <= maxDays) {
        buttons.push(el('button', { type: 'button', class: 'day day-more', text: 'Fler dagar', onclick: () => load(false) }));
      }
      strip.replaceChildren(...buttons);
    }

    async function load(reset) {
      const mine = ++request;
      if (reset) { days = []; pickedDate = null; pickedTime = null; onPick(null); }
      const from = addDays(today, days.length);
      const count = Math.min(14, maxDays + 1 - days.length);
      if (count <= 0) return;
      if (reset) say('Hämtar lediga tider…');
      try {
        const query = new URLSearchParams({ service_id: serviceId, from, days: count });
        if (token) query.set('token', token);
        const data = await api(`/api/availability?${query}`);
        if (mine !== request) return;
        days = days.concat(data.days);
        if (!pickedDate) {
          const first = days.find((d) => d.slots.length);
          pickedDate = first ? first.date : null;
        }
        say(days.some((d) => d.slots.length) ? '' : 'Inga lediga tider just nu. Titta längre fram eller ring oss.');
        renderDays();
        renderTimes();
      } catch (error) {
        if (mine === request) say(error.message, true);
      }
    }

    load(true);
    return {
      setService(id) { serviceId = id; load(true); },
      reload() { load(true); },
    };
  }

  return { api, el, icon, summary, createPicker, toDate, isoDate, addDays, longDate, shortDate, timeOf, when, pad, DOW_LONG };
})();
