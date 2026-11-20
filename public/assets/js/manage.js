/* The customer's own booking page (/bokning?t=...): view, rebook, cancel. */
(() => {
  'use strict';
  const { api, el, summary, createPicker, when } = window.Warrior;
  const mount = document.querySelector('[data-manage]');
  const token = new URLSearchParams(location.search).get('t') || '';

  const fail = (text) => mount.replaceChildren(
    el('p', { class: 'notice error', text }),
    el('p', { class: 'fineprint' }, el('a', { href: '/#boka', text: 'Boka en ny tid' })),
  );

  function details(booking) {
    return summary([
      ['Namn', booking.customer_name],
      ['Tjänst', booking.service],
      ['Tid', when(booking.start)],
      ['Pris', `${booking.price_sek} kr (betalas i salongen)`],
      ['Adress', 'Långholmsgatan 11, Stockholm'],
    ]);
  }

  function show(booking, flash) {
    const cancelled = booking.status === 'cancelled';
    const error = el('p', { class: 'notice error', role: 'alert', hidden: true });
    const parts = [
      el('p', { style: 'text-align:center;margin:0' }, el('span', {
        class: `status-pill ${booking.status}`, text: cancelled ? 'Avbokad' : 'Bokad',
      })),
      flash ? el('p', { class: 'notice', role: 'status', style: 'margin-top:16px', text: flash }) : null,
      details(booking),
    ];

    if (cancelled) {
      parts.push(el('a', { class: 'btn btn-gold btn-block', href: '/#boka', text: 'Boka en ny tid' }));
    } else if (!booking.can_change) {
      parts.push(el('p', { class: 'notice', text: 'Det är för nära inpå för att ändra tiden online. Ring 076-419 70 98 så hjälper vi dig.' }));
    } else {
      const cancelButton = el('button', { type: 'button', class: 'btn btn-danger', text: 'Avboka', onclick: async () => {
        if (!confirm('Vill du avboka din tid?')) return;
        cancelButton.disabled = true;
        try {
          const data = await api(`/api/bookings/${encodeURIComponent(token)}/cancel`, { method: 'POST' });
          show(data.booking, 'Din tid är avbokad.');
        } catch (problem) {
          error.textContent = problem.message; error.hidden = false; cancelButton.disabled = false;
        }
      } });
      parts.push(error, el('div', { class: 'done-actions' }, [
        el('button', { type: 'button', class: 'btn btn-gold', text: 'Boka om', onclick: () => rebook(booking) }),
        cancelButton,
      ]));
    }
    mount.replaceChildren(...parts.filter(Boolean));
  }

  async function rebook(booking) {
    let info;
    try { info = await api('/api/info'); } catch (problem) { return fail(problem.message); }
    let start = null;
    const pickerMount = el('div');
    const error = el('p', { class: 'notice error', role: 'alert', hidden: true });
    const save = el('button', { type: 'button', class: 'btn btn-gold', text: 'Byt till den här tiden', disabled: true });
    const picker = createPicker({
      mount: pickerMount, serviceId: booking.service_id, today: info.today, maxDays: info.max_days_ahead, token,
      onPick: (stamp) => {
        start = stamp;
        save.disabled = !stamp;
        save.textContent = stamp ? `Byt till ${when(stamp)}` : 'Välj en ny tid';
      },
    });
    save.addEventListener('click', async () => {
      save.disabled = true;
      error.hidden = true;
      try {
        const data = await api(`/api/bookings/${encodeURIComponent(token)}/reschedule`, { method: 'POST', body: { start } });
        show(data.booking, 'Din tid är ändrad.');
      } catch (problem) {
        error.textContent = problem.message; error.hidden = false;
        save.disabled = false;
        if (problem.status === 409) picker.reload();
      }
    });
    mount.replaceChildren(
      el('p', { class: 'muted', style: 'margin-top:0', text: `Nuvarande tid: ${when(booking.start)}` }),
      pickerMount, error,
      el('div', { class: 'done-actions' }, [
        save,
        el('button', { type: 'button', class: 'btn btn-ghost', text: 'Behåll min tid', onclick: () => show(booking) }),
      ]),
    );
  }

  if (!token) fail('Länken saknar bokningskod. Använd länken du fick när du bokade.');
  else api(`/api/bookings/${encodeURIComponent(token)}`).then((data) => show(data.booking)).catch((problem) => fail(problem.message));
})();
