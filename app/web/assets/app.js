const SESSIONS_KEY = "rag_chat_sessions_v6";
const SETTINGS_KEY = "rag_chat_settings_v6";
const AUTH_TOKEN_KEY = "rag_auth_token_v1";

const THINKING_IMAGES = Array.from(
  { length: 18 },
  (_, idx) => `/assets/rotator/photo_${String(idx + 1).padStart(2, "0")}.png`
);

const messagesNode = document.getElementById("messages");
const chatListNode = document.getElementById("chat-list");
const chatSearchNode = document.getElementById("chat-search");
const composerStatusNode = document.getElementById("composer-status");

const askForm = document.getElementById("ask-form");
const questionInput = document.getElementById("ask-question");
const attachBtn = document.getElementById("attach-btn");
const fileInput = document.getElementById("file-input");
const responseModeInput = document.getElementById("response-mode");

const newChatBtn = document.getElementById("new-chat-btn");
const shareChatBtn = document.getElementById("share-chat-btn");
const openSettingsBtn = document.getElementById("open-settings-btn");

const settingsModal = document.getElementById("settings-modal");
const settingsForm = document.getElementById("settings-form");
const closeSettingsBtn = document.getElementById("close-settings-btn");
const logoutBtn = document.getElementById("logout-btn");
const themeSelect = document.getElementById("theme-select");
const defaultTypeInput = document.getElementById("default-type");
const defaultModeInput = document.getElementById("default-mode");
const defaultVersionInput = document.getElementById("default-version");
const showConfidenceInput = document.getElementById("show-confidence");
const enterToSendInput = document.getElementById("enter-to-send");
const profileEmailInput = document.getElementById("profile-email");
const profileDisplayNameInput = document.getElementById("profile-display-name");

const authModal = document.getElementById("auth-modal");
const authStatusNode = document.getElementById("auth-status");
const authTabLoginBtn = document.getElementById("auth-tab-login");
const authTabRegisterBtn = document.getElementById("auth-tab-register");
const authLoginForm = document.getElementById("auth-login-form");
const authRegisterForm = document.getElementById("auth-register-form");
const loginEmailInput = document.getElementById("login-email");
const loginPasswordInput = document.getElementById("login-password");
const registerDisplayNameInput = document.getElementById("register-display-name");
const registerEmailInput = document.getElementById("register-email");
const registerPasswordInput = document.getElementById("register-password");

const defaultSettings = {
  theme: "system",
  defaultType: "technical",
  defaultMode: "standard",
  defaultVersion: "v1",
  showConfidence: true,
  enterToSend: true,
};

let settings = loadSettings();
let sessions = loadSessions();
let activeSessionId = sessions[0]?.id || createSession("New chat");
let chatSearchQuery = "";
let authToken = localStorage.getItem(AUTH_TOKEN_KEY) || "";
let currentUser = null;
let thinkingFrameIndex = 0;
let thinkingTimer = null;

initialize().catch((error) => {
  console.error(error);
  setComposerStatus(`Ошибка инициализации: ${error}`);
});

async function initialize() {
  applyTheme();
  initializeMermaid();
  bindSettingsToUI();
  renderChatList();
  renderMessages();
  bindEvents();
  await restoreSession();
  await loadSharedChatFromUrl();
}

function uid() {
  return `${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...defaultSettings };
    const parsed = JSON.parse(raw);
    return { ...defaultSettings, ...parsed };
  } catch (_) {
    return { ...defaultSettings };
  }
}

function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function loadSessions() {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_) {
    return [];
  }
}

function saveSessions() {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

function createSession(title, options = {}) {
  const id = uid();
  sessions.unshift({
    id,
    title,
    messages: [],
    createdAt: new Date().toISOString(),
    readOnly: Boolean(options.readOnly),
  });
  saveSessions();
  return id;
}

function getActiveSession() {
  return sessions.find((session) => session.id === activeSessionId);
}

function applyTheme() {
  const root = document.body;
  const selected = settings.theme;
  if (selected === "system") {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = prefersDark ? "dark" : "light";
  } else {
    root.dataset.theme = selected;
  }
}

function initializeMermaid() {
  if (!window.mermaid) return;
  const isDark = document.body.dataset.theme === "dark";
  window.mermaid.initialize({
    startOnLoad: false,
    securityLevel: "loose",
    theme: isDark ? "dark" : "default",
  });
}

function bindSettingsToUI() {
  themeSelect.value = settings.theme;
  defaultTypeInput.value = settings.defaultType;
  defaultModeInput.value = settings.defaultMode;
  responseModeInput.value = settings.defaultMode;
  defaultVersionInput.value = settings.defaultVersion;
  showConfidenceInput.checked = settings.showConfidence;
  enterToSendInput.checked = settings.enterToSend;
  profileEmailInput.value = currentUser?.email || "";
  profileDisplayNameInput.value = currentUser?.display_name || "";
}

function setAuthStatus(message) {
  authStatusNode.textContent = message || "";
}

function openAuthModal() {
  setAuthTab("login");
  setAuthStatus("");
  if (!authModal.open) authModal.showModal();
}

function closeAuthModal() {
  if (authModal.open) authModal.close();
}

function setAuthTab(tabName) {
  const isLogin = tabName === "login";
  authTabLoginBtn.classList.toggle("active", isLogin);
  authTabRegisterBtn.classList.toggle("active", !isLogin);
  authLoginForm.classList.toggle("hidden", !isLogin);
  authRegisterForm.classList.toggle("hidden", isLogin);
}

async function restoreSession() {
  if (!authToken) {
    openAuthModal();
    setComposerStatus("Войдите в аккаунт для работы с документами.");
    return;
  }

  try {
    currentUser = await apiRequest("/auth/me", { method: "GET" }, true);
    if (currentUser?.settings?.ui && typeof currentUser.settings.ui === "object") {
      settings = { ...settings, ...currentUser.settings.ui };
      saveSettings();
      applyTheme();
      initializeMermaid();
    }
    bindSettingsToUI();
    closeAuthModal();
    setComposerStatus(`Вы вошли как ${currentUser.display_name}.`);
  } catch (_) {
    clearAuth();
    openAuthModal();
    setComposerStatus("Сессия истекла. Выполните вход.");
  }
}

function clearAuth() {
  authToken = "";
  currentUser = null;
  localStorage.removeItem(AUTH_TOKEN_KEY);
  bindSettingsToUI();
}

async function apiRequest(path, options = {}, authRequired = false) {
  const requestOptions = { ...options };
  requestOptions.headers = { ...(options.headers || {}) };

  if (authToken) requestOptions.headers.Authorization = `Bearer ${authToken}`;
  if (authRequired && !authToken) throw new Error("Требуется авторизация");

  const response = await fetch(path, requestOptions);
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (_) {
    payload = {};
  }

  if (!response.ok) {
    if (response.status === 401) {
      clearAuth();
      openAuthModal();
    }
    throw new Error(payload?.detail || `HTTP ${response.status}`);
  }
  return payload;
}

function renderChatList() {
  const query = chatSearchQuery.trim().toLowerCase();
  const filtered = sessions.filter((session) => {
    if (!query) return true;
    if ((session.title || "").toLowerCase().includes(query)) return true;
    return session.messages.some((message) => (message.text || "").toLowerCase().includes(query));
  });

  chatListNode.innerHTML = "";
  filtered.forEach((session) => {
    const button = document.createElement("button");
    button.className = `chat-item ${session.id === activeSessionId ? "active" : ""}`;
    const title = document.createElement("div");
    title.className = "chat-item-title";
    title.textContent = normalizeSingleLine(session.title || "Untitled chat");

    const preview = document.createElement("div");
    preview.className = "chat-item-preview";
    preview.textContent = getSessionPreview(session);

    button.appendChild(title);
    button.appendChild(preview);
    button.onclick = () => {
      activeSessionId = session.id;
      renderChatList();
      renderMessages();
    };
    chatListNode.appendChild(button);
  });
}

function appendMessage(role, text, meta = "") {
  const session = getActiveSession();
  if (!session) return;
  session.messages.push({ id: uid(), role, text, meta, ts: new Date().toISOString() });
  if (session.title === "New chat" && role === "user") {
    session.title = normalizeSingleLine(text).slice(0, 56) || "New chat";
  }
  saveSessions();
  renderChatList();
  renderMessages();
}

function normalizeSingleLine(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function getSessionPreview(session) {
  const messages = Array.isArray(session.messages) ? session.messages : [];
  const lastMessage = messages[messages.length - 1];
  if (!lastMessage || !lastMessage.text) return "Пустой чат";
  const clean = normalizeSingleLine(lastMessage.text);
  if (!clean) return "Пустой чат";
  return clean.slice(0, 72);
}

function parseContentParts(text) {
  const parts = [];
  const regex = /```mermaid\s*([\s\S]*?)```/gi;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    const before = text.slice(lastIndex, match.index);
    if (before) parts.push({ type: "text", value: before });
    parts.push({ type: "mermaid", value: match[1].trim() });
    lastIndex = regex.lastIndex;
  }
  const tail = text.slice(lastIndex);
  if (tail) parts.push({ type: "text", value: tail });
  if (parts.length === 0) parts.push({ type: "text", value: text || "" });
  return parts;
}

function renderBubbleContent(bubble, text) {
  bubble.innerHTML = "";
  const parts = parseContentParts(text || "");

  parts.forEach((part) => {
    if (part.type === "mermaid") {
      const wrap = document.createElement("div");
      wrap.className = "mermaid-wrap";
      const mermaidNode = document.createElement("div");
      mermaidNode.className = "mermaid";
      mermaidNode.textContent = part.value;
      wrap.appendChild(mermaidNode);
      bubble.appendChild(wrap);
      return;
    }

    const textNode = document.createElement("div");
    textNode.className = "bubble-text";
    textNode.textContent = part.value;
    bubble.appendChild(textNode);
  });
}

function isThinkingMessage(message) {
  if (!message || message.role !== "assistant") return false;
  return String(message.text || "").trim() === "Думаю...";
}

function appendThinkingVisual(bubble) {
  const wrap = document.createElement("div");
  wrap.className = "thinking-visual";
  const img = document.createElement("img");
  img.className = "thinking-image";
  img.src = THINKING_IMAGES[thinkingFrameIndex % THINKING_IMAGES.length];
  img.alt = "Thinking visual";
  wrap.appendChild(img);

  const label = document.createElement("p");
  label.textContent = "Подбираю ответ...";
  wrap.appendChild(label);
  bubble.appendChild(wrap);
}

function updateThinkingImages() {
  const images = document.querySelectorAll(".thinking-image");
  if (images.length === 0) return;
  const src = THINKING_IMAGES[thinkingFrameIndex % THINKING_IMAGES.length];
  images.forEach((image) => {
    image.src = src;
  });
}

function stopThinkingTimer() {
  if (thinkingTimer) {
    clearTimeout(thinkingTimer);
    thinkingTimer = null;
  }
}

function scheduleThinkingTick() {
  stopThinkingTimer();
  thinkingTimer = setTimeout(() => {
    thinkingFrameIndex = (thinkingFrameIndex + 1) % THINKING_IMAGES.length;
    updateThinkingImages();
    scheduleThinkingTick();
  }, 2500);
}

function syncThinkingTimer() {
  const hasThinking = document.querySelectorAll(".thinking-image").length > 0;
  if (!hasThinking) {
    stopThinkingTimer();
    return;
  }
  updateThinkingImages();
  if (!thinkingTimer) {
    scheduleThinkingTick();
  }
}

function runMermaidRender() {
  if (!window.mermaid) return;
  const nodes = document.querySelectorAll(".mermaid");
  if (nodes.length === 0) return;
  window.mermaid.run({ nodes }).catch((error) => {
    console.error("Mermaid render error:", error);
  });
}

function renderMessages() {
  const session = getActiveSession();
  messagesNode.innerHTML = "";

  if (!session || session.messages.length === 0) {
    const row = document.createElement("div");
    row.className = "msg assistant";
    row.innerHTML =
      '<div class="bubble"><div class="bubble-text">Загрузите файл кнопкой "+" в поле ввода и задайте вопрос. На каждый запрос система показывает диаграмму (или market comparison).</div></div>';
    messagesNode.appendChild(row);
  } else {
    session.messages.forEach((message) => {
      const row = document.createElement("div");
      row.className = `msg ${message.role}`;

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      renderBubbleContent(bubble, message.text);
      if (isThinkingMessage(message)) {
        appendThinkingVisual(bubble);
      }

      if (message.meta) {
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = message.meta;
        bubble.appendChild(meta);
      }
      row.appendChild(bubble);
      messagesNode.appendChild(row);
    });
  }

  setComposerReadOnly(Boolean(session?.readOnly));
  messagesNode.scrollTop = messagesNode.scrollHeight;
  runMermaidRender();
  syncThinkingTimer();
}

function setComposerReadOnly(isReadOnly) {
  questionInput.disabled = isReadOnly;
  attachBtn.disabled = isReadOnly;
  responseModeInput.disabled = isReadOnly;
  askForm.querySelector('button[type="submit"]').disabled = isReadOnly;
  if (isReadOnly) {
    setComposerStatus("Это shared-чат в режиме чтения. Нажмите New chat для продолжения.");
  }
}

function setComposerStatus(message) {
  composerStatusNode.textContent = message;
}

function normalizeTextareaHeight() {
  questionInput.style.height = "auto";
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 220)}px`;
}

async function uploadDocument(file) {
  const version = (settings.defaultVersion || "v1").trim() || "v1";
  const formData = new FormData();
  formData.append("file", file);
  formData.append("version", version);

  setComposerStatus(`Загрузка файла: ${file.name} ...`);
  const result = await apiRequest(
    "/documents/upload",
    {
      method: "POST",
      body: formData,
    },
    true
  );

  appendMessage(
    "assistant",
    `Файл загружен: ${result.document_name}\nИндексировано чанков: ${result.chunks_indexed}\nВерсия: ${result.version}`
  );
  setComposerStatus(`Файл ${result.document_name} успешно загружен.`);
}

async function sendQuestion(question) {
  appendMessage("assistant", "Думаю...");
  const session = getActiveSession();
  const pending = session.messages[session.messages.length - 1];

  const payload = {
    question,
    type: settings.defaultType || "technical",
    mode: responseModeInput.value || settings.defaultMode || "standard",
  };
  if (settings.defaultVersion?.trim()) payload.version = settings.defaultVersion.trim();

  try {
    const result = await apiRequest(
      "/ask",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
      true
    );

    pending.text = result.answer || "";
    if (settings.showConfidence) {
      const confidence = Number(result.confidence || 0).toFixed(3);
      const docs = (result.used_documents || []).join(", ") || "-";
      pending.meta = `confidence=${confidence} | docs=${docs} | type=${payload.type} | mode=${payload.mode} | version=${payload.version || "-"}`;
    } else {
      pending.meta = "";
    }
    setComposerStatus("Готово.");
  } catch (error) {
    pending.text = `Ошибка: ${error}`;
    pending.meta = "";
    setComposerStatus("Ошибка ответа.");
  }

  saveSessions();
  renderMessages();
}

async function shareCurrentChat() {
  const session = getActiveSession();
  if (!session || session.messages.length === 0) {
    setComposerStatus("Нечего публиковать: чат пустой.");
    return;
  }

  try {
    const result = await apiRequest(
      "/share",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: session.title || "Shared chat",
          messages: session.messages.map((msg) => ({
            role: msg.role,
            text: msg.text,
            meta: msg.meta || "",
            ts: msg.ts || "",
          })),
        }),
      },
      true
    );
    await navigator.clipboard.writeText(result.share_url);
    setComposerStatus(`Ссылка скопирована: ${result.share_url}`);
  } catch (error) {
    setComposerStatus(`Не удалось поделиться чатом: ${error}`);
  }
}

async function loadSharedChatFromUrl() {
  const shareToken = new URLSearchParams(window.location.search).get("share");
  if (!shareToken) return;

  try {
    const payload = await apiRequest(`/share/${encodeURIComponent(shareToken)}`, { method: "GET" });
    const newId = createSession(`Shared: ${payload.title}`, { readOnly: true });
    const session = sessions.find((item) => item.id === newId);
    session.messages = (payload.messages || []).map((message) => ({
      id: uid(),
      role: message.role || "assistant",
      text: message.text || "",
      meta: message.meta || "",
      ts: message.ts || payload.created_at || new Date().toISOString(),
    }));
    session.readOnly = true;
    activeSessionId = newId;
    saveSessions();
    renderChatList();
    renderMessages();
  } catch (error) {
    setComposerStatus(`Не удалось открыть shared-чат: ${error}`);
  }
}

function bindEvents() {
  attachBtn.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      await uploadDocument(file);
    } catch (error) {
      appendMessage("assistant", `Ошибка загрузки: ${error}`);
      setComposerStatus("Ошибка загрузки файла.");
    } finally {
      fileInput.value = "";
    }
  });

  questionInput.addEventListener("input", normalizeTextareaHeight);

  questionInput.addEventListener("keydown", (event) => {
    if (!settings.enterToSend) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      askForm.requestSubmit();
    }
  });

  askForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const session = getActiveSession();
    if (session?.readOnly) return;

    const question = questionInput.value.trim();
    if (!question) return;

    appendMessage("user", question);
    questionInput.value = "";
    normalizeTextareaHeight();
    setComposerStatus("Формирую ответ...");
    await sendQuestion(question);
  });

  newChatBtn.addEventListener("click", () => {
    activeSessionId = createSession("New chat");
    renderChatList();
    renderMessages();
    setComposerStatus("Новый чат создан.");
  });

  shareChatBtn.addEventListener("click", async () => {
    await shareCurrentChat();
  });

  chatSearchNode.addEventListener("input", () => {
    chatSearchQuery = chatSearchNode.value || "";
    renderChatList();
  });

  openSettingsBtn.addEventListener("click", () => {
    bindSettingsToUI();
    settingsModal.showModal();
  });

  closeSettingsBtn.addEventListener("click", () => settingsModal.close());

  logoutBtn.addEventListener("click", async () => {
    try {
      await apiRequest("/auth/logout", { method: "POST" }, false);
    } catch (_) {
      // no-op
    }
    clearAuth();
    settingsModal.close();
    openAuthModal();
    setComposerStatus("Вы вышли из аккаунта.");
  });

  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    settings.theme = themeSelect.value;
    settings.defaultType = defaultTypeInput.value;
    settings.defaultMode = defaultModeInput.value;
    settings.defaultVersion = defaultVersionInput.value.trim() || "v1";
    settings.showConfidence = showConfidenceInput.checked;
    settings.enterToSend = enterToSendInput.checked;
    saveSettings();
    responseModeInput.value = settings.defaultMode;
    applyTheme();
    initializeMermaid();

    if (currentUser) {
      try {
        currentUser = await apiRequest(
          "/auth/me",
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              display_name: profileDisplayNameInput.value,
              settings: { ui: settings },
            }),
          },
          true
        );
      } catch (error) {
        setComposerStatus(`Профиль не сохранен: ${error}`);
      }
    }

    settingsModal.close();
    renderMessages();
    setComposerStatus("Настройки сохранены.");
  });

  authTabLoginBtn.addEventListener("click", () => setAuthTab("login"));
  authTabRegisterBtn.addEventListener("click", () => setAuthTab("register"));

  authLoginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setAuthStatus("Выполняю вход...");
    try {
      const payload = await apiRequest("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: loginEmailInput.value.trim(),
          password: loginPasswordInput.value,
        }),
      });
      authToken = payload.access_token;
      currentUser = payload.user;
      if (currentUser?.settings?.ui && typeof currentUser.settings.ui === "object") {
        settings = { ...settings, ...currentUser.settings.ui };
        saveSettings();
        applyTheme();
        initializeMermaid();
      }
      localStorage.setItem(AUTH_TOKEN_KEY, authToken);
      closeAuthModal();
      bindSettingsToUI();
      setComposerStatus(`Вы вошли как ${currentUser.display_name}.`);
    } catch (error) {
      setAuthStatus(String(error));
    }
  });

  authRegisterForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setAuthStatus("Создаю аккаунт...");
    try {
      const payload = await apiRequest("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: registerEmailInput.value.trim(),
          password: registerPasswordInput.value,
          display_name: registerDisplayNameInput.value.trim(),
        }),
      });
      authToken = payload.access_token;
      currentUser = payload.user;
      if (currentUser?.settings?.ui && typeof currentUser.settings.ui === "object") {
        settings = { ...settings, ...currentUser.settings.ui };
        saveSettings();
        applyTheme();
        initializeMermaid();
      }
      localStorage.setItem(AUTH_TOKEN_KEY, authToken);
      closeAuthModal();
      bindSettingsToUI();
      setComposerStatus(`Аккаунт создан: ${currentUser.display_name}.`);
    } catch (error) {
      setAuthStatus(String(error));
    }
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (settings.theme === "system") {
      applyTheme();
      initializeMermaid();
      renderMessages();
    }
  });
}
