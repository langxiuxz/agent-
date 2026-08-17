let currentThreadId = null;
let selectedFile = null;
let sending = false;

const $ = (id) => document.getElementById(id);

function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(text) {
  if (typeof marked !== "undefined" && typeof marked.parse === "function") {
    try {
      return marked.parse(text);
    } catch (_) {}
  }
  return escapeHtml(text);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let msg = `请求失败（${res.status}）`;
    try {
      const j = await res.json();
      if (j && j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

// ---------- 会话列表 ----------
function renderSessionList(sessions) {
  const list = $("session-list");
  list.innerHTML = "";
  sessions.forEach((s) => {
    const li = document.createElement("li");
    li.className = "session-item" + (s.session_id === currentThreadId ? " active" : "");
    li.textContent = s.title || "新对话";
    li.addEventListener("click", () => selectSession(s.session_id));
    list.appendChild(li);
  });
}

async function refreshSessions() {
  const { sessions } = await api("/api/sessions");
  renderSessionList(sessions);
}

async function selectSession(sid) {
  currentThreadId = sid;
  await loadHistory(sid);
  await refreshSessions();
}

async function loadHistory(sid) {
  const { messages } = await api(`/api/history/${sid}`);
  $("messages").innerHTML = "";
  messages.forEach((m) => addMessage(m.role, m.text, m.image_url));
  const firstUser = messages.find((m) => m.role === "user");
  $("chat-title").textContent = (firstUser && firstUser.text ? firstUser.text : "新对话").slice(0, 20);
  scrollToBottom();
}

// ---------- 消息渲染 ----------
function addMessage(role, text, imageUrl) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  if (role === "user" && imageUrl) {
    const img = document.createElement("img");
    img.className = "msg-image";
    img.src = imageUrl;
    img.alt = "食材图片";
    wrap.appendChild(img);
  }
  if (text) {
    const body = document.createElement("div");
    body.className = "msg-body";
    if (role === "assistant") body.innerHTML = renderMarkdown(text);
    else body.textContent = text;
    wrap.appendChild(body);
  }
  $("messages").appendChild(wrap);
  return wrap;
}

function addAssistantStream() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  const body = document.createElement("div");
  body.className = "msg-body";
  body.innerHTML = '<span class="loading-dots">思考中…</span>';
  wrap.appendChild(body);
  $("messages").appendChild(wrap);
  return body;
}

function addError(msg) {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  const body = document.createElement("div");
  body.className = "msg-body error";
  body.textContent = "⚠️ " + msg;
  wrap.appendChild(body);
  $("messages").appendChild(wrap);
}

function scrollToBottom() {
  $("messages").scrollTop = $("messages").scrollHeight;
}

// ---------- 图片选择 ----------
function updatePreview() {
  if (selectedFile) {
    $("preview-img").src = URL.createObjectURL(selectedFile);
    $("image-preview").classList.remove("hidden");
  } else {
    $("preview-img").src = "";
    $("image-preview").classList.add("hidden");
  }
}

function clearImageSelection() {
  selectedFile = null;
  $("file-input").value = "";
  updatePreview();
}

function autoResize() {
  const el = $("input");
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

// ---------- 流式对话 ----------
async function streamChat(threadId, message, imageUrl, onToken) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, message, image_url: imageUrl }),
  });
  if (!res.ok) {
    let msg = `请求失败（${res.status}）`;
    try {
      const j = await res.json();
      if (j && j.detail) msg = j.detail;
    } catch (_) {}
    throw new Error(msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    onToken(decoder.decode(value, { stream: true }));
  }
}

async function send() {
  if (sending) return;
  const text = $("input").value.trim();
  if (!text && !selectedFile) return;
  if (!currentThreadId) currentThreadId = uuid();

  sending = true;
  $("send-btn").disabled = true;

  const localImg = selectedFile ? URL.createObjectURL(selectedFile) : null;
  addMessage("user", text, localImg);
  $("input").value = "";
  autoResize();

  const body = addAssistantStream();
  scrollToBottom();

  try {
    let imageUrl = null;
    if (selectedFile) {
      const fd = new FormData();
      fd.append("image", selectedFile);
      const up = await api("/api/upload", { method: "POST", body: fd });
      imageUrl = up.url;
    }

    let acc = "";
    let timer = null;
    await streamChat(currentThreadId, text, imageUrl, (token) => {
      acc += token;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        body.innerHTML = renderMarkdown(acc);
        scrollToBottom();
      }, 40);
    });
    if (timer) clearTimeout(timer);
    body.innerHTML = renderMarkdown(acc);
    scrollToBottom();
    await refreshSessions();
  } catch (e) {
    body.remove();
    addError(e.message || "出错了，请重试");
  } finally {
    sending = false;
    $("send-btn").disabled = false;
    clearImageSelection();
    scrollToBottom();
  }
}

// ---------- 新建 / 清空 ----------
async function newSession() {
  currentThreadId = uuid();
  $("messages").innerHTML = "";
  $("chat-title").textContent = "新对话";
  await refreshSessions();
  $("input").focus();
}

async function clearConversation() {
  if (!currentThreadId) return;
  if (!confirm("确定清空当前对话吗？")) return;
  try {
    await api(`/api/history/${currentThreadId}`, { method: "DELETE" });
  } catch (_) {}
  await newSession();
}

async function init() {
  $("new-session-btn").addEventListener("click", newSession);
  $("clear-btn").addEventListener("click", clearConversation);
  $("send-btn").addEventListener("click", send);
  $("upload-btn").addEventListener("click", () => $("file-input").click());
  $("remove-image").addEventListener("click", clearImageSelection);
  $("file-input").addEventListener("change", (e) => {
    selectedFile = e.target.files[0] || null;
    updatePreview();
  });
  $("input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  $("input").addEventListener("input", autoResize);

  try {
    const { sessions } = await api("/api/sessions");
    if (!sessions.length) {
      currentThreadId = uuid();
      $("chat-title").textContent = "新对话";
    } else {
      currentThreadId = sessions[0].session_id;
      renderSessionList(sessions);
      await loadHistory(currentThreadId);
    }
  } catch (e) {
    addError("初始化失败：" + (e.message || ""));
  }
}

init();
