/* Warrior Barbershop - home page: menu, gallery, opening hours, booking. */
(() => {
  'use strict';
  const { api, el, icon, summary, createPicker, when, timeOf, DOW_LONG } = window.Warrior;
  const $ = (selector) => document.querySelector(selector);

  // ---------------------------------------------------------- header + menu
  const header = $('[data-header]');
  const nav = $('[data-nav]');
  const toggle = $('[data-nav-toggle]');
  const onScroll = () => header.classList.toggle('is-solid', window.scrollY > 24);
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  function setMenu(open) {
    nav.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Stäng menyn' : 'Öppna menyn');
  }
  toggle.addEventListener('click', () => setMenu(!nav.classList.contains('is-open')));
  nav.addEventListener('click', (event) => { if (event.target.closest('a')) setMenu(false); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') setMenu(false); });

  $('[data-year]').textContent = new Date().getFullYear();

  // ---------------------------------------------------------------- gallery
  const more = $('[data-gallery-more]');
  more.addEventListener('click', () => {
    document.querySelectorAll('[data-gallery] [data-extra]').forEach((img) => { img.hidden = false; });
    more.hidden = true;
  });

  // The floating "Boka tid" button on phones hides while the booking is on screen.
  // It also stays away at the very top, where the hero has its own button.
  const mobileCta = $('[data-mobile-cta]');
  let bookingOnScreen = false;
  const syncCta = () => mobileCta.classList.toggle('is-hidden', bookingOnScreen || window.scrollY < 480);
  new IntersectionObserver(([entry]) => { bookingOnScreen = entry.isIntersecting; syncCta(); }, { threshold: 0.05 })
    .observe($('#boka'));
  window.addEventListener('scroll', syncCta, { passive: true });
  syncCta();

  // ---------------------------------------------------------- opening hours
  const span = (row) => (row.closed ? 'Stängt' : `${row.open_time} – ${row.close_time}`);

  function renderHours(hours, today) {
    // Group days in a row that share the same hours: "Måndag – fredag".
    const groups = [];
    hours.forEach((row) => {
      const last = groups[groups.length - 1];
      if (last && last.text === span(row)) last.to = row.weekday;
      else groups.push({ from: row.weekday, to: row.weekday, text: span(row) });
    });
    const name = (weekday) => DOW_LONG[(weekday + 1) % 7];
    const cap = (s) => s[0].toUpperCase() + s.slice(1);
    const todayIndex = (window.Warrior.toDate(today).getDay() + 6) % 7; // 0 = Monday
    $('[data-hours] tbody').replaceChildren(...groups.map((group) => el('tr', {
      class: todayIndex >= group.from && todayIndex <= group.to ? 'is-today' : null,
    }, [
      el('th', { scope: 'row', text: group.from === group.to ? cap(name(group.from)) : `${cap(name(group.from))} – ${name(group.to)}` }),
      el('td', { text: group.text }),
    ])));
    const now = hours[todayIndex];
    $('[data-today-hours]').textContent = now.closed ? 'Stängt idag' : `Öppet idag ${now.open_time} – ${now.close_time}`;
  }

  function renderServices(services) {
    $('[data-services]').replaceChildren(...services.map((service) => el('article', { class: 'service-card' }, [
      el('div', {}, [el('h3', { text: service.name }), el('p', { text: service.description })]),
      el('div', { class: 'service-meta' }, [
        el('span', { class: 'price', text: `${service.price_sek} kr` }),
        el('span', { text: `${service.duration_min} min` }),
      ]),
    ])));
  }

  // ---------------------------------------------------------------- booking
  const mount = $('[data-booking]');

  function stepTitle(number, text) {
    return el('h3', { class: 'step-title' }, [el('span', { class: 'step-num', text: String(number) }), text]);
  }

  function field(label, input, optional, full) {
    const id = `f-${input.name}`;
    input.id = id;
    return el('div', { class: `field${full ? ' full' : ''}` }, [
      el('label', { for: id }, [label, optional ? el('span', { text: ' (valfritt)' }) : null]),
      input,
    ]);
  }

  function calendarFile(booking) {
    const stamp = (s) => s.replace(/[-:]/g, '') + '00';
    const text = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Warrior Barbershop//Bokning//SV', 'BEGIN:VEVENT',
      `UID:${booking.token}@warriorbarbershop.com`,
      `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)}Z`,
      `DTSTART;TZID=Europe/Stockholm:${stamp(booking.start)}`,
      `DTEND;TZID=Europe/Stockholm:${stamp(booking.end)}`,
      `SUMMARY:${booking.service} – Warrior Barbershop`,
      'LOCATION:Långholmsgatan 11\\, Stockholm',
      'END:VEVENT', 'END:VCALENDAR',
    ].join('\r\n');
    return URL.createObjectURL(new Blob([text], { type: 'text/calendar' }));
  }

  function showDone(booking) {
    const manage = `/bokning?t=${encodeURIComponent(booking.token)}`;
    mount.replaceChildren(el('div', { class: 'done', role: 'status' }, [
      el('div', { class: 'done-mark' }, icon('check')),
      el('h3', { text: 'Din tid är bokad' }),
      el('p', { class: 'muted', text: booking.email
        ? `En bekräftelse skickas till ${booking.email}.`
        : 'Spara länken nedan om du behöver boka om eller avboka.' }),
      summary([
        ['Tjänst', booking.service],
        ['Tid', when(booking.start)],
        ['Pris', `${booking.price_sek} kr (betalas i salongen)`],
        ['Adress', 'Långholmsgatan 11, Stockholm'],
      ]),
      el('div', { class: 'done-actions' }, [
        el('a', { class: 'btn btn-gold', href: calendarFile(booking), download: 'warrior-bokning.ics', text: 'Lägg till i kalendern' }),
        el('a', { class: 'btn btn-ghost', href: manage, text: 'Boka om eller avboka' }),
      ]),
    ]));
    mount.scrollIntoView({ block: 'center' });
  }

  function buildBooking(info) {
    const services = info.services;
    if (!services.length) {
      mount.replaceChildren(el('p', { class: 'notice', text: 'Onlinebokningen är stängd just nu. Ring oss på 076-419 70 98.' }));
      return;
    }
    let service = services[0];
    let start = null;

    // Step 1: service
    const serviceStep = el('div', { class: 'step' }, [
      stepTitle(1, 'Tjänst'),
      el('div', { class: 'choice-list' }, services.map((item, index) => el('label', { class: 'choice' }, [
        el('input', {
          type: 'radio', name: 'service', value: item.id, checked: index === 0,
          onchange: () => { service = item; picker.setService(item.id); },
        }),
        el('span', {}, [
          el('strong', { text: item.name }),
          el('small', { text: [`${item.duration_min} min`, item.description].filter(Boolean).join(' · ') }),
        ]),
        el('span', { class: 'price', text: `${item.price_sek} kr` }),
      ]))),
    ]);

    // Step 2: day and time
    const pickerMount = el('div');
    const timeStep = el('div', { class: 'step' }, [stepTitle(2, 'Dag och tid'), pickerMount]);

    // Step 3: details
    const name = el('input', { name: 'customer_name', type: 'text', autocomplete: 'name', required: true, maxlength: 80 });
    const phone = el('input', { name: 'phone', type: 'tel', autocomplete: 'tel', inputmode: 'tel', required: true, maxlength: 30, placeholder: '07x-xxx xx xx' });
    const email = el('input', { name: 'email', type: 'email', autocomplete: 'email', maxlength: 120 });
    const note = el('textarea', { name: 'note', maxlength: 300, rows: 2 });
    const trap = el('input', { name: 'website', type: 'text', tabindex: '-1', autocomplete: 'off' });
    const summaryBox = el('div');
    const error = el('p', { class: 'notice error', role: 'alert', hidden: true });
    const submit = el('button', { type: 'submit', class: 'btn btn-gold btn-lg btn-block', text: 'Bekräfta bokning' });

    const form = el('form', { class: 'step', hidden: true, novalidate: false }, [
      stepTitle(3, 'Dina uppgifter'),
      el('div', { class: 'form-grid' }, [
        field('Namn', name),
        field('Mobilnummer', phone),
        field('E-post för bekräftelse', email, true, true),
        field('Meddelande till barberaren', note, true, true),
        el('div', { class: 'hp', 'aria-hidden': 'true' }, [el('label', { text: 'Lämna tomt' }), trap]),
      ]),
      summaryBox, error, submit,
      el('p', { class: 'fineprint', text: 'Vi använder dina uppgifter bara för att hantera din bokning.' }),
    ]);

    function onPick(stamp) {
      start = stamp;
      form.hidden = !stamp;
      error.hidden = true;
      if (!stamp) return;
      summaryBox.replaceChildren(summary([
        ['Tjänst', `${service.name}, ${service.duration_min} min`],
        ['Tid', when(stamp)],
        ['Pris', `${service.price_sek} kr`],
      ]));
      // Only scroll on phones, where the form would otherwise be off screen.
      if (window.innerWidth < 800) form.scrollIntoView({ block: 'nearest' });
    }

    const picker = createPicker({
      mount: pickerMount, serviceId: service.id, today: info.today, maxDays: info.max_days_ahead, onPick,
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!start || !form.reportValidity()) return;
      submit.disabled = true;
      submit.textContent = 'Bokar…';
      error.hidden = true;
      try {
        const data = await api('/api/bookings', { method: 'POST', body: {
          service_id: service.id, start, customer_name: name.value, phone: phone.value,
          email: email.value, note: note.value, website: trap.value,
        } });
        showDone(data.booking);
      } catch (problem) {
        error.textContent = problem.message;
        error.hidden = false;
        submit.disabled = false;
        submit.textContent = 'Bekräfta bokning';
        if (problem.status === 409) picker.reload(); // the time was taken: show fresh times
      }
    });

    mount.replaceChildren(serviceStep, timeStep, form);
  }

  api('/api/info').then((info) => {
    renderHours(info.hours, info.today);
    renderServices(info.services);
    buildBooking(info);
  }).catch(() => {
    mount.replaceChildren(el('p', { class: 'notice error', text: 'Bokningen kan inte nås just nu. Ring oss på 076-419 70 98 så hjälper vi dig.' }));
  });
})();
