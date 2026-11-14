import { h, toast, modal } from './ui.mjs';

export function createUpdates({ api, host, parent }) {
  let busy = false, installing = false, latest = null, dismissed = null;
  const banner = h('div', { class: 'update-banner', role: 'status', hidden: true });
  parent.append(banner);

  function render() {
    banner.hidden = !latest || latest.status !== 'available' || dismissed === latest.latest_version;
    banner.replaceChildren();
    if (banner.hidden) return;
    banner.append(h('span', {}, `Доступна AIRA ${latest.latest_version}`),
      h('button', { class: 'btn primary sm', disabled: installing, onclick: install }, installing ? 'Подготавливаем обновление…' : 'Обновить'),
      h('button', { class: 'btn sm', onclick: () => { dismissed = latest.latest_version; render(); } }, 'Позже'));
  }

  async function install() {
    if (installing || !host.checkUpdates) return;
    const answer = await modal({ title: 'Обновить AIRA?',
      body: 'Новая сборка загрузится с сервера AIRA. Перед установкой приложение сохранит документы и завершит работу. После обновления работа продолжится в новой версии.',
      actions: [{ id: 'later', label: 'Позже' }, { id: 'update', label: 'Обновить', kind: 'primary' }] });
    if (answer?.id !== 'update') return;
    installing = true; render();
    try { if (await host.checkUpdates() === false) throw new Error('update_not_started'); }
    catch { toast('Не удалось начать обновление. Попробуйте ещё раз через меню «?».', 'warn'); }
    finally { installing = false; render(); }
  }

  return {
    async check(manual = false) {
      if (busy || !host.checkUpdates) return;
      busy = true;
      try {
        const value = await api.updates(manual);
        if (!['available', 'current'].includes(value?.status)
            || !/^[0-9]+\.[0-9]+\.[0-9]+$/.test(value.latest_version || '')) throw new Error('invalid_update');
        latest = value;
        if (manual) dismissed = null;
        render();
        if (manual && value.status === 'current') toast(`Установлена актуальная версия AIRA ${value.current_version}.`, 'ok');
      } catch {
        if (manual) toast('Не удалось проверить обновления. Проверьте интернет и повторите попытку.', 'warn');
      } finally { busy = false; }
    },
  };
}
