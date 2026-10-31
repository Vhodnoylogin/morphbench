/* A neutral consumer of the public add-on SDK. No host-page or core imports. */
;(function () {
  "use strict";
  const sdk = window.MorphbenchAddon;
  const elements = {};
  for (const id of ["title", "scope", "status", "error", "controls", "controls-label",
    "refresh", "model-label", "model", "open-model", "morph-label", "morph", "value-label",
    "value", "apply-morph", "reset-morphs", "preset-label", "preset", "apply-preset",
    "scene-label", "scene"]) elements[id] = document.getElementById(id);

  const translations = {
    en: {
      title: "Scene inspector", scope: "Browser preview only. Opening a model reloads the page and resets unsaved preview changes.",
      "controls-label": "Controls", refresh: "Refresh scene", "model-label": "Model",
      "open-model": "Open model", "morph-label": "Morph", "value-label": "Value",
      "apply-morph": "Apply morph", "reset-morphs": "Reset all morphs", "preset-label": "View preset",
      "apply-preset": "Apply view", "scene-label": "Scene snapshot", ready: "Connected",
      loading: "Reading scene…", navigating: "Opening model…", empty: "None available",
      finite: "Enter a finite number.", missing: "Select an available item.",
      failed: "The request failed.", unavailable: "The local Morphbench add-on SDK could not be loaded."
    },
    ru: {
      title: "Инспектор сцены", scope: "Только предпросмотр в браузере. Открытие модели перезагружает страницу и сбрасывает несохранённые изменения предпросмотра.",
      "controls-label": "Управление", refresh: "Обновить сцену", "model-label": "Модель",
      "open-model": "Открыть модель", "morph-label": "Морф", "value-label": "Значение",
      "apply-morph": "Применить морф", "reset-morphs": "Сбросить все морфы", "preset-label": "Ракурс",
      "apply-preset": "Применить ракурс", "scene-label": "Снимок сцены", ready: "Подключено",
      loading: "Чтение сцены…", navigating: "Открытие модели…", empty: "Нет доступных",
      finite: "Введите конечное число.", missing: "Выберите доступный элемент.",
      failed: "Ошибка запроса.", unavailable: "Не удалось загрузить локальный SDK дополнений Morphbench."
    }
  };
  let labels = translations.en;
  let currentMorphs = {};
  let refreshing = false;
  let refreshAgain = false;
  let debounce = null;
  let stopped = false;
  let unsubscribe = function () {};

  function showError(error) {
    elements.error.textContent = (error.code ? error.code + ": " : "") + (error.message || labels.failed);
    elements.error.hidden = false;
  }

  function choices(select, names) {
    const selected = select.value;
    select.replaceChildren();
    for (const name of names) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    }
    if (names.includes(selected)) select.value = selected;
    if (!names.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = labels.empty;
      select.appendChild(option);
    }
    select.disabled = names.length === 0;
  }

  function morphValue() {
    elements.value.value = currentMorphs[elements.morph.value] || 0;
  }

  async function refresh() {
    if (stopped) return;
    if (refreshing) { refreshAgain = true; return; }
    refreshing = true;
    elements.status.textContent = labels.loading;
    elements.error.hidden = true;
    try {
      const [scene, catalog, view] = await Promise.all([
        sdk.request("scene.get"), sdk.request("models.list"), sdk.request("view.get")
      ]);
      const morphs = scene.open ? await sdk.request("morphs.get") : { names: [], values: {} };
      if (stopped) return;
      elements.scene.textContent = JSON.stringify(scene, null, 2);
      choices(elements.model, catalog.entries.map(function (entry) { return entry.name; }));
      choices(elements.morph, morphs.names);
      currentMorphs = morphs.values;
      morphValue();
      choices(elements.preset, Object.keys(view.presets));
      elements["open-model"].disabled = !catalog.entries.length;
      elements["apply-morph"].disabled = !morphs.names.length;
      elements["reset-morphs"].disabled = !morphs.names.length;
      elements["apply-preset"].disabled = !scene.open || !Object.keys(view.presets).length;
      elements.status.textContent = labels.ready;
    } catch (error) {
      if (!stopped) { showError(error); elements.status.textContent = labels.ready; }
    } finally {
      refreshing = false;
      if (refreshAgain && !stopped) { refreshAgain = false; scheduleRefresh(); }
    }
  }

  function scheduleRefresh() {
    if (stopped) return;
    window.clearTimeout(debounce);
    debounce = window.setTimeout(refresh, 150);
  }

  async function action(method, params, navigating) {
    elements.error.hidden = true;
    try {
      await sdk.request(method, params);
      if (navigating) elements.status.textContent = labels.navigating;
      else scheduleRefresh();
    } catch (error) { showError(error); }
  }

  function selection(select) {
    if (!select.value) { showError(new Error(labels.missing)); return null; }
    return select.value;
  }

  elements.refresh.addEventListener("click", refresh);
  elements.morph.addEventListener("change", morphValue);
  elements["open-model"].addEventListener("click", function () {
    const name = selection(elements.model);
    if (name) action("models.open", { name: name }, true);
  });
  elements["apply-morph"].addEventListener("click", function () {
    const name = selection(elements.morph);
    if (!name) return;
    const value = Number(elements.value.value);
    if (!elements.value.value.trim() || !Number.isFinite(value)) {
      showError(new Error(labels.finite));
      return;
    }
    action("morphs.set", { values: { [name]: value } });
  });
  elements["reset-morphs"].addEventListener("click", function () { action("morphs.reset", {}); });
  elements["apply-preset"].addEventListener("click", function () {
    const preset = selection(elements.preset);
    if (preset) action("view.set", { preset: preset });
  });
  window.addEventListener("pagehide", function () {
    stopped = true;
    window.clearTimeout(debounce);
    unsubscribe();
  });

  async function start() {
    try {
      if (!sdk) throw new Error(labels.unavailable);
      const info = await sdk.connect();
      if (stopped) return;
      const language = info.language === "ru" ? "ru" : "en";
      labels = translations[language];
      document.documentElement.lang = language;
      document.title = labels.title;
      for (const id of Object.keys(elements)) {
        if (Object.prototype.hasOwnProperty.call(labels, id)) elements[id].textContent = labels[id];
      }
      elements.controls.disabled = false;
      // Reads do not mutate the host and therefore do not generate another scene.changed.
      unsubscribe = sdk.on("scene.changed", scheduleRefresh);
      await refresh();
    } catch (error) { showError(error); elements.status.textContent = ""; }
  }
  start();
})();
