/* MyWorld 前端：状态展示 + WebSocket 通道。
 * 页面不放日志面板 —— 运行日志统一由控制台输出；
 * 这里只在浏览器 DevTools 里留 console.debug，便于排查。
 * 无构建步骤，浏览器直接加载。 */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = {
    version: $("version"),
    port: $("port"),
    latency: $("latency"),
    pill: $("connPill"),
    pillText: $("pillText"),
    meta: $("meta"),
    uptime: $("uptime"),
    btnPing: $("btnPing"),
    btnTick: $("btnTick"),
    btnTheme: $("btnTheme"),
    layout: $("layout"),
    sidebar: $("sidebar"),
    panel: document.querySelector(".panel"),
    btnSidebar: $("btnSidebar"),
    btnCreateWorld: $("btnCreateWorld"),
    worldList: $("worldList"),
    worldEmpty: $("worldEmpty"),
    btnCreatePreset: $("btnCreatePreset"),
    presetList: $("presetList"),
    presetEmpty: $("presetEmpty"),
    createDialog: $("createDialog"),
    createForm: $("createForm"),
    createTitle: $("createTitle"),
    createName: $("createName"),
    createError: $("createError"),
    createHint: $("createHint"),
    presetField: $("presetField"),
    presetAttrList: $("presetAttrList"),
    btnPresetAddAttr: $("btnPresetAddAttr"),
    btnDialogSubmit: $("btnDialogSubmit"),
    btnDialogCancel: $("btnDialogCancel"),
    coverField: $("coverField"),
    coverPreview: $("coverPreview"),
    coverImg: $("coverImg"),
    coverHint: $("coverHint"),
    coverHintText: $("coverHintText"),
    coverMeta: $("coverMeta"),
    worldImage: $("worldImage"),
    detailImage: $("detailImage"),
    detailPhotoBtn: $("detailPhotoBtn"),
    cropDialog: $("cropDialog"),
    cropTitle: $("cropTitle"),
    cropFrame: $("cropFrame"),
    cropImage: $("cropImage"),
    cropZoom: $("cropZoom"),
    cropMeta: $("cropMeta"),
    btnCropCancel: $("btnCropCancel"),
    btnCropApply: $("btnCropApply"),
    loadTarget: $("loadTarget"),
    btnLoadWorld: $("btnLoadWorld"),
    loadError: $("loadError"),
    canvasHint: $("canvasHint"),
    characterView: $("characterView"),
    characterWorldName: $("characterWorldName"),
    characterWorldPath: $("characterWorldPath"),
    characterList: $("characterList"),
    characterEmpty: $("characterEmpty"),
    characterPanel: $("characterPanel"),
    canvasBody: $("canvasBody"),
    detailPhoto: $("detailPhoto"),
    attrList: $("attrList"),
    btnAddAttr: $("btnAddAttr"),
    btnCloseDetail: $("btnCloseDetail"),
    btnDetailCancel: $("btnDetailCancel"),
    btnDetailSave: $("btnDetailSave"),
    btnUsePreset: $("btnUsePreset"),
    presetPickerDialog: $("presetPickerDialog"),
    presetPickerList: $("presetPickerList"),
    presetPickerEmpty: $("presetPickerEmpty"),
    btnPresetPickerCancel: $("btnPresetPickerCancel"),
    presetImportDialog: $("presetImportDialog"),
    presetImportText: $("presetImportText"),
    btnImportCancel: $("btnImportCancel"),
    btnImportConfirm: $("btnImportConfirm"),
    detailError: $("detailError"),
    btnCloseWorld: $("btnCloseWorld"),
    worldMenu: $("worldMenu"),
    menuRestoreDefault: $("menuRestoreDefault"),
    menuMoveFront: $("menuMoveFront"),
    menuDelete: $("menuDelete"),
    confirmDialog: $("confirmDialog"),
    confirmText: $("confirmText"),
    btnConfirmOk: $("btnConfirmOk"),
    btnConfirmCancel: $("btnConfirmCancel"),
    toast: $("toast"),
  };

  const state = {
    ws: null,
    connected: false,
    worlds: [],
    characters: [],
    reconnectDelay: 1000,
    reconnectMax: 15000,
    heartbeat: null,
    pingAt: 0,
    failures: 0,
    serverUptime: 0,
    syncedAt: 0,
    config: null,
    status: null,
  };

  // DevTools 里的调试输出，不影响页面
  const debug = (...args) => console.debug("[myworld]", ...args);

  // 页面结构与脚本版本万一不匹配（比如缓存错位），宁可少绑一个事件也别整个脚本崩掉
  const on = (node, event, handler) => {
    if (node) node.addEventListener(event, handler);
  };

  let toastTimer = null;

  /* 底部轻提示：失败原因不再只躺在 console 里 */
  function toast(message, kind = "info") {
    if (!el.toast) return;
    el.toast.textContent = message;
    el.toast.hidden = false;
    el.toast.classList.toggle("is-error", kind === "error");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.toast.hidden = true;
    }, 3200);
  }

  // ---------------- 明暗主题 ----------------

  const THEME_KEY = "myworld.theme";

  function currentTheme() {
    return document.documentElement.dataset.theme === "light" ? "light" : "dark";
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    // 图标由 CSS 按 data-theme 切换（暗色显示太阳、浅色显示月亮），这里只更新提示
    const tip = theme === "light" ? "切换到深色" : "切换到浅色";
    el.btnTheme.title = tip;
    el.btnTheme.setAttribute("aria-label", tip);
    // 默认缩略图分深浅两版，切主题时重新取
    refreshThumbnailThemes();
  }

  function initTheme() {
    // index.html 里的内联脚本已经定好初始主题（localStorage → 系统偏好），
    // 这里只负责同步按钮外观与手动切换。
    applyTheme(currentTheme());

    on(el.btnTheme, "click", () => {
      const next = currentTheme() === "light" ? "dark" : "light";
      applyTheme(next);
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch {
        /* 隐私模式下写不进去，忽略 */
      }
    });

    // 用户没手动选过时，跟随系统主题变化
    const media = window.matchMedia("(prefers-color-scheme: light)");
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", (event) => {
        let stored = null;
        try {
          stored = localStorage.getItem(THEME_KEY);
        } catch {
          stored = null;
        }
        if (!stored) applyTheme(event.matches ? "light" : "dark");
      });
    }
  }

  // ---------------- 左侧功能区 ----------------

  function activatePane(name) {
    document.querySelectorAll(".rail-item").forEach((item) => {
      const active = item.dataset.pane === name;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll(".pane").forEach((pane) => {
      pane.hidden = pane.dataset.pane !== name;
    });
    // 底部「选中项 + 加载」只在世界面板出现
    if (el.panel) el.panel.dataset.activePane = name;
    // 列表可能被别处改过（比如删了目录），切过去时 reload 一次
    if (name === "world") loadWorlds();
    if (name === "presets") loadPresets();
  }

  function initRail() {
    document.querySelectorAll(".rail-item").forEach((item) => {
      if (item.disabled) return;
      on(item, "click", () => activatePane(item.dataset.pane));
    });
  }

  // ---------------- 世界 ----------------

  let selectedWorld = null;
  let selectedItem = null;
  let loadedWorld = null;
  let menuTarget = null;
  let pendingDelete = null;

  async function loadWorlds() {
    try {
      const data = await fetchJSON("/api/worlds");
      renderWorlds(Array.isArray(data.items) ? data.items : []);
    } catch (err) {
      debug("读取世界列表失败", err.message);
    }
  }

  function renderWorlds(items) {
    state.worlds = items;
    el.worldList.replaceChildren();
    el.worldEmpty.hidden = items.length > 0;

    // 选中的世界可能已经不在了
    if (selectedWorld && !items.some((item) => item.name === selectedWorld)) {
      clearSelection();
    }

    for (const item of items) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "world-card";
      card.dataset.name = item.name;
      card.title = `${item.name} · ${formatStartTime(item.created_at)}`;
      if (item.name === selectedWorld) card.classList.add("is-selected");

      const thumb = document.createElement("div");
      thumb.className = "world-thumb";
      const img = document.createElement("img");
      // 没有真实缩略图时，后端按 ?theme= 返回对应的默认图（深/浅两版）
      const thumbBase = `/api/worlds/${encodeURIComponent(item.name)}/thumbnail`;
      img.dataset.thumbBase = thumbBase;
      img.src = `${thumbBase}?theme=${currentTheme()}`;
      img.alt = item.name;
      // 不用 loading="lazy"：动态插入的元素在部分浏览器里不会触发懒加载，
      // 表现就是缩略图一直空着。本地小图直接加载更快也更可靠。
      img.decoding = "async";
      thumb.append(img);

      const name = document.createElement("span");
      name.className = "world-name";
      name.textContent = item.name;

      // 选中标记：浅色圆圈 + 对号，盖在暗色蒙版之上（蒙版由 CSS 负责）
      const check = document.createElement("span");
      check.className = "world-check";
      check.setAttribute("aria-hidden", "true");
      check.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5.6 12.6l4 4 8.8-9" fill="none" stroke="currentColor"
              stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>`;
      thumb.append(check);

      card.append(thumb, name);
      card.addEventListener("click", () => selectWorld(item, card));
      el.worldList.append(card);
    }
  }

  function selectWorld(item, node) {
    selectedItem = item;
    selectedWorld = item.name;
    el.worldList.querySelectorAll(".world-card").forEach((el2) => {
      el2.classList.toggle("is-selected", el2 === node);
    });
    if (el.loadTarget) {
      el.loadTarget.textContent = item.name;
      el.loadTarget.classList.remove("is-empty");
    }
    if (el.btnLoadWorld) el.btnLoadWorld.disabled = false;
    clearLoadError();
    debug("选择世界", item);
  }

  /* 选中项没了（比如目录被删）就回到未选中状态 */
  function clearSelection() {
    selectedItem = null;
    selectedWorld = null;
    el.worldList.querySelectorAll(".world-card").forEach((card) => {
      card.classList.remove("is-selected");
    });
    if (el.loadTarget) {
      el.loadTarget.textContent = "未选择世界";
      el.loadTarget.classList.add("is-empty");
    }
    if (el.btnLoadWorld) el.btnLoadWorld.disabled = true;
  }

  /* 主题切换后，让默认缩略图跟着换版本 */
  function refreshThumbnailThemes() {
    const theme = currentTheme();
    document.querySelectorAll(".world-card img, .character-card img").forEach((img) => {
      const base = img.dataset.thumbBase;
      if (base) img.src = `${base}?theme=${theme}`;
    });
    // 右侧面板开着时，立绘也跟着换
    if (el.detailPhoto && loadedWorld && currentDetailName) {
      el.detailPhoto.src = portraitUrl(loadedWorld.name, currentDetailName);
    }
  }

  // ---------------- 底部加载栏 ----------------

  function showLoadError(message) {
    if (!el.loadError) return;
    el.loadError.textContent = message;
    el.loadError.hidden = false;
  }

  function clearLoadError() {
    if (!el.loadError) return;
    el.loadError.textContent = "";
    el.loadError.hidden = true;
  }

  async function loadSelectedWorld() {
    if (!selectedItem) {
      showLoadError("先选中一个世界");
      return;
    }
    clearLoadError();
    loadedWorld = selectedItem;

    if (el.canvasHint) el.canvasHint.hidden = true;
    if (el.characterView) el.characterView.hidden = false;
    if (el.characterWorldName) el.characterWorldName.textContent = selectedItem.name;
    if (el.characterWorldPath) el.characterWorldPath.textContent = selectedItem.path;

    await loadCharacters();
    debug("加载世界", selectedItem);
  }

  function closeLoadedWorld() {
    loadedWorld = null;
    closeCharacterPanel();
    if (el.characterView) el.characterView.hidden = true;
    if (el.canvasHint) el.canvasHint.hidden = false;
    if (el.characterList) el.characterList.replaceChildren();
    if (el.characterEmpty) el.characterEmpty.hidden = true;
  }

  // ---------------- 角色属性面板（右侧滑入） ----------------

  let currentDetailName = null;

  function portraitUrl(worldName, charName) {
    return `/api/worlds/${encodeURIComponent(worldName)}/characters/${encodeURIComponent(charName)}/portrait?theme=${currentTheme()}`;
  }

  function showDetailError(message) {
    if (!el.detailError) return;
    el.detailError.textContent = message;
    el.detailError.hidden = false;
  }

  function makeAttrRow({ label = "", value = "", fixedLabel = false, removable = true } = {}) {
    const row = document.createElement("div");
    row.className = "attr-row";

    if (fixedLabel) {
      const labelEl = document.createElement("span");
      labelEl.className = "attr-label-fixed";
      labelEl.textContent = label;
      row.append(labelEl);
    } else {
      const labelInput = document.createElement("input");
      labelInput.className = "input attr-label-input";
      labelInput.placeholder = "属性名";
      labelInput.value = label;
      labelInput.maxLength = 40;
      labelInput.setAttribute("aria-label", "属性名");
      row.append(labelInput);
    }

    const valueInput = document.createElement("input");
    valueInput.className = "input attr-value";
    valueInput.placeholder = fixedLabel ? "角色名（不能重复）" : "值";
    valueInput.value = value;
    valueInput.maxLength = fixedLabel ? 64 : 200;
    valueInput.setAttribute("aria-label", fixedLabel ? "角色名" : "属性值");
    row.append(valueInput);

    if (removable) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "attr-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "删除这条属性");
      remove.addEventListener("click", () => row.remove());
      row.append(remove);
    } else {
      const spacer = document.createElement("span");
      spacer.className = "attr-spacer";
      spacer.setAttribute("aria-hidden", "true");
      row.append(spacer);
    }

    return row;
  }

  /* 第一行固定是「姓名」（值唯一），其余是普通属性（值可重复） */
  function renderAttributeRows(detail) {
    if (!el.attrList) return;
    el.attrList.replaceChildren();
    el.attrList.append(makeAttrRow({ label: "姓名", value: detail.name ?? "", fixedLabel: true, removable: false }));
    for (const attr of detail.attributes ?? []) {
      el.attrList.append(makeAttrRow({ label: attr.label ?? "", value: attr.value ?? "" }));
    }
  }

  /* 预设只有属性名（键），单独一种行：一个输入框 + 删除 */
  function makeKeyRow(key = "") {
    const row = document.createElement("div");
    row.className = "attr-row key-row";

    const input = document.createElement("input");
    input.className = "input attr-key-input";
    input.placeholder = "属性名，例如 年龄";
    input.value = key;
    input.maxLength = 40;
    input.setAttribute("aria-label", "属性名");

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "attr-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", "删除这个属性名");
    remove.addEventListener("click", () => row.remove());

    row.append(input, remove);
    return row;
  }

  function collectRows() {
    const rows = [...(el.attrList?.querySelectorAll(".attr-row") ?? [])];
    const name = rows[0]?.querySelector(".attr-value")?.value.trim() ?? "";
    const attributes = rows
      .slice(1)
      .map((row) => ({
        label: row.querySelector(".attr-label-input")?.value.trim() ?? "",
        value: row.querySelector(".attr-value")?.value.trim() ?? "",
      }))
      .filter((attr) => attr.label || attr.value);
    return { name, attributes };
  }

  /* 创建/修改预设时收集属性名 */
  function collectPresetKeys() {
    return [...(el.presetAttrList?.querySelectorAll(".attr-key-input") ?? [])]
      .map((input) => input.value.trim())
      .filter(Boolean);
  }

  /* 卡片重排时用 FLIP 动画：先量旧位置，改布局后再把差异补成 transform */
  function animateCharacterReflow(mutate) {
    const cards = [...(el.characterList?.querySelectorAll(".character-card") ?? [])];
    const before = cards.map((card) => card.getBoundingClientRect());

    mutate();

    requestAnimationFrame(() => {
      cards.forEach((card, index) => {
        const first = before[index];
        const last = card.getBoundingClientRect();
        const dx = first.left - last.left;
        const dy = first.top - last.top;
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;

        card.style.transition = "none";
        card.style.transform = `translate(${dx}px, ${dy}px)`;
        requestAnimationFrame(() => {
          card.style.transition = "transform 0.26s cubic-bezier(0.4, 0, 0.2, 1)";
          card.style.transform = "";
        });
      });
    });
  }

  /* 面板宽度 = 正好两列卡片 + 列间距 */
  function measureDetailWidth() {
    const list = el.characterList;
    const card = list?.querySelector(".character-card");
    if (!list || !card) return 378;

    const gap = parseFloat(getComputedStyle(list).columnGap || "0") || 18;
    const width = card.getBoundingClientRect().width;
    return Math.max(240, Math.round(width * 2 + gap));
  }

  async function openCharacterPanel(item) {
    if (!loadedWorld || !el.characterPanel) return;

    currentDetailName = item.name;
    if (el.detailError) el.detailError.hidden = true;
    clearPendingPortrait();
    if (el.detailPhoto) {
      el.detailPhoto.src = portraitUrl(loadedWorld.name, item.name);
      el.detailPhoto.alt = item.name;
    }
    renderAttributeRows({ name: item.name, attributes: [] });

    const width = measureDetailWidth();
    document.documentElement.style.setProperty("--detail-w", `${width}px`);

    animateCharacterReflow(() => {
      el.canvasBody?.classList.add("has-detail");
      el.characterPanel.classList.add("is-open");
      el.characterPanel.setAttribute("aria-hidden", "false");
    });

    try {
      const detail = await fetchJSON(
        `/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters/${encodeURIComponent(item.name)}`,
      );
      renderAttributeRows(detail);
    } catch (err) {
      debug("读取角色详情失败", err.message);
    }
  }

  function closeCharacterPanel() {
    if (!el.characterPanel) return;
    clearPendingPortrait(); // 没保存的立绘直接丢掉
    animateCharacterReflow(() => {
      el.canvasBody?.classList.remove("has-detail");
      el.characterPanel.classList.remove("is-open");
      el.characterPanel.setAttribute("aria-hidden", "true");
    });
    currentDetailName = null;
  }

  /* 面板「导入预设」：按预设的属性名清单调整角色——缺的补上、多余的连值一起删掉 */
  let pendingImport = null;

  function planPresetImport(item) {
    if (!el.attrList) return;

    const keys = item.keys ?? [];
    if (!keys.length) {
      toast(`预设「${item.name}」还没有属性名`);
      return;
    }

    const rows = [...el.attrList.querySelectorAll(".attr-row")].slice(1); // 跳过姓名
    const entries = rows
      .map((row) => ({ row, label: (row.querySelector(".attr-label-input")?.value ?? "").trim() }))
      .filter((entry) => entry.label);

    const keySet = new Set(keys);
    const toAdd = keys.filter((key) => !entries.some((entry) => entry.label === key));
    const toRemove = entries.filter((entry) => !keySet.has(entry.label));

    if (!toAdd.length && !toRemove.length) {
      toast(`「${item.name}」和当前属性已经一致`);
      return;
    }

    pendingImport = { item, toAdd, toRemove };
    const parts = [];
    if (toAdd.length) {
      parts.push(`补充 ${toAdd.length} 个：${toAdd.join("、")}`);
    }
    if (toRemove.length) {
      parts.push(`删除 ${toRemove.length} 个（连值一起删）：${toRemove.map((entry) => entry.label).join("、")}`);
    }
    if (el.presetImportText) {
      el.presetImportText.textContent =
        `导入「${item.name}」会把属性调整成预设的清单——${parts.join("；")}。` +
        "删除的值无法恢复（还可以点「取消」不保存），确定要导入吗？";
    }
    el.presetImportDialog?.showModal();
  }

  function confirmPresetImport() {
    if (!pendingImport) return;
    const { item, toAdd, toRemove } = pendingImport;

    for (const entry of toRemove) entry.row.remove();
    for (const key of toAdd) el.attrList.append(makeAttrRow({ label: key, value: "" }));

    if (el.detailError) el.detailError.hidden = true;
    pendingImport = null;
    toast(`已导入「${item.name}」：补充 ${toAdd.length} 个、删除 ${toRemove.length} 个`);
  }

  async function openPresetPicker() {
    if (!el.presetPickerDialog || !el.presetPickerList) return;

    el.presetPickerList.replaceChildren();
    if (el.presetPickerEmpty) el.presetPickerEmpty.hidden = true;

    let items = [];
    try {
      const data = await fetchJSON("/api/presets");
      items = data.items ?? [];
    } catch (err) {
      toast("读取预设失败：" + err.message, "error");
      return;
    }

    if (!items.length && el.presetPickerEmpty) el.presetPickerEmpty.hidden = false;

    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "preset-pick";
      button.dataset.name = item.name;

      const name = document.createElement("span");
      name.className = "preset-pick-name";
      name.textContent = item.name;

      const keys = item.keys ?? [];
      const meta = document.createElement("span");
      meta.className = "preset-pick-meta";
      meta.textContent = keys.length ? `${keys.length} 个属性名` : "空预设";
      meta.title = keys.join("、");

      button.append(name, meta);
      button.addEventListener("click", () => {
        el.presetPickerDialog.close();
        requestAnimationFrame(() => planPresetImport(item));
      });
      el.presetPickerList.append(button);
    }

    el.presetPickerDialog.showModal();
  }

  async function saveCharacterDetail() {
    if (!currentDetailName || !loadedWorld) return;

    const { name, attributes } = collectRows();
    if (!name) {
      showDetailError("姓名不能为空");
      el.attrList?.querySelector(".attr-value")?.focus();
      return;
    }

    // 姓名这条属性值必须唯一，其他属性可以随便重复
    const clash = state.characters.some((char) => char.name === name && char.name !== currentDetailName);
    if (clash) {
      showDetailError(`已经有角色叫「${name}」了，姓名不能重复`);
      return;
    }

    if (el.detailError) el.detailError.hidden = true;

    el.btnDetailSave.disabled = true;
    try {
      const updated = await fetchJSON(
        `/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters/${encodeURIComponent(currentDetailName)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, attributes }),
        },
      );

      currentDetailName = updated.name;

      // 立绘有改动才上传（取消或没换图都不会动它）
      if (pendingPortrait) {
        try {
          await postPortrait(pendingPortrait, loadedWorld.name, updated.name);
        } catch (err) {
          toast("立绘上传失败：" + err.message, "error");
        }
        clearPendingPortrait();
      }

      if (el.detailPhoto) {
        el.detailPhoto.src = `${portraitUrl(loadedWorld.name, updated.name)}&v=${Date.now()}`;
      }
      await loadCharacters();
      bumpCardPortrait(loadedWorld.name, updated.name);
      renderAttributeRows(updated);
      toast("角色属性已保存");
    } catch (err) {
      showDetailError(err.message);
    } finally {
      el.btnDetailSave.disabled = false;
    }
  }

  // ---------------- 角色 ----------------

  async function loadCharacters() {
    if (!el.characterList) return;
    if (!loadedWorld) {
      el.characterList.replaceChildren();
      return;
    }
    try {
      const data = await fetchJSON(`/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters`);
      renderCharacters(Array.isArray(data.items) ? data.items : []);
    } catch (err) {
      debug("读取角色失败", err.message);
    }
  }

  function renderCharacters(items) {
    state.characters = items;
    el.characterList.replaceChildren();

    for (const item of items) {
      const card = document.createElement("figure");
      card.className = "character-card";
      card.dataset.name = item.name;
      card.title = `${item.name} · ${formatStartTime(item.created_at)}`;
      card.draggable = true;

      const thumb = document.createElement("div");
      thumb.className = "character-thumb";
      const img = document.createElement("img");
      const base = `/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters/${encodeURIComponent(item.name)}/portrait`;
      img.dataset.thumbBase = base;
      img.src = `${base}?theme=${currentTheme()}`;
      img.alt = item.name;
      img.decoding = "async";
      thumb.append(img);

      const name = document.createElement("figcaption");
      name.className = "character-name";
      name.textContent = item.name;

      card.append(thumb, name);
      card.addEventListener("click", () => openCharacterPanel(item));
      el.characterList.append(card);
    }

    // 「新建角色」永远排在最后一个角色后面
    el.characterList.append(makeCharacterCreateTile());
    if (el.characterEmpty) el.characterEmpty.hidden = items.length > 0;
  }

  function makeCharacterCreateTile() {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "character-create";
    tile.innerHTML = `<span class="character-create-plus">＋</span><span>新建角色</span>`;
    tile.addEventListener("click", () => openCreateDialog("character"));
    return tile;
  }

  /* 拖动角色卡片调整顺序（HTML5 拖放，落下后写回 order.json） */
  function initCharacterDrag() {
    const list = el.characterList;
    if (!list) return;

    let dragging = null;

    list.addEventListener("dragstart", (event) => {
      const card = event.target.closest?.(".character-card");
      if (!card) return;
      dragging = card;
      card.classList.add("is-dragging");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.name);
      }
    });

    list.addEventListener("dragover", (event) => {
      if (!dragging) return;
      const target = event.target.closest?.(".character-card");
      if (!target || target === dragging) return;

      event.preventDefault();
      const rect = target.getBoundingClientRect();
      const after = event.clientX > rect.left + rect.width / 2;
      list.insertBefore(dragging, after ? target.nextSibling : target);
    });

    list.addEventListener("drop", (event) => event.preventDefault());

    list.addEventListener("dragend", async () => {
      if (!dragging) return;
      dragging.classList.remove("is-dragging");

      const names = [...list.querySelectorAll(".character-card")].map((card) => card.dataset.name);
      const before = state.characters.map((item) => item.name);
      dragging = null;

      if (!loadedWorld || names.join("\u0000") === before.join("\u0000")) return;

      try {
        await fetchJSON(`/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters/order`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ names }),
        });
        await loadCharacters();
        toast("角色顺序已保存");
        debug("角色顺序已保存", names);
      } catch (err) {
        // 多半是后端还是旧进程（重启 MyWorld.exe 即可）；把原因直接告诉用户
        toast("顺序保存失败：" + err.message + "（后端可能是旧进程，重启 MyWorld.exe 试试）", "error");
        debug("保存角色顺序失败", err.message);
        await loadCharacters();
      }
    });
  }

  // ---------------- 世界卡片右键菜单 ----------------

  function openWorldMenu(x, y) {
    if (!el.worldMenu) return;

    // 「恢复默认」「移至最前」只有角色才有
    const isCharacter = menuTarget?.type === "character";
    if (el.menuRestoreDefault) el.menuRestoreDefault.hidden = !isCharacter;
    if (el.menuMoveFront) el.menuMoveFront.hidden = !isCharacter;

    el.worldMenu.hidden = false;
    const rect = el.worldMenu.getBoundingClientRect();
    const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
    el.worldMenu.style.left = `${left}px`;
    el.worldMenu.style.top = `${top}px`;
    (isCharacter ? el.menuRestoreDefault : el.menuDelete)?.focus();
  }

  function closeWorldMenu() {
    if (el.worldMenu) el.worldMenu.hidden = true;
  }

  /* 右键「移至最前」：把该角色排到第一个并落盘 */
  async function moveCharacterToFront(item) {
    if (!loadedWorld) return;

    const current = state.characters.map((entry) => entry.name);
    if (current[0] === item.name) {
      toast(`「${item.name}」已经在最前面了`);
      return;
    }

    const names = [item.name, ...current.filter((name) => name !== item.name)];
    try {
      await fetchJSON(`/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters/order`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ names }),
      });
      await loadCharacters();
      toast(`「${item.name}」已移至最前`);
    } catch (err) {
      toast("移动失败：" + err.message, "error");
    }
  }

  /* 右键「恢复默认」：删掉自定义立绘，回到默认占位图 */
  async function restoreDefaultPortrait(item) {
    if (!loadedWorld) return;

    try {
      const result = await fetchJSON(
        `/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters/${encodeURIComponent(item.name)}/portrait`,
        { method: "DELETE" },
      );

      clearPendingPortrait();
      bumpCardPortrait(loadedWorld.name, item.name);
      if (currentDetailName === item.name && el.detailPhoto) {
        el.detailPhoto.src = `${portraitUrl(loadedWorld.name, item.name)}&v=${Date.now()}`;
      }
      toast(result.removed?.length ? "立绘已恢复默认" : "本来就是默认立绘");
    } catch (err) {
      toast("恢复默认失败：" + err.message, "error");
    }
  }

  function initWorldMenu() {
    if (!el.worldMenu) return;

    if (el.worldList) {
      el.worldList.addEventListener("contextmenu", (event) => {
        const card = event.target.closest(".world-card");
        if (!card) return;
        event.preventDefault();
        const item = state.worlds.find((entry) => entry.name === card.dataset.name);
        if (!item) return;
        menuTarget = { type: "world", item };
        openWorldMenu(event.clientX, event.clientY);
      });
    }

    // 角色卡片用同一套菜单，额外多一个「移至最前」
    if (el.characterList) {
      el.characterList.addEventListener("contextmenu", (event) => {
        const card = event.target.closest(".character-card");
        if (!card) return;
        event.preventDefault();
        const item = state.characters.find((entry) => entry.name === card.dataset.name);
        if (!item) return;
        menuTarget = { type: "character", item };
        openWorldMenu(event.clientX, event.clientY);
      });
    }

    // 预设卡片：只有删除
    if (el.presetList) {
      el.presetList.addEventListener("contextmenu", (event) => {
        const row = event.target.closest(".preset-item");
        if (!row) return;
        event.preventDefault();
        menuTarget = { type: "preset", item: { name: row.dataset.name } };
        openWorldMenu(event.clientX, event.clientY);
      });
    }

    // 点别处、按 Esc、滚动、改窗口大小都收起菜单
    document.addEventListener("pointerdown", (event) => {
      if (!el.worldMenu.hidden && !el.worldMenu.contains(event.target)) closeWorldMenu();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeWorldMenu();
    });
    el.worldList?.addEventListener("scroll", closeWorldMenu, true);
    el.characterList?.addEventListener("scroll", closeWorldMenu, true);
    el.presetList?.addEventListener("scroll", closeWorldMenu, true);
    window.addEventListener("resize", closeWorldMenu);

    on(el.menuRestoreDefault, "click", () => {
      closeWorldMenu();
      if (menuTarget?.type === "character") restoreDefaultPortrait(menuTarget.item);
    });

    on(el.menuMoveFront, "click", () => {
      closeWorldMenu();
      if (menuTarget?.type === "character") moveCharacterToFront(menuTarget.item);
    });

    on(el.menuDelete, "click", () => {
      closeWorldMenu();
      if (menuTarget) requestDelete(menuTarget);
    });
  }

  function requestDelete(entry) {
    pendingDelete = entry;
    if (!el.confirmDialog || !el.confirmText) return;

    const texts = {
      world: `世界「${entry.item.name}」以及它目录里的所有文件都会被删除，无法恢复。`,
      character: `角色「${entry.item.name}」以及它的立绘等文件都会被删除，无法恢复。`,
      preset: `预设「${entry.item.name}」以及它保存的属性都会被删除，无法恢复。`,
    };
    el.confirmText.textContent = texts[entry.type] ?? `「${entry.item.name}」会被删除，无法恢复。`;
    el.confirmDialog.showModal();
    requestAnimationFrame(() => el.btnConfirmOk?.focus());
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const { type, item } = pendingDelete;

    if (type === "character" && !loadedWorld) {
      if (el.confirmText) el.confirmText.textContent = "世界没有加载，无法删除角色";
      return;
    }

    let url;
    if (type === "world") {
      url = `/api/worlds/${encodeURIComponent(item.name)}`;
    } else if (type === "preset") {
      url = `/api/presets/${encodeURIComponent(item.name)}`;
    } else {
      url = `/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters/${encodeURIComponent(item.name)}`;
    }

    el.btnConfirmOk.disabled = true;
    try {
      const response = await fetch(url, { method: "DELETE" });
      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body && body.detail) detail = body.detail;
        } catch {
          /* 非 JSON 响应就保持默认信息 */
        }
        throw new Error(detail);
      }

      pendingDelete = null;
      el.confirmDialog.close();

      if (type === "world") {
        if (selectedWorld === item.name) clearSelection();
        if (loadedWorld?.name === item.name) closeLoadedWorld();
        await loadWorlds();
        debug("删除世界", item);
      } else if (type === "preset") {
        await loadPresets();
        toast(`预设「${item.name}」已删除`);
        debug("删除预设", item);
      } else {
        if (currentDetailName === item.name) closeCharacterPanel();
        await loadCharacters();
        debug("删除角色", item);
      }
    } catch (err) {
      if (el.confirmText) el.confirmText.textContent = "删除失败：" + err.message;
    } finally {
      el.btnConfirmOk.disabled = false;
    }
  }

  // ---------------- 创建弹窗（世界 / 预设共用） ----------------

  let createMode = null; // "world" | "preset" | "character"
  let editPresetName = null; // 非空 = 正在修改这个预设

  function showCreateError(message) {
    if (!el.createError) return;
    el.createError.textContent = message;
    el.createError.hidden = false;
  }

  function clearCreateError() {
    if (!el.createError) return;
    el.createError.textContent = "";
    el.createError.hidden = true;
  }

  function openCreateDialog(mode, preset = null) {
    if (!el.createDialog || !el.createName) return;
    createMode = mode;
    editPresetName = preset?.name ?? null;
    const isWorld = mode === "world";
    const isEditing = Boolean(preset);

    const titles = { world: "创建新世界", preset: "创建新预设", character: "新建角色" };
    const placeholders = {
      world: "给世界取个名字",
      preset: "给预设取个名字",
      character: "给角色取个名字",
    };
    el.createTitle.textContent = isEditing ? "修改预设" : titles[mode] ?? "新建";
    el.createName.placeholder = placeholders[mode] ?? "取个名字";
    el.createName.value = preset?.name ?? "";
    if (el.btnDialogSubmit) el.btnDialogSubmit.textContent = isEditing ? "保存" : "创建";
    clearCreateError();

    // 世界要 16:9 封面，角色要 9:16 立绘；预设不需要图片
    const isPortrait = mode === "character";
    const wantsCover = isWorld || isPortrait;

    if (el.coverField) el.coverField.hidden = !wantsCover;
    if (wantsCover) resetCover();

    if (el.coverPreview) {
      el.coverPreview.classList.toggle("is-portrait", isPortrait);
      el.coverPreview.style.aspectRatio = isPortrait ? "9 / 16" : "16 / 9";
    }
    if (el.coverHintText) {
      el.coverHintText.textContent = isPortrait
        ? "点击选择本地图片，可裁剪成 9:16 立绘"
        : "点击选择本地图片，可裁剪成 16:9 封面";
    }

    // 预设：填的是给角色用的属性键值对
    const isPreset = mode === "preset";
    if (el.presetField) el.presetField.hidden = !isPreset;
    if (isPreset && el.presetAttrList) {
      el.presetAttrList.replaceChildren();
      const existing = preset?.keys ?? [];
      if (existing.length) {
        for (const key of existing) {
          el.presetAttrList.append(makeKeyRow(key));
        }
      } else {
        el.presetAttrList.append(makeKeyRow());
      }
    }

    if (el.createHint) {
      el.createHint.textContent = isPreset
        ? "预设只记属性名（键），套用到角色时只补缺失的属性行，不会改动已有值。"
        : isPortrait
          ? "立绘可以先不选，之后在右侧面板里点立绘也能换。"
          : "封面可以先不选，默认图照样能用；之后往世界目录里放一张 thumbnail.png 也能换。";
    }

    el.createDialog.classList.toggle("is-wide", isWorld);

    el.createDialog.showModal();
    requestAnimationFrame(() => el.createName?.focus());
  }

  function closeCreateDialog() {
    clearCreateError();
    editPresetName = null;
    if (el.btnDialogSubmit) el.btnDialogSubmit.textContent = "创建";
    if (el.createDialog?.open) el.createDialog.close();
  }

  async function submitCreate() {
    const mode = createMode;
    if (!mode || !el.createName) return;

    const name = el.createName.value.trim();
    if (!name) {
      showCreateError("名字不能为空");
      el.createName.focus();
      return;
    }

    el.btnDialogSubmit.disabled = true;
    try {
      const editingPreset = mode === "preset" && editPresetName;
      let url = "/api/worlds";
      if (mode === "preset") {
        url = editingPreset ? `/api/presets/${encodeURIComponent(editPresetName)}` : "/api/presets";
      } else if (mode === "character") {
        if (!loadedWorld) {
          showCreateError("先加载一个世界");
          return;
        }
        url = `/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters`;
      }

      const created = await fetchJSON(url, {
        method: editingPreset ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, ...(mode === "preset" ? { keys: collectPresetKeys() } : {}) }),
      });

      if (mode === "world" && cover.blob) {
        try {
          const response = await fetch(`/api/worlds/${encodeURIComponent(created.name)}/thumbnail`, {
            method: "POST",
            headers: { "Content-Type": cover.blob.type || "image/jpeg" },
            body: cover.blob,
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
        } catch (err) {
          // 世界已经建好了，封面没存上去：提示一下但不回滚
          showLoadError("封面保存失败：" + err.message);
        }
      }

      if (mode === "character" && cover.blob && loadedWorld) {
        try {
          const response = await fetch(
            `/api/worlds/${encodeURIComponent(loadedWorld.name)}/characters/${encodeURIComponent(created.name)}/portrait`,
            {
              method: "POST",
              headers: { "Content-Type": cover.blob.type || "image/jpeg" },
              body: cover.blob,
            },
          );
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
        } catch (err) {
          // 角色已经建好了，立绘没存上去：提示一下
          toast("立绘保存失败：" + err.message, "error");
          debug("角色立绘保存失败", err.message);
        }
      }

      closeCreateDialog();

      if (mode === "world") {
        selectedWorld = created.name;
        await loadWorlds();
        const node = el.worldList.querySelector(`.world-card[data-name="${CSS.escape(created.name)}"]`);
        if (node) selectWorld(created, node);
      } else if (mode === "character") {
        await loadCharacters();
        debug("新建角色", created);
      } else {
        await loadPresets();
        toast(editingPreset ? "预设已更新" : "预设已创建");
        debug(editingPreset ? "修改预设" : "创建预设", created);
      }
    } catch (err) {
      showCreateError(err.message);
    } finally {
      el.btnDialogSubmit.disabled = false;
    }
  }

  // ---------------- 封面：选图 + 裁剪 ----------------

  // "create" = 创建弹窗里裁剪后待提交；"portrait" = 给角色换立绘，裁完直接上传
  let cropPurpose = "create";

  const cover = {
    img: null,
    blob: null,
    frame: { w: 0, h: 0 },
    scale: 1,
    minScale: 1,
    offset: { x: 0, y: 0 },
    dragging: false,
    pointer: { x: 0, y: 0 },
  };

  function resetCover() {
    cover.img = null;
    cover.blob = null;
    if (el.coverImg) {
      el.coverImg.hidden = true;
      el.coverImg.removeAttribute("src");
    }
    if (el.coverHint) el.coverHint.hidden = false;
    if (el.coverMeta) {
      el.coverMeta.hidden = true;
      el.coverMeta.textContent = "";
    }
  }

  function clampCover() {
    const w = cover.img.naturalWidth * cover.scale;
    const h = cover.img.naturalHeight * cover.scale;
    cover.offset.x = Math.min(0, Math.max(cover.frame.w - w, cover.offset.x));
    cover.offset.y = Math.min(0, Math.max(cover.frame.h - h, cover.offset.y));
  }

  function applyCoverTransform() {
    if (!el.cropImage || !cover.img) return;
    const w = cover.img.naturalWidth * cover.scale;
    const h = cover.img.naturalHeight * cover.scale;
    el.cropImage.style.width = `${w}px`;
    el.cropImage.style.height = `${h}px`;
    el.cropImage.style.transform = `translate(${cover.offset.x}px, ${cover.offset.y}px)`;
    if (el.cropMeta) {
      el.cropMeta.textContent = `${cover.img.naturalWidth}×${cover.img.naturalHeight} · ${Math.round(
        (cover.scale / cover.minScale) * 100,
      )}%`;
    }
  }

  function setCoverZoom(percent, anchor) {
    if (!cover.img) return;

    const clamped = Math.min(300, Math.max(100, percent));
    // 以锚点（默认画面中心）为基准缩放，滚轮时用鼠标位置
    const px = anchor ? anchor.x : cover.frame.w / 2;
    const py = anchor ? anchor.y : cover.frame.h / 2;
    const srcX = (px - cover.offset.x) / cover.scale;
    const srcY = (py - cover.offset.y) / cover.scale;

    cover.scale = cover.minScale * (clamped / 100);
    cover.offset.x = px - srcX * cover.scale;
    cover.offset.y = py - srcY * cover.scale;

    clampCover();
    applyCoverTransform();
    if (el.cropZoom) el.cropZoom.value = String(Math.round(clamped));
  }

  /* 鼠标滚轮缩放：以指针所在位置为锚点，向上放大、向下缩小 */
  function initCropWheel() {
    const frame = el.cropFrame;
    if (!frame) return;

    frame.addEventListener(
      "wheel",
      (event) => {
        if (!cover.img || !el.cropDialog?.open) return;
        event.preventDefault();

        const rect = frame.getBoundingClientRect();
        const anchor = { x: event.clientX - rect.left, y: event.clientY - rect.top };
        const current = Number(el.cropZoom?.value ?? 100);
        const step = event.deltaY < 0 ? 10 : -10;
        setCoverZoom(current + step, anchor);
      },
      { passive: false },
    );
  }

  function openCropDialog(file, purpose = "create") {
    if (!el.cropDialog || !el.cropImage) return;
    cropPurpose = purpose;
    const url = URL.createObjectURL(file);
    const img = new Image();

    img.onload = () => {
      cover.img = img;
      el.cropImage.src = url;

      // 先把画框比例切好，再量尺寸（换立绘和建角色都是 9:16，世界封面是 16:9）
      const portrait = purpose === "portrait" || createMode === "character";
      if (el.cropTitle) el.cropTitle.textContent = portrait ? "裁剪立绘" : "裁剪封面";
      if (el.cropFrame) {
        el.cropFrame.classList.toggle("is-portrait", portrait);
        el.cropFrame.style.aspectRatio = portrait ? "9 / 16" : "16 / 9";
      }

      el.cropDialog.showModal();
      requestAnimationFrame(() => {
        if (!el.cropFrame) return;
        // 不能用 getBoundingClientRect：弹窗有入场缩放动画，量到的尺寸会偏小，
        // 导致图片比画框略窄、右边露出黑边。clientWidth/Height 不受 transform 影响。
        const frameW = el.cropFrame.clientWidth;
        const frameH = el.cropFrame.clientHeight;
        if (!frameW || !frameH) return;

        cover.frame = { w: frameW, h: frameH };
        // 加一点点余量，避免亚像素取整在边缘漏出 1px 背景
        cover.minScale = Math.max(frameW / img.naturalWidth, frameH / img.naturalHeight) + 0.001;
        cover.scale = cover.minScale;
        cover.offset.x = (frameW - img.naturalWidth * cover.scale) / 2;
        cover.offset.y = (frameH - img.naturalHeight * cover.scale) / 2;
        clampCover();
        el.cropZoom.value = "100";
        applyCoverTransform();
      });
    };
    img.onerror = () => showCreateError("这张图片读不出来，换一张试试");
    img.src = url;
  }

  function applyCrop() {
    if (!cover.img) return;

    const sourceW = cover.frame.w / cover.scale;
    const sourceH = cover.frame.h / cover.scale;
    const sourceX = -cover.offset.x / cover.scale;
    const sourceY = -cover.offset.y / cover.scale;

    const targetW = cover.frame.w >= cover.frame.h ? 960 : Math.round(1280 * (cover.frame.w / cover.frame.h));
    const targetH = cover.frame.w >= cover.frame.h ? Math.round(960 * (cover.frame.h / cover.frame.w)) : 1280;
    const canvas = document.createElement("canvas");
    canvas.width = targetW;
    canvas.height = targetH;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(cover.img, sourceX, sourceY, sourceW, sourceH, 0, 0, targetW, targetH);

    canvas.toBlob(
      (blob) => {
        if (!blob) {
          showCreateError("裁剪失败，换一张图片试试");
          return;
        }

        // 换立绘：先只做本地预览，点「保存」才真正上传（取消就丢弃）
        if (cropPurpose === "portrait") {
          el.cropDialog.close();
          setPendingPortrait(blob);
          return;
        }

        cover.blob = blob;
        if (el.coverImg) {
          el.coverImg.src = URL.createObjectURL(blob);
          el.coverImg.hidden = false;
        }
        if (el.coverHint) el.coverHint.hidden = true;
        if (el.coverMeta) {
          el.coverMeta.hidden = false;
          el.coverMeta.textContent = `已裁剪 ${targetW}×${targetH} · ${(blob.size / 1024).toFixed(0)} KB`;
        }
        el.cropDialog.close();
      },
      "image/jpeg",
      0.9,
    );
  }

  /* 面板里点立绘 → 选图 → 裁剪：先暂存，保存时才上传 */
  let pendingPortrait = null;
  let pendingPortraitPreview = null;

  function setPendingPortrait(blob) {
    clearPendingPortrait();
    pendingPortrait = blob;
    pendingPortraitPreview = URL.createObjectURL(blob);
    if (el.detailPhoto) el.detailPhoto.src = pendingPortraitPreview;
    if (el.detailError) el.detailError.hidden = true;
    toast("新立绘已选好，点「保存」生效");
  }

  function clearPendingPortrait() {
    if (pendingPortraitPreview) URL.revokeObjectURL(pendingPortraitPreview);
    pendingPortraitPreview = null;
    pendingPortrait = null;
  }

  async function postPortrait(blob, worldName, charName) {
    const response = await fetch(
      `/api/worlds/${encodeURIComponent(worldName)}/characters/${encodeURIComponent(charName)}/portrait`,
      {
        method: "POST",
        headers: { "Content-Type": blob.type || "image/jpeg" },
        body: blob,
      },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  }

  /* 列表卡片的立绘地址是带 theme 的，换图后要加版本号才会刷新 */
  function bumpCardPortrait(worldName, charName) {
    const card = [...(el.characterList?.querySelectorAll(".character-card") ?? [])].find(
      (item) => item.dataset.name === charName,
    );
    const image = card?.querySelector("img");
    if (!image) return;
    image.src = `/api/worlds/${encodeURIComponent(worldName)}/characters/${encodeURIComponent(charName)}/portrait?theme=${currentTheme()}&v=${Date.now()}`;
  }

  function initCropDrag() {
    const frame = el.cropFrame;
    if (!frame) return;

    frame.addEventListener("pointerdown", (event) => {
      if (!cover.img) return;
      cover.dragging = true;
      cover.pointer = { x: event.clientX, y: event.clientY };
      frame.classList.add("is-dragging");
      frame.setPointerCapture?.(event.pointerId);
    });

    frame.addEventListener("pointermove", (event) => {
      if (!cover.dragging) return;
      cover.offset.x += event.clientX - cover.pointer.x;
      cover.offset.y += event.clientY - cover.pointer.y;
      cover.pointer = { x: event.clientX, y: event.clientY };
      clampCover();
      applyCoverTransform();
    });

    const end = (event) => {
      if (!cover.dragging) return;
      cover.dragging = false;
      frame.classList.remove("is-dragging");
      if (frame.hasPointerCapture?.(event.pointerId)) frame.releasePointerCapture(event.pointerId);
    };
    frame.addEventListener("pointerup", end);
    frame.addEventListener("pointercancel", end);
  }

  // ---------------- 预设 ----------------

  async function loadPresets() {
    try {
      const data = await fetchJSON("/api/presets");
      renderPresets(Array.isArray(data.items) ? data.items : []);
    } catch (err) {
      debug("读取预设失败", err.message);
    }
  }

  function renderPresets(items) {
    el.presetList.replaceChildren();
    el.presetEmpty.hidden = items.length > 0;

    for (const item of items) {
      const row = document.createElement("div");
      row.className = "preset-item";
      row.dataset.name = item.name;

      const name = document.createElement("span");
      name.className = "preset-name";
      name.textContent = item.name;

      const keys = item.keys ?? [];
      const meta = document.createElement("span");
      meta.className = "preset-meta";
      meta.textContent = keys.length ? `${keys.length} 个属性名` : "空预设";
      meta.title = keys.join("、");

      const time = document.createElement("span");
      time.className = "preset-time";
      time.textContent = formatStartTime(item.created_at).replace(/:\d{2}$/, "");
      time.title = item.created_at ?? "";

      row.append(name, meta, time);
      row.addEventListener("click", () => openCreateDialog("preset", item));
      el.presetList.append(row);
    }
  }

  // ---------------- 左侧栏展开/收起 ----------------

  const SIDEBAR_KEY = "myworld.sidebar";

  function applySidebar(collapsed) {
    if (!el.layout || !el.sidebar || !el.btnSidebar) return;
    el.layout.classList.toggle("is-collapsed", collapsed);
    el.btnSidebar.setAttribute("aria-expanded", String(!collapsed));
    el.btnSidebar.title = collapsed ? "展开左侧栏 (Ctrl+B)" : "收起左侧栏 (Ctrl+B)";
    el.sidebar.setAttribute("aria-hidden", String(collapsed));
    // 收起后把面板移出 Tab 顺序
    if ("inert" in HTMLElement.prototype) el.sidebar.inert = collapsed;
  }

  function initSidebar() {
    if (!el.layout || !el.sidebar || !el.btnSidebar) return;

    let stored = null;
    try {
      stored = localStorage.getItem(SIDEBAR_KEY);
    } catch {
      stored = null;
    }
    applySidebar(stored === "collapsed");

    on(el.btnSidebar, "click", () => {
      const collapsed = !el.layout.classList.contains("is-collapsed");
      applySidebar(collapsed);
      try {
        localStorage.setItem(SIDEBAR_KEY, collapsed ? "collapsed" : "open");
      } catch {
        /* 隐私模式写不进去，忽略 */
      }
    });

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "b") {
        event.preventDefault();
        el.btnSidebar.click();
      }
    });
  }

  // ---------------- 画布分栏（二级顶栏） ----------------

  function initWorkTabs() {
    const tabs = Array.from(document.querySelectorAll(".worktab"));
    if (!tabs.length) return;

    tabs.forEach((tab) => {
      on(tab, "click", () => {
        tabs.forEach((other) => {
          const active = other === tab;
          other.classList.toggle("is-active", active);
          other.setAttribute("aria-selected", String(active));
        });

        // 「角色」栏：有加载的世界就显示角色图库，否则仍显示占位提示
        if (tab.dataset.tab === "characters") {
          if (loadedWorld) {
            if (el.canvasHint) el.canvasHint.hidden = true;
            if (el.characterView) el.characterView.hidden = false;
            loadCharacters();
          } else {
            if (el.characterView) el.characterView.hidden = true;
            if (el.canvasHint) el.canvasHint.hidden = false;
          }
        }

        debug("切换画布分栏", tab.dataset.tab);
      });
    });
  }

  // ---------------- 连接状态 ----------------

  function setConnection(status, label) {
    el.pill.dataset.state = status;
    el.pillText.textContent = label;
  }

  function send(payload) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(payload));
      return true;
    }
    debug("未连接，消息未发送", payload);
    return false;
  }

  // ---------------- WebSocket ----------------

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws`;
    debug("连接中", url);

    const ws = new WebSocket(url);
    state.ws = ws;

    ws.onopen = () => {
      state.connected = true;
      state.failures = 0;
      state.reconnectDelay = 1000;
      el.pill.title = "WebSocket 已连接";
      setConnection("on", "已连接");
      startHeartbeat();
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        debug("收到非 JSON 消息", event.data);
        return;
      }
      handle(msg);
    };

    ws.onerror = () => debug("WebSocket 异常");

    ws.onclose = (event) => {
      state.connected = false;
      stopHeartbeat();
      state.failures += 1;
      // 连续失败就别再说“重连中”了：后端多半没起来
      if (state.failures >= 3) {
        setConnection("off", "连不上后端");
        el.pill.title = "没连上本地服务：MyWorld.exe 可能已退出（关闭控制台窗口会停掉它）";
      } else {
        setConnection("off", "重连中");
      }
      debug("断开", event.code, "第", state.failures, "次失败，", state.reconnectDelay, "ms 后重连");
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    const delay = state.reconnectDelay;
    state.reconnectDelay = Math.min(state.reconnectDelay * 1.7, state.reconnectMax);
    setTimeout(() => {
      if (!state.connected) connect();
    }, delay);
  }

  function startHeartbeat() {
    stopHeartbeat();
    ping();
    state.heartbeat = setInterval(ping, 10000);
  }

  function stopHeartbeat() {
    if (state.heartbeat) clearInterval(state.heartbeat);
    state.heartbeat = null;
  }

  function ping() {
    state.pingAt = performance.now();
    send({ type: "ping", t: Date.now() });
  }

  // ---------------- 服务端消息 ----------------

  function handle(msg) {
    switch (msg.kind) {
      case "hello":
        state.serverUptime = Number(msg.uptime_seconds || 0);
        state.syncedAt = performance.now();
        el.version.textContent = "v" + (msg.version || "?");
        el.port.textContent = msg.port ?? "—";
        debug("握手成功", msg);
        break;

      case "pong": {
        const rtt = Math.max(0, Math.round(performance.now() - state.pingAt));
        el.latency.textContent = rtt + " ms";
        if (typeof msg.uptime_seconds === "number") {
          state.serverUptime = msg.uptime_seconds;
          state.syncedAt = performance.now();
        }
        break;
      }

      case "tick":
        debug("收到服务端推送", msg);
        refreshStatus();
        break;

      case "broadcast":
        debug("收到广播", msg.payload);
        break;

      case "ack":
        debug("广播已送达", msg.delivered);
        break;

      case "stats":
        fillMeta(msg);
        break;

      case "error":
        debug("服务端错误", msg.message);
        break;

      default:
        debug("未知事件", msg);
    }
  }

  // ---------------- REST ----------------

  async function fetchJSON(path, options = {}) {
    const res = await fetch(path, { cache: "no-store", ...options });
    if (!res.ok) {
      // 后端的 HTTPException 会把可读原因放在 detail 里，直接透给用户
      let detail = `${path} → HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body && body.detail) {
          detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        }
      } catch {
        /* 响应不是 JSON，保持默认信息 */
      }
      throw new Error(detail);
    }
    return res.json();
  }

  async function refreshStatus() {
    try {
      state.status = await fetchJSON("/api/status");
      fillMeta(state.status);
      el.port.textContent = state.status.port;
      el.version.textContent = "v" + state.status.version;
      if (typeof state.status.uptime_seconds === "number") {
        state.serverUptime = state.status.uptime_seconds;
        state.syncedAt = performance.now();
      }
    } catch (err) {
      debug("读取状态失败", err.message);
    }
  }

  async function loadConfig() {
    try {
      state.config = await fetchJSON("/api/config");
      // 状态可能先到、配置后到：补一次渲染，保证「端口来源」有值
      if (state.status) fillMeta(state.status);
    } catch (err) {
      debug("读取配置失败", err.message);
    }
  }

  // ---------------- 渲染 ----------------

  function pair(label, value) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    return [dt, dd];
  }

  function formatStartTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function fillMeta(s) {
    el.meta.replaceChildren(
      ...pair("监听地址", `${s.host}:${s.port}`),
      ...pair("端口来源", state.config?.sources?.port ?? "—"),
      ...pair("启动时间", formatStartTime(s.started_at)),
      ...pair("Python", s.python ?? "—"),
      ...pair("PID", String(s.pid ?? "—")),
      ...pair("请求数", String(s.requests ?? "—")),
      ...pair("广播事件", String(s.events_published ?? "—")),
      ...pair("平台", s.platform ?? "—"),
    );
  }

  function formatDuration(totalSeconds) {
    const total = Math.max(0, Math.floor(totalSeconds));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
  }

  function tickUptime() {
    if (!state.syncedAt) return;
    const seconds = state.serverUptime + (performance.now() - state.syncedAt) / 1000;
    el.uptime.textContent = "运行 " + formatDuration(seconds);
  }

  // ---------------- 交互 ----------------

  el.btnPing.addEventListener("click", () => {
    if (send({ type: "ping", t: Date.now() })) debug("已发送 ping");
  });

  el.btnTick.addEventListener("click", async () => {
    try {
      const result = await fetchJSON("/api/demo/tick", { method: "POST" });
      debug("已触发服务端推送", result);
    } catch (err) {
      debug("推送失败", err.message);
    }
  });

  // ---------------- 启动 ----------------

  initTheme();
  initRail();
  initSidebar();
  initWorkTabs();
  on(el.btnCreateWorld, "click", () => openCreateDialog("world"));
  on(el.btnCreatePreset, "click", () => openCreateDialog("preset"));
  on(el.btnLoadWorld, "click", loadSelectedWorld);
  on(el.btnCloseWorld, "click", closeLoadedWorld);
  initWorldMenu();
  on(el.btnConfirmOk, "click", confirmDelete);
  on(el.btnConfirmCancel, "click", () => el.confirmDialog?.close());

  // 角色属性面板
  on(el.btnAddAttr, "click", () => el.attrList?.append(makeAttrRow()));
  on(el.btnCloseDetail, "click", closeCharacterPanel);
  on(el.btnDetailCancel, "click", closeCharacterPanel);
  on(el.btnDetailSave, "click", saveCharacterDetail);
  on(el.btnUsePreset, "click", openPresetPicker);
  on(el.btnPresetPickerCancel, "click", () => el.presetPickerDialog?.close());
  on(el.btnImportCancel, "click", () => {
    pendingImport = null;
    el.presetImportDialog?.close();
  });
  on(el.btnImportConfirm, "click", () => {
    confirmPresetImport();
    el.presetImportDialog?.close();
  });
  el.presetImportDialog?.addEventListener("close", () => {
    pendingImport = null;
  });

  // 点面板里的立绘 → 选图 → 裁剪 → 直接上传
  on(el.detailPhotoBtn, "click", () => el.detailImage?.click());
  on(el.detailImage, "change", () => {
    const file = el.detailImage?.files?.[0];
    if (!file) return;
    el.detailImage.value = "";
    openCropDialog(file, "portrait");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (el.cropDialog?.open || el.createDialog?.open || el.confirmDialog?.open) return;
    if (el.characterPanel?.classList.contains("is-open")) closeCharacterPanel();
  });
  on(el.createForm, "submit", (event) => {
    event.preventDefault();
    submitCreate();
  });
  on(el.btnDialogCancel, "click", closeCreateDialog);
  // Esc / 点击遮罩关闭时清掉错误提示
  on(el.createDialog, "cancel", clearCreateError);
  on(el.createDialog, "close", clearCreateError);

  // 封面：选本地图片 → 裁剪弹窗
  on(el.btnPresetAddAttr, "click", () => {
    el.presetAttrList?.append(makeKeyRow());
    el.presetAttrList?.lastElementChild?.querySelector(".attr-key-input")?.focus();
  });

  on(el.coverPreview, "click", () => el.worldImage?.click());
  on(el.worldImage, "change", () => {
    const file = el.worldImage?.files?.[0];
    if (!file) return;
    el.worldImage.value = "";
    openCropDialog(file);
  });
  on(el.cropZoom, "input", () => setCoverZoom(Number(el.cropZoom.value)));
  on(el.btnCropCancel, "click", () => el.cropDialog?.close());
  on(el.btnCropApply, "click", applyCrop);
  initCropDrag();
  initCropWheel();
  initCharacterDrag();
  refreshStatus();
  loadConfig();
  loadWorlds();
  connect();
  setInterval(tickUptime, 1000);
  setInterval(refreshStatus, 15000);
})();
