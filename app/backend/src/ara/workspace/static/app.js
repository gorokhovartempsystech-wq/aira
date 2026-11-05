import { createAutosave } from "./autosave.js";
import { createHistory } from "./history.js";
import { createTabs, MAX_OPEN_DOCUMENTS } from "./tabs.js";

"use strict";
(() => {
  const el = (id) => document.getElementById(id);
  const tabs = createTabs();
  const MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  const MAX_BYTES = 33554432;
  let automaticBusy = false;
  let busy = false, items = [], offset = 0, hasMore = false;
  let selected = null, file = null, attempt = null;
  let creationAttempt = null;
  let draft = null;
  let confirmingDiscard = false, recoveryBlocked = false;
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

  function notice(text, kind = "") {
    el("notice").textContent = text;
    el("notice").className = `notice ${kind}`;
  }
  function controls() {
    for (const button of document.querySelectorAll("button")) button.disabled = busy;
    el("file").disabled = busy;
    el("title").disabled = busy || attempt !== null;
    el("upload").disabled = busy || !file;
    el("upload").textContent = attempt ? "Повторить загрузку" : "Сохранить документ ↗";
    el("create-name").disabled = busy || creationAttempt !== null;
    el("create-document").textContent = creationAttempt ? "Повторить создание" : "Создать документ";
    el("create-reset").hidden = creationAttempt === null;
    el("create-pending").hidden = creationAttempt === null;
    el("download").disabled = busy || !selected;
    for (const button of document.querySelectorAll(".text-fragment")) button.disabled = busy || recoveryBlocked;
    el("edit-text").disabled = busy && !automaticBusy;
    el("edit-text").readOnly = busy || Boolean(draft?.pending);
    el("edit-save").textContent = draft?.pending ? "Повторить сохранение" : "Сохранить правку";
    el("edit-undo").disabled = busy || !draft || Boolean(draft.pending || draft.composing) || !draft.history?.canUndo();
    el("edit-redo").disabled = busy || !draft || Boolean(draft.pending || draft.composing) || !draft.history?.canRedo();
    el("edit-save").disabled = busy || Boolean(draft?.composing) || !dirty() || [...el("edit-text").value].length > 100000;
    el("edit-cancel").disabled = busy || !draft;
    el("reload-document").disabled = busy || !selected;
    updateTabIndicators();
  }
  function size(bytes) { return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(bytes / 1024) + " КБ"; }
  function date(value) { return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  function metadata(value) {
    if (!value || !uuid.test(value.document_id) || typeof value.title !== "string" ||
        !Number.isInteger(value.current_size_bytes) || value.current_size_bytes < 1 ||
        !Number.isFinite(Date.parse(value.updated_at))) throw new Error("invalid_response");
    return value;
  }
  function failure(error) {
    if (error.recovery && error.status === 409) return "Черновик изменён в другом окне. Ваш текст остался в поле; скопируйте его перед повторным открытием документа.";
    if (error.recovery) return "Не удалось подтвердить копию черновика. Текст остался в поле. Проверьте соединение и повторите сохранение.";
    if (error.creation && error.status === 409) return "Не удалось подтвердить эту попытку создания. Существующий документ сохранён. Проверьте список; для другого документа завершите попытку.";
    if (error.creation) return "Создание ещё не подтверждено. Нажмите «Повторить создание», чтобы получить результат этой попытки.";
    if (error.edit && error.status === 404) return "Документ не найден. Введённый текст остался в поле; скопируйте его перед открытием другого документа.";
    if (error.edit && error.status === 415) return "Запрос правки не принят. Введённый текст остался в поле; попробуйте сохранить его снова.";
    if (error.edit && error.status === 409) return "Документ изменился. Ваш текст остался в поле. Скопируйте его перед повторным открытием документа.";
    if (error.edit && error.status === 422) return "Эту правку не удалось безопасно применить. Проверьте текст; некоторые фрагменты и новые переносы пока не поддерживаются. Введённый текст остался в поле.";
    if (error.edit && error.status === 413) return "Правка превышает технический предел. Сократите текст; он остался в поле.";
    if (error.edit) return "Сохранение ещё не подтверждено. Текст остался в поле, его можно скопировать. Нажмите «Повторить сохранение», чтобы узнать результат этой попытки.";
    if (error.status === 404) return "Документ не найден. Обновите список.";
    if (error.status === 413 && error.view) return "Документ слишком большой для текущего просмотра. Его можно скачать в DOCX.";
    if (error.status === 413) return "Этот файл превышает технический предел загрузки — 32 МБ.";
    if (error.status === 422 || error.status === 415) return "Не удалось открыть DOCX. Проверьте файл и попробуйте другой.";
    if (error.status === 409) return "Загрузка не совпала с предыдущей попыткой. Выберите файл заново.";
    return "Не удалось завершить операцию. Проверьте соединение и повторите попытку.";
  }
  async function request(path, options = {}, timeout = 15000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, { ...options, signal: controller.signal, cache: "no-store" });
      if (!response.ok) { const error = new Error("request_failed"); error.status = response.status; error.view = path.endsWith("/view"); error.edit = path.endsWith("/text-edit"); throw error; }
      if (response.status === 204) return null;
      return options.download ? await response.blob() : await response.json();
    } finally { clearTimeout(timer); }
  }
  async function operation(message, action) {
    if (busy) return;
    busy = true; controls(); notice(message);
    try { await action(); }
    catch (error) { notice(failure(error), "error"); }
    finally { busy = false; controls(); }
  }
  function showSelection(value) {
    clearEditor(); recoveryBlocked = false;
    el("view-body").replaceChildren();
    el("view").hidden = !value;
    el("view-warning").hidden = true;
    el("view-title").textContent = value ? value.title : "";
    el("view-status").textContent = value ? "Загружаем содержимое…" : "";
    el("view-status").className = "muted";
    selected = value;
    el("selection").hidden = !value;
    el("selection-hint").hidden = Boolean(value);
    if (value) {
      el("selected-title").textContent = value.title;
      el("selected-size").textContent = size(value.current_size_bytes);
      el("selected-date").textContent = date(value.updated_at);
    }
    for (const button of el("documents").querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.id === value?.document_id));
    }
  }
  function label(text, kind = "view-label") {
    const element = document.createElement("span");
    element.className = kind; element.textContent = text; return element;
  }
  function dirty() { return draft !== null && el("edit-text").value !== draft.initialInput; }
  function clearEditor() {
    draft?.autosave?.stop();
    draft = null; el("edit-text").value = ""; el("text-editor").hidden = true;
    for (const button of el("view-body").querySelectorAll("button")) button.setAttribute("aria-pressed", "false");
  }
  function editBody(d) {
    return { expected_storage_revision: d.expected_storage_revision, anchor: d.anchor,
      expected_text: d.expected_text, replacement_text: d.replacement };
  }
  function copyPayload(d) {
    return { edit: d.pending ? JSON.parse(d.pending.payload) : editBody(d), operation_id: d.pending?.key || null };
  }
  function copyStatus(d, text) {
    if (draft === d) el("edit-status").textContent = text;
  }
  async function recoveryRequest(d, options) {
    try { return await request(`/docx-documents/${d.document_id}/draft`, options, 15000); }
    catch (error) { error.recovery = true; if (error.status === 409) d.conflict = true; throw error; }
  }
  function persistCopy(d) {
    if (d.saving) return d.saving;
    d.saving = (async () => {
      for (;;) {
        if (!d.checkpoint && [...d.replacement].length > 100000) {
          copyStatus(d, "Текст превышает технический предел — 100000 символов. Его копия не сохранена."); return;
        }
        const payload = copyPayload(d), serialized = JSON.stringify(payload);
        if (!d.checkpoint && serialized === d.lastJSON) return;
        if (!d.checkpoint) d.checkpoint = { expected_token: d.token, token: crypto.randomUUID(), ...payload };
        const checkpoint = d.checkpoint;
        copyStatus(d, "Сохраняем копию черновика…");
        let result;
        try { result = await recoveryRequest(d, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(checkpoint) }); }
        catch (error) { if ([413, 415, 422].includes(error.status)) d.checkpoint = null; throw error; }
        if (result?.document_id !== d.document_id || result.draft?.token !== checkpoint.token) {
          const error = new Error("invalid_draft_receipt"); error.recovery = true; throw error;
        }
        d.token = checkpoint.token; d.lastJSON = JSON.stringify({ edit: checkpoint.edit, operation_id: checkpoint.operation_id });
        d.checkpoint = null;
        if (d.lastJSON === JSON.stringify(copyPayload(d))) {
          copyStatus(d, d.replacement === d.initialInput
            ? "Нет несохранённых изменений в этом фрагменте. Копия черновика обновлена."
            : "Копия черновика сохранена на этом компьютере. В DOCX правка ещё не применена."); return;
        }
      }
    })().finally(() => { d.saving = null; });
    return d.saving;
  }
  async function deleteCopy(d) {
    if (d.token) await recoveryRequest(d, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_token: d.token }) });
  }
  async function leaveEditor() {
    if (confirmingDiscard || draft?.composing) return false;
    if (dirty()) {
      confirmingDiscard = true;
      const dialog = el("discard-dialog"); dialog.returnValue = "stay";
      dialog.querySelector("p").textContent = draft.conflict
        ? "Отбросить свой локальный текст? Черновик другого окна сохранится."
        : draft.pending
        ? "Результат сохранения ещё неизвестен: запись могла состояться. Закрыть эту правку и удалить её черновик? Это не отменит сохранённые изменения."
        : "Отбросить введённый текст и удалить его копию черновика?";
      const discard = await new Promise((resolve) => {
        dialog.addEventListener("close", () => resolve(dialog.returnValue === "discard"), { once: true });
        dialog.showModal();
      });
      confirmingDiscard = false;
      if (!discard) return false;
    }
    const current = draft;
    if (current) {
      busy = true; controls();
      try {
        if (current.saving) { try { await current.saving; } catch (error) { if (!current.conflict) throw error; } }
        if (!current.conflict && (current.token || current.checkpoint)) {
          await persistCopy(current); await deleteCopy(current);
        }
      } catch (error) { notice(failure(error), "error"); return false; }
      finally { busy = false; controls(); }
    }
    clearEditor(); controls(); return true;
  }
  function openEditor(d, replacement, message) {
    el("edit-text").value = d.expected_text;
    d.initialInput = el("edit-text").value;
    el("edit-text").value = replacement; d.replacement = el("edit-text").value;
    d.history = createHistory({ text: d.initialInput, start: d.initialInput.length, end: d.initialInput.length });
    d.history.record(editorSnapshot());
    draft = d; el("text-editor").hidden = false;
    el("edit-status").textContent = message;
    attachAutosave(d); controls();
    el("text-editor").scrollIntoView({ block: "center" }); el("edit-text").focus({ preventScroll: true });
  }
  function attachAutosave(d) {
    d.autosave = createAutosave({
      hasChanges: () => draft === d && dirty() && !d.composing && !d.pending && !d.conflict && !d.autoPaused && !d.autoBlocked && !recoveryBlocked && [...d.replacement].length <= 100000,
      canSave: () => !busy && !confirmingDiscard,
      save: () => saveCurrent(true, d),
      onError: () => {
        d.autoPaused = true;
        copyStatus(d, "Автосохранение не завершено. Текст остался в поле; сохраните правку вручную.");
      },
    });
    d.autosave.touch();
  }
  function newDraft(document_id, edit, token = null) {
    return { document_id, ...edit, token, checkpoint: null, lastJSON: null, saving: null, conflict: false };
  }
  async function editFragment(view, span, button) {
    if (busy || recoveryBlocked || !(await leaveEditor())) return;
    openEditor(newDraft(view.document_id, { expected_storage_revision: view.storage_revision,
      anchor: span.anchor, expected_text: span.text }), span.text, "Измените текст и сохраните правку.");
    button.setAttribute("aria-pressed", "true");
  }
  async function restoreCopy(view) {
    try {
      const result = await request(`/docx-documents/${view.document_id}/draft`);
      if (result?.document_id !== view.document_id || !Object.hasOwn(result, "draft")) throw new Error("invalid_draft");
      if (!result.draft) return true;
      const saved = result.draft;
      if (!uuid.test(saved.token) || !saved.edit || typeof saved.edit.expected_storage_revision !== "string" ||
          typeof saved.edit.expected_text !== "string" || typeof saved.edit.replacement_text !== "string" ||
          !saved.edit.anchor || (saved.operation_id !== null && !uuid.test(saved.operation_id))) throw new Error("invalid_draft");
      const d = newDraft(view.document_id, saved.edit, saved.token);
      d.lastJSON = JSON.stringify({ edit: saved.edit, operation_id: saved.operation_id });
      if (saved.operation_id) d.pending = { key: saved.operation_id, payload: JSON.stringify(saved.edit) };
      const message = d.pending ? "Восстановлена неподтверждённая попытка. Нажмите «Повторить сохранение», чтобы узнать её результат."
        : (view.storage_revision === d.expected_storage_revision ? "Восстановлен черновик. В DOCX правка ещё не применена."
          : "Восстановлен черновик, но документ уже изменился. Скопируйте текст перед повторным открытием; чужие изменения не будут перезаписаны.");
      openEditor(d, saved.edit.replacement_text, message); return true;
    } catch (_) {
      recoveryBlocked = true; controls();
      notice("Не удалось прочитать черновик. Переоткройте документ перед редактированием: сохранённая копия может существовать.", "error"); return false;
    }
  }
  function renderBlocks(blocks, parent, view) {
    for (const block of blocks) {
      if (block.kind === "paragraph") {
        const paragraph = document.createElement("p"); paragraph.className = "view-paragraph";
        if (block.numbering_id !== null) paragraph.append(label("Элемент списка"));
        for (const span of block.spans) {
          if (span.kind === "opaque") paragraph.append(label("Непоказанный элемент", "view-opaque"));
          else if (span.kind === "text" && [...span.text].length <= 100000) {
            const button = document.createElement("button"); button.type = "button";
            button.className = "text-fragment"; button.textContent = span.text || "(пустой фрагмент)";
            if (span.text === "") button.dataset.empty = "true";
            button.setAttribute("aria-pressed", String(draft?.document_id === view.document_id &&
              draft.anchor.source_sha256 === span.anchor.source_sha256 && draft.anchor.part_name === span.anchor.part_name &&
              JSON.stringify(draft.anchor.path) === JSON.stringify(span.anchor.path)));
            button.addEventListener("click", () => editFragment(view, span, button)); paragraph.append(button);
          } else paragraph.append(document.createTextNode(span.text));
        }
        parent.append(paragraph);
      } else if (block.kind === "table") {
        const wrapper = document.createElement("div"), table = document.createElement("table");
        wrapper.className = "view-table-wrap"; table.className = "view-table";
        table.setAttribute("aria-label", "Таблица документа");
        const body = document.createElement("tbody");
        for (const row of block.rows) {
          const tr = document.createElement("tr");
          for (const cell of row.cells) {
            const td = document.createElement("td");
            if (cell.grid_span !== null && cell.grid_span !== "1") td.append(label("Объединённая ячейка"));
            if (cell.vertical_merge !== null) td.append(label("Вертикальное объединение"));
            renderBlocks(cell.blocks, td, view); tr.append(td);
          }
          body.append(tr);
        }
        table.append(body); wrapper.append(table); parent.append(wrapper);
      } else if (block.kind === "opaque") {
        const unknown = document.createElement("p"); unknown.className = "view-opaque";
        unknown.textContent = "Элемент сохранён в DOCX, но пока не отображается."; parent.append(unknown);
      } else throw new Error("invalid_view");
    }
  }
  async function loadView(current, restore = true) {
    try {
      const view = metadata(await request(`/docx-documents/${current.document_id}/view`));
      if (view.document_id !== current.document_id || !Array.isArray(view.blocks) ||
          typeof view.storage_revision !== "string" || view.coverage_scope !== "main-body-structural-v1") {
        throw new Error("invalid_view");
      }
      const fragment = document.createDocumentFragment(); renderBlocks(view.blocks, fragment, view);
      showSelection(view); el("view-body").append(fragment);
      el("view-warning").hidden = !view.has_unprojected_content;
      el("view-status").textContent = "Нажмите на текст, чтобы изменить отдельный фрагмент. Оформление Word в этом виде может отличаться.";
      return restore ? await restoreCopy(view) : true;
    } catch (error) {
      el("view-body").replaceChildren();
      el("view-status").textContent = failure(error); el("view-status").className = "muted view-failure";
      notice(failure(error), "error"); return false;
    }
  }
  function noticeState() { return { text: el("notice").textContent, kind: el("notice").className }; }
  function frameDirty(frame) {
    const d = frame?.draft; return Boolean(d && (d.pending || d.replacement !== d.initialInput));
  }
  function tabCapacity(id) {
    if (tabs.has(id) || tabs.entries().length < MAX_OPEN_DOCUMENTS) return true;
    notice(`Одновременно можно открыть ${MAX_OPEN_DOCUMENTS} документов. Закройте одну из вкладок.`, "error"); return false;
  }
  function updateTabIndicators() {
    for (const { id, value } of tabs.entries()) {
      const button = el("tab-" + id); if (!button) continue;
      const active = id === tabs.activeId(), d = active ? draft : value.draft;
      const title = active ? selected?.title : value.selected?.title;
      const state = d?.pending ? " · требуется подтверждение" : (d && d.replacement !== d.initialInput ? " · черновик" : "");
      button.textContent = (title || "Документ") + state;
      button.title = (title || "Документ") + state + ". Delete — закрыть вкладку";
      button.tabIndex = active ? 0 : -1; button.setAttribute("aria-selected", String(active));
    }
  }
  function renderTabs() {
    el("document-tabs").replaceChildren();
    el("tabs-section").hidden = tabs.entries().length === 0;
    for (const { id, value } of tabs.entries()) {
      const wrapper = document.createElement("div"); wrapper.className = "tab-item";
      const button = document.createElement("button"), close = document.createElement("button");
      button.type = "button"; button.className = "document-tab"; button.id = "tab-" + id; button.disabled = busy;
      button.setAttribute("role", "tab"); button.setAttribute("aria-controls", "view");
      button.setAttribute("aria-keyshortcuts", "Delete");
      button.addEventListener("click", () => { void activateDocument(id, true); });
      button.addEventListener("keydown", event => {
        const ids = tabs.entries().map(entry => entry.id), index = ids.indexOf(id);
        let target = null;
        if (event.key === "ArrowRight") target = ids[(index + 1) % ids.length];
        if (event.key === "ArrowLeft") target = ids[(index - 1 + ids.length) % ids.length];
        if (event.key === "Home") target = ids[0];
        if (event.key === "End") target = ids[ids.length - 1];
        if (target) { event.preventDefault(); void activateDocument(target, true); }
        if (event.key === "Delete") { event.preventDefault(); void closeTab(id); }
      });
      close.type = "button"; close.className = "tab-close"; close.disabled = busy; close.tabIndex = -1; close.textContent = "×";
      close.setAttribute("aria-label", "Закрыть " + (value.selected?.title || "документ"));
      close.title = "Закрыть вкладку (Delete)";
      close.addEventListener("click", () => { void closeTab(id); });
      wrapper.append(button, close); el("document-tabs").append(wrapper);
    }
    el("view").setAttribute("aria-labelledby", tabs.activeId() ? "tab-" + tabs.activeId() : "view-heading");
    updateTabIndicators();
  }
  async function confirmCopy(d) {
    if (!d) return;
    try {
    if ([...d.replacement].length > 100000) { const error = new Error("draft_limit"); error.recovery = true; error.status = 413; throw error; }
    if (d.saving) await d.saving;
    if (d.conflict) { const error = new Error("draft_conflict"); error.recovery = true; error.status = 409; throw error; }
    if (d.pending || d.replacement !== d.initialInput || d.token || d.checkpoint) await persistCopy(d);
    if (d.token) {
      const result = await recoveryRequest(d, {});
      if (result?.document_id !== d.document_id || result.draft?.token !== d.token) {
        d.conflict = true; const error = new Error("draft_conflict"); error.recovery = true; error.status = 409; throw error;
      }
    }
    } catch (error) { copyStatus(d, failure(error)); throw error; }
  }
  async function parkActive(previousNotice) {
    const id = tabs.activeId(); if (!id || !selected) return;
    const d = draft;
    await confirmCopy(d);
    const selection = d ? editorSnapshot() : null;
    if (d) { d.history.capture(selection); d.autosave.stop(); }
    Object.assign(tabs.get(id), {
      selected, draft: d, selection, nodes: [...el("view-body").childNodes],
      viewHidden: el("view").hidden, viewStatus: el("view-status").textContent,
      viewClass: el("view-status").className, warningHidden: el("view-warning").hidden,
      editorStatus: el("edit-status").textContent, editorHeight: el("edit-text").style.height,
      recoveryBlocked, notice: previousNotice || noticeState(),
    });
    // Keep the visible draft attached until the next frame is actually shown,
    // including during slow GET/import and beforeunload checks.
  }
  function restoreFrame(frame) {
    showSelection(frame.selected);
    el("view-body").replaceChildren(...(frame.nodes || []));
    el("view").hidden = Boolean(frame.viewHidden);
    el("view-status").textContent = frame.viewStatus || ""; el("view-status").className = frame.viewClass || "muted";
    el("view-warning").hidden = frame.warningHidden ?? true; recoveryBlocked = Boolean(frame.recoveryBlocked);
    if (frame.draft) {
      draft = frame.draft;
      el("text-editor").hidden = false; el("edit-text").value = draft.replacement;
      el("edit-text").style.height = frame.editorHeight || "";
      if (frame.selection) el("edit-text").setSelectionRange(frame.selection.start, frame.selection.end);
      el("edit-status").textContent = frame.editorStatus || "Черновик восстановлен во вкладке.";
      attachAutosave(draft);
    }
    if (frame.notice) { el("notice").textContent = frame.notice.text; el("notice").className = frame.notice.kind; }
    renderTabs(); controls();
  }
  async function activateDocument(id, focusTab = false) {
    if (busy || confirmingDiscard || draft?.composing || !tabCapacity(id)) return;
    if (tabs.activeId() === id) { if (focusTab) el("tab-" + id)?.focus(); return; }
    const previousId = tabs.activeId(), previousNotice = noticeState();
    await operation("Открываем документ…", async () => {
      let parked = false;
      try {
        await parkActive(previousNotice); parked = true;
        if (tabs.has(id)) { tabs.activate(id); restoreFrame(tabs.get(id)); }
        else {
          const current = metadata(await request(`/docx-documents/${id}`));
          tabs.open(id, { selected: current }); showSelection(current); renderTabs();
          if (await loadView(current)) notice("Содержимое документа открыто.");
        }
      } catch (error) {
        if (parked && previousId && tabs.has(previousId)) { tabs.activate(previousId); restoreFrame(tabs.get(previousId)); }
        throw error;
      }
    });
    if (focusTab) el("tab-" + tabs.activeId())?.focus({ preventScroll: true });
  }
  async function closeTab(id) {
    if (busy || confirmingDiscard || draft?.composing || !tabs.has(id)) return;
    const active = id === tabs.activeId(), frame = tabs.get(id), d = active ? draft : frame.draft;
    if (d && (d.pending || d.replacement !== d.initialInput)) {
      confirmingDiscard = true;
      const dialog = el("close-tab-dialog"); dialog.returnValue = "stay";
      el("close-tab-title").textContent = "Закрыть «" + (frame.selected?.title || "документ") + "»?";
      const close = await new Promise(resolve => {
        dialog.addEventListener("close", () => resolve(dialog.returnValue === "close"), { once: true }); dialog.showModal();
      });
      confirmingDiscard = false; if (!close) return;
    }
    const previousNotice = noticeState();
    await operation("Закрываем вкладку…", async () => {
      try { if (active) await parkActive(previousNotice); else await confirmCopy(d); }
      catch (error) { notice("Вкладка «" + (frame.selected?.title || "документ") + "» не закрыта. " + failure(error), "error"); return; }
      d?.autosave?.stop(); tabs.close(id);
      if (active) {
        if (tabs.activeId()) restoreFrame(tabs.get(tabs.activeId()));
        else { showSelection(null); renderTabs(); }
      } else renderTabs();
      notice("Вкладка закрыта. Сохранённый черновик доступен при открытии документа.");
    });
    (el("tab-" + tabs.activeId()) || el("refresh")).focus({ preventScroll: true });
  }
  el("reload-document").addEventListener("click", async () => {
    if (busy || confirmingDiscard || !selected || !(await leaveEditor())) return;
    const id = selected.document_id;
    await operation("Обновляем документ…", async () => {
      const current = metadata(await request(`/docx-documents/${id}`));
      showSelection(current); renderTabs();
      if (await loadView(current)) notice("Документ обновлён.");
    });
  });
  function renderList() {
    el("documents").replaceChildren();
    for (const item of items) {
      const li = document.createElement("li"), button = document.createElement("button");
      button.type = "button"; button.className = "document"; button.dataset.id = item.document_id;
      button.setAttribute("aria-pressed", String(selected?.document_id === item.document_id));
      const icon = document.createElement("span"), copy = document.createElement("span");
      icon.className = "doc-icon"; icon.textContent = "DOCX"; icon.setAttribute("aria-hidden", "true");
      copy.className = "doc-copy";
      const title = document.createElement("span"), meta = document.createElement("span");
      title.className = "doc-title"; title.textContent = item.title;
      meta.className = "doc-meta"; meta.textContent = `${size(item.current_size_bytes)} · ${date(item.updated_at)}`;
      copy.append(title, meta);
      const arrow = document.createElement("span"); arrow.className = "doc-arrow"; arrow.textContent = "›"; arrow.setAttribute("aria-hidden", "true");
      button.append(icon, copy, arrow); li.append(button); el("documents").append(li);
      button.addEventListener("click", () => { void activateDocument(item.document_id); });
    }
    el("empty").hidden = items.length > 0;
    el("count").textContent = `Загружено документов: ${items.length}`;
    el("more").hidden = !hasMore;
    controls();
  }
  async function loadList(reset = true) {
    const start = reset ? 0 : offset;
    const result = await request(`/docx-documents?limit=20&offset=${start}`);
    if (!result || !Array.isArray(result.items) || result.items.length > 20) throw new Error("invalid_response");
    const page = result.items.map(metadata);
    const combined = reset ? page : [...items, ...page];
    items = [...new Map(combined.map((item) => [item.document_id, item])).values()];
    offset = start + page.length; hasMore = page.length === 20; renderList();
  }
  el("refresh").addEventListener("click", () => operation("Обновляем список…", async () => {
    await loadList(); notice("Список обновлён.");
  }));
  el("more").addEventListener("click", () => operation("Загружаем документы…", async () => {
    await loadList(false); notice("Следующая страница загружена.");
  }));
  el("file").addEventListener("change", () => {
    if (busy) return;
    attempt = null; file = el("file").files[0] || null;
    if (file && (!/\.docx$/i.test(file.name) || file.size < 1 || file.size > MAX_BYTES)) {
      notice("Выберите непустой файл .docx размером не больше 32 МБ.", "error");
      file = null; el("file").value = "";
    }
    el("title").value = file ? file.name.replace(/\.docx$/i, "") : ""; controls();
  });
  function validTitle(value) {
    return Boolean(value.trim()) && [...value].length <= 200 && !/\u0000|[\uD800-\uDFFF]/u.test(value);
  }
  el("create-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || confirmingDiscard || draft?.composing) return;
    const title = el("create-name").value;
    if (!creationAttempt && !validTitle(title)) {
      notice("Введите название: от 1 до 200 символов без служебных знаков.", "error"); return;
    }
    if (!creationAttempt) creationAttempt = { id: crypto.randomUUID(), title };
    const current = creationAttempt;
    if (!tabCapacity(current.id)) { controls(); return; }
    const previousId = tabs.activeId(), previousNotice = noticeState();
    let opened = null;
    await operation("Создаём документ…", async () => {
      let parked = false;
      try {
        await parkActive(previousNotice); parked = true;
        let result;
        try {
          result = metadata(await request(`/docx-documents/${current.id}/create?${new URLSearchParams({title:current.title})}`,
            { method:"POST" }, 60000));
          if (result.document_id !== current.id) throw new Error("invalid_create_receipt");
        } catch (error) { error.creation = true; throw error; }
        creationAttempt = null; el("create-name").value = "";
        let viewReady;
        if (tabs.has(result.document_id)) {
          tabs.activate(result.document_id); restoreFrame(tabs.get(result.document_id));
          viewReady = !recoveryBlocked && !el("view").hidden;
        } else {
          tabs.open(result.document_id, { selected:result }); showSelection(result); renderTabs();
          viewReady = await loadView(result);
        }
        if (viewReady) opened = result.document_id;
        notice("Документ создан.", "success");
        try { await loadList(); }
        catch (_) { notice("Документ создан. Список не обновился — нажмите «Обновить».", "error"); }
        if (!viewReady) notice("Документ создан. Просмотр недоступен; файл можно скачать.", "error");
      } catch (error) {
        if (parked && previousId && tabs.has(previousId)) { tabs.activate(previousId); restoreFrame(tabs.get(previousId)); }
        throw error;
      }
    });
    if (opened === selected?.document_id && !draft && !recoveryBlocked) {
      el("view-body").querySelector('.text-fragment[data-empty="true"]')?.click();
    }
  });
  el("create-reset").addEventListener("click", async () => {
    if (busy || confirmingDiscard || !creationAttempt) return;
    confirmingDiscard = true;
    const dialog = el("create-reset-dialog"); dialog.returnValue = "stay";
    const finish = await new Promise(resolve => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "finish"), { once:true }); dialog.showModal();
    });
    confirmingDiscard = false;
    if (finish) {
      creationAttempt = null;
      notice("Попытка завершена. Если документ успел создаться, он остался в списке — нажмите «Обновить».");
    }
    controls(); el(finish ? "create-name" : "create-document").focus({preventScroll:true});
  });
  el("upload-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (busy || confirmingDiscard || draft?.composing || !file) return;
    const title = el("title").value;
    // JS length counts UTF-16 units; the server's title bound is Unicode code points.
    if (!validTitle(title)) {
      notice("Введите название: от 1 до 200 символов без служебных знаков.", "error"); return;
    }
    if (!attempt) attempt = { id: crypto.randomUUID(), file, title };
    if (!tabCapacity(attempt.id)) return;
    const previousId = tabs.activeId(), previousNotice = noticeState();
    operation("Сохраняем документ…", async () => {
      let parked = false;
      try {
      await parkActive(previousNotice); parked = true;
      const current = attempt;
      const result = metadata(await request(`/docx-documents/${current.id}/import?${new URLSearchParams({ title: current.title })}`,
        { method: "POST", headers: { "Content-Type": MIME }, body: current.file }, 60000));
      attempt = null; file = null; el("file").value = ""; el("title").value = "";
      tabs.open(result.document_id, { selected: result });
      showSelection(result); renderTabs();
      // A confirmed import remains confirmed even if the subsequent list refresh fails.
      notice("Документ сохранён.", "success");
      try { await loadList(); }
      catch (_) { notice("Документ сохранён. Список не обновился — нажмите «Обновить».", "error"); }
      if (!(await loadView(result))) notice("Документ сохранён. Просмотр недоступен; файл можно скачать.", "error");
      } catch (error) {
        if (parked && previousId && tabs.has(previousId)) { tabs.activate(previousId); restoreFrame(tabs.get(previousId)); }
        throw error;
      }
    });
  });
  function editorSnapshot() {
    const field = el("edit-text");
    return { text: field.value, start: field.selectionStart, end: field.selectionEnd };
  }
  function syncDraftText() {
    const current = draft; current.replacement = el("edit-text").value;
    current.autoPaused = false;
    if ([...current.replacement].length > 100000) {
      el("edit-status").textContent = "Текст превышает технический предел — 100000 символов. Его копия не сохранена.";
      controls(); return;
    }
    controls(); persistCopy(current).catch(error => copyStatus(current, failure(error)));
    current.autosave.touch();
  }
  function textChanged(event, before = null) {
    if (!draft || busy || draft.pending || draft.composing || event.isComposing) return;
    draft.history.record(editorSnapshot(), { before, inputType: event.inputType || "", time: event.timeStamp });
    syncDraftText();
  }
  function historyChange(direction) {
    if (!draft || busy || draft.pending || draft.composing) return;
    draft.history.capture(editorSnapshot());
    const value = draft.history[direction]();
    if (!value) { controls(); return; }
    const field = el("edit-text"); field.value = value.text;
    field.focus({ preventScroll: true }); field.setSelectionRange(value.start, value.end);
    draft.beforeInput = null; syncDraftText();
  }
  el("edit-text").addEventListener("beforeinput", event => {
    if (!draft || busy || draft.pending || draft.composing || event.isComposing) return;
    if (event.cancelable && ["historyUndo", "historyRedo"].includes(event.inputType)) {
      event.preventDefault(); historyChange(event.inputType === "historyUndo" ? "undo" : "redo"); return;
    }
    draft.beforeInput = editorSnapshot();
  });
  el("edit-text").addEventListener("input", event => {
    const before = draft?.beforeInput || null;
    if (draft) draft.beforeInput = null;
    textChanged(event, before);
  });
  el("edit-text").addEventListener("compositionstart", () => {
    if (!draft || busy || draft.pending) return;
    draft.compositionBefore = editorSnapshot(); draft.history.capture(draft.compositionBefore);
    draft.beforeInput = null; draft.composing = true; controls();
  });
  el("edit-text").addEventListener("compositionend", event => {
    if (!draft || !draft.composing) return;
    const before = draft.compositionBefore; draft.compositionBefore = null; draft.composing = false;
    textChanged({ inputType: "insertCompositionText", timeStamp: event.timeStamp }, before);
  });
  el("edit-text").addEventListener("keydown", event => {
    if (event.isComposing || draft?.composing || event.altKey || !(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key !== "z" && !(key === "y" && !event.shiftKey)) return;
    event.preventDefault(); historyChange(key === "y" || event.shiftKey ? "redo" : "undo");
  });
  el("edit-undo").addEventListener("click", () => historyChange("undo"));
  el("edit-redo").addEventListener("click", () => historyChange("redo"));
  el("edit-cancel").addEventListener("click", async () => {
    if (busy) return;
    const pending = Boolean(draft?.pending), conflict = Boolean(draft?.conflict);
    if (await leaveEditor()) notice(conflict ? "Локальная правка закрыта. Черновик другого окна сохранён." : pending ? "Правка закрыта. Это не отменяет возможную запись; откройте документ, чтобы увидеть сохранённый текст." : "Черновик удалён.");
  });
  async function finishAutomatic(current, result) {
    const savedEdit = JSON.parse(current.pending.payload);
    current.expected_storage_revision = result.storage_revision;
    current.expected_text = savedEdit.replacement_text;
    current.anchor = { ...savedEdit.anchor, source_sha256: result.current_sha256 };
    current.initialInput = el("edit-text").value;
    current.pending = null; current.token = null; current.checkpoint = null; current.lastJSON = null;
    current.autoPaused = false;
    selected = result;
    el("selected-title").textContent = result.title;
    el("selected-size").textContent = size(result.current_size_bytes);
    el("selected-date").textContent = date(result.updated_at);
    copyStatus(current, "Автосохранено. Можно продолжать редактирование.");
    notice("Изменения автоматически сохранены.", "success");
    try { await loadList(); }
    catch (_) { notice("Автосохранено. Список не обновился — нажмите «Обновить».", "error"); }
    try {
      const view = metadata(await request(`/docx-documents/${current.document_id}/view`));
      if (view.document_id !== current.document_id || view.storage_revision !== result.storage_revision ||
          view.current_sha256 !== result.current_sha256 || !Array.isArray(view.blocks) ||
          view.coverage_scope !== "main-body-structural-v1") throw new Error("view_changed");
      const fragment = document.createDocumentFragment(); renderBlocks(view.blocks, fragment, view);
      el("view-body").replaceChildren(fragment);
      el("view-warning").hidden = !view.has_unprojected_content;
    } catch (_) {
      current.autoBlocked = true; recoveryBlocked = true;
      notice("Автосохранено. Просмотр не обновился — переоткройте документ перед дальнейшей работой.", "error");
    }
  }
  async function saveCurrent(automatic = false, expectedDraft = draft) {
    if (busy || confirmingDiscard || !draft || draft.composing || expectedDraft !== draft || !dirty() || [...el("edit-text").value].length > 100000) return;
    const current = draft, createdPending = !current.pending;
    if (automatic && (current.pending || current.conflict || current.autoPaused || current.autoBlocked || recoveryBlocked)) return;
    if (!current.pending) current.pending = { key: crypto.randomUUID(), payload: JSON.stringify(editBody(current)) };
    automaticBusy = automatic;
    try { await operation(automatic ? "Автосохранение изменений…" : "Сохраняем правку…", async () => {
      try { await persistCopy(current); }
      catch (error) {
        current.autoPaused = true;
        if (createdPending) current.pending = null;
        copyStatus(current, failure(error)); notice(failure(error), "error"); return;
      }
      let result;
      try {
        result = metadata(await request(`/docx-documents/${current.document_id}/text-edit`, {
          method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": current.pending.key },
          body: current.pending.payload,
        }, 60000));
        const expected = JSON.parse(current.pending.payload).expected_storage_revision;
        if (result.document_id !== current.document_id || typeof result.storage_revision !== "string" ||
            !/^[1-9][0-9]{0,18}$/.test(result.storage_revision) || BigInt(result.storage_revision) !== BigInt(expected) + 1n ||
            typeof result.current_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(result.current_sha256)) throw new Error("invalid_receipt");
      } catch (error) {
        current.autoPaused = true;
        if (error.status === 409) current.autoBlocked = true;
        if ([404, 409, 413, 415, 422].includes(error.status)) {
          current.pending = null;
          try { await persistCopy(current); } catch (_) { /* The previous recovery copy remains. */ }
        }
        error.edit = true; const message = failure(error);
        copyStatus(current, message); notice(message, "error"); return;
      }
      let removed = true;
      try { await deleteCopy(current); } catch (_) { removed = false; }
      if (automatic && removed) { await finishAutomatic(current, result); return; }
      clearEditor(); showSelection(result); notice("Правка сохранена.", "success");
      try { await loadList(); }
      catch (_) { notice("Правка сохранена. Список не обновился — нажмите «Обновить».", "error"); }
      if (!(await loadView(result, false))) notice("Правка сохранена. Просмотр недоступен; файл можно скачать.", "error");
      if (!removed) notice("Правка сохранена. Копию черновика удалить не удалось; переоткройте документ перед следующей правкой.", "error");
    }); } finally { automaticBusy = false; controls(); }
  }
  el("edit-save").addEventListener("click", () => { void saveCurrent(); });
  window.addEventListener("beforeunload", (event) => {
    if (creationAttempt || dirty() || draft?.pending || tabs.entries().some(({id,value}) => id !== tabs.activeId() && frameDirty(value))) {
      event.preventDefault(); event.returnValue = "";
    }
  });
  el("download").addEventListener("click", () => {
    if (dirty()) { notice("Сначала сохраните или отмените правку, затем скачайте документ.", "error"); return; }
    operation("Подготавливаем файл…", async () => {
    if (!selected) return;
    const identity = selected.document_id;
    const blob = await request(`/docx-documents/${identity}/content`, { download: true });
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = `${identity}.docx`; document.body.append(link);
    link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice("Файл передан браузеру для скачивания.", "success");
    });
  });
  operation("Загружаем список документов…", async () => { await loadList(); notice("Список документов готов."); });
})();
