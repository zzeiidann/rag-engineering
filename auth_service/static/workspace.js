/* No persisted answers or browser-stored bearer tokens. Identity lives on the server. */
"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  user: null,
  csrf: "",
  documents: [],
  history: [],
  epoch: 0,
  scopeEpoch: 0,
  busy: false,
};
let controller,
  timer,
  lastQuestion = "",
  currentAnswer = "";

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(
      response.status === 401
        ? "Your session has expired. Please sign in again."
        : response.status === 429
          ? "Too many requests. Please wait a moment and retry."
          : "The knowledge service is temporarily unavailable. Please retry shortly. If this continues, contact your administrator.",
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
function notify(message) {
  $("notice").textContent = message;
  $("notice").hidden = false;
  setTimeout(() => {
    $("notice").hidden = true;
  }, 4500);
}
function busy(value) {
  state.busy = value;
  $("sendButton").disabled = value;
  $("loading").hidden = !value;
  $("answer").setAttribute("aria-busy", String(value));
  clearInterval(timer);
}
function tab(library = false) {
  $("askView").hidden = library;
  $("libraryView").hidden = !library;
  $("askTab").classList.toggle("selected", !library);
  $("libraryTab").classList.toggle("selected", library);
  $("pageLabel").textContent = library
    ? "Document library"
    : "Knowledge assistant";
  $("askTab").setAttribute("aria-current", library ? "false" : "page");
  $("libraryTab").setAttribute("aria-current", library ? "page" : "false");
}
function reset() {
  state.epoch++;
  controller?.abort();
  busy(false);
  currentAnswer = "";
  $("answer").replaceChildren();
  $("sources").replaceChildren();
  $("askedQuestion").textContent = "";
  $("result").hidden = true;
  $("welcome").hidden = false;
  $("starters").hidden = false;
  $("sourceHeading").textContent = "No sources yet";
  $("sourceIntro").textContent =
    "Ask a question to see the documents supporting your answer.";
  $("question").value = "";
  $("questionLength").textContent = "0 / 4,000";
}
function clearPrivateState() {
  state.scopeEpoch++;
  reset();
  lastQuestion = "";
  state.history = [];
  state.documents = [];
  renderHistory();
  renderLibrary();
  $("libraryCount").textContent = "—";
}
function setIdentity(user) {
  if (JSON.stringify(user) !== JSON.stringify(state.user)) clearPrivateState();
  state.user = user;
  const scope = !user
    ? "Public knowledge"
    : user.role === "client"
      ? user.client_id
      : user.department ||
        (user.role === "guest"
          ? "Public knowledge"
          : "Internal · explicit permissions");
  $("accountName").textContent = user?.username || "Guest";
  $("accountDetail").textContent = scope;
  $("avatar").textContent = (user?.username || "G").slice(0, 1).toUpperCase();
  $("accessLabel").textContent = user
    ? `${user.role} / ${scope}`
    : "Public access";
  $("identityFooter").textContent =
    `${user?.role || "guest"} SESSION`.toUpperCase();
  $("adminLink").hidden = !user?.is_admin;
  $("signInTop").textContent = user ? "Sign out ↗" : "Sign in ↗";
  $("accountAction").setAttribute("aria-label", user ? "Sign out" : "Sign in");
  $("scopeLogin").hidden = !!user;
  $("scopeDescription").textContent = !user
    ? "You’re browsing public information. Sign in to include documents shared with your account."
    : user.role === "client"
      ? `Public documents and records belonging to ${user.client_id}. Other clients’ records are excluded.`
      : "Documents are scoped to your role, department, and explicit permissions. Signing in does not grant access to every record.";
}
async function refresh() {
  try {
    const data = await request("/api/workspace/session");
    setIdentity(data.user);
    state.csrf = data.csrf_token;
    await loadDocuments();
  } catch (error) {
    clearPrivateState();
    setIdentity(null);
    state.csrf = "";
    notify(error.message);
  }
}
async function loadDocuments() {
  const epoch = state.scopeEpoch;
  try {
    const documents = await request("/api/workspace/documents");
    if (epoch !== state.scopeEpoch) return;
    state.documents = documents;
    $("libraryCount").textContent = documents.length;
    $("libraryError").hidden = true;
    renderLibrary();
  } catch (error) {
    if (epoch !== state.scopeEpoch) return;
    state.documents = [];
    renderLibrary();
    $("libraryCount").textContent = "—";
    $("libraryError").textContent = error.message;
    $("libraryError").hidden = false;
  }
}
function renderLibrary() {
  $("libraryTotal").textContent = ` / ${state.documents.length}`;
  const search = $("documentSearch").value.toLowerCase();
  const documents = state.documents.filter((d) =>
    `${d.title} ${d.document_id}`.toLowerCase().includes(search),
  );
  $("documentsList").replaceChildren();
  for (const doc of documents) {
    const row = node("div", undefined, "document-row");
    const detail = node("div");
    detail.append(node("h2", doc.title), node("p", doc.document_id));
    const ask = node("button", "Ask about this ↗", "text-button");
    ask.onclick = () => {
      tab();
      $("question").value = `What does ${doc.title} explain?`;
      $("question").dispatchEvent(new Event("input"));
      $("question").focus();
    };
    row.append(node("span", "▤", "doc-icon"), detail, ask);
    $("documentsList").append(row);
  }
  if (!documents.length)
    $("documentsList").append(
      node(
        "p",
        "No documents to display. Try a different search or check your service connection.",
        "library-empty",
      ),
    );
}
function renderHistory() {
  $("history").replaceChildren();
  for (const item of state.history) {
    const button = node("button", item.query, "history-item");
    button.onclick = async () => {
      const epoch = state.epoch;
      await refresh();
      if (epoch === state.epoch && state.history.includes(item)) {
        reset();
        showResult(item.query, item.data);
        tab();
      }
    };
    $("history").append(button);
  }
  if (!state.history.length)
    $("history").append(node("p", "Your questions will appear here.", "quiet"));
}
function showResult(query, data) {
  $("welcome").hidden = true;
  $("starters").hidden = true;
  $("result").hidden = false;
  $("askedQuestion").textContent = query;
  $("queryError").hidden = true;
  $("copyAnswer").hidden = false;
  $("resultNote").hidden = false;
  currentAnswer = data.answer;
  const sources = data.sources || [];
  $("sourceHeading").textContent = `${sources.length} supporting sources`;
  $("sourceIntro").textContent = sources.length
    ? "Retrieved for this answer, within your access."
    : "No relevant accessible sources were found for this question.";
  $("sources").replaceChildren();
  sources.forEach((source, index) => {
    const card = node("div", undefined, "source-item");
    card.id = `source-${index}`;
    card.tabIndex = -1;
    const title =
      state.documents.find((d) => d.document_id === source.document_id)
        ?.title || source.document_id;
    card.append(
      node("span", String(index + 1).padStart(2, "0"), "source-index"),
      node("h3", title),
      node("code", source.document_id),
    );
    const details = node("details");
    details.append(
      node("summary", "Source identifier"),
      node("small", source.source_id),
    );
    card.append(details);
    $("sources").append(card);
  });
  // Treat all model text as text, never HTML. Only known source IDs become links.
  $("answer").replaceChildren();
  for (const paragraph of data.answer.split(/\n\s*\n/)) {
    const p = node("p");
    for (const part of paragraph.split(/(\[[^\]\n]+\])/g)) {
      const identifiers =
        part.startsWith("[") && part.endsWith("]")
          ? part
              .slice(1, -1)
              .split(",")
              .map((id) => id.trim())
          : [];
      const indices = identifiers.map((id) =>
        sources.findIndex((s) => s.source_id === id),
      );
      if (!indices.length || indices.some((index) => index < 0))
        p.append(document.createTextNode(part));
      else
        for (const index of indices) {
          const cite = node("button", `[${index + 1}]`, "citation");
          cite.setAttribute("aria-label", `Go to source ${index + 1}`);
          cite.onclick = () => {
            $(`source-${index}`).scrollIntoView({
              block: "center",
              behavior: "smooth",
            });
            $(`source-${index}`).focus();
          };
          p.append(cite);
        }
    }
    $("answer").append(p);
  }
}
async function ask(query) {
  if (state.busy || !query.trim()) return;
  query = query.trim();
  reset();
  tab();
  lastQuestion = query;
  const epoch = state.epoch;
  controller = new AbortController();
  $("welcome").hidden = true;
  $("starters").hidden = true;
  $("result").hidden = false;
  $("askedQuestion").textContent = query;
  $("queryError").hidden = true;
  $("copyAnswer").hidden = true;
  $("resultNote").hidden = true;
  busy(true);
  const start = Date.now();
  $("loadingDetail").textContent = "Finding relevant information…";
  timer = setInterval(() => {
    $("loadingDetail").textContent =
      `Waiting for retrieval and generation · ${Math.floor((Date.now() - start) / 1000)}s`;
  }, 1000);
  try {
    const data = await request("/api/workspace/query", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": state.csrf,
      },
      body: JSON.stringify({ query }),
      signal: controller.signal,
    });
    if (epoch !== state.epoch) return;
    showResult(query, data);
    state.history.unshift({ query, data });
    state.history = state.history.slice(0, 15);
    renderHistory();
  } catch (error) {
    if (epoch !== state.epoch || error.name === "AbortError") return;
    if (error.status === 401) {
      clearPrivateState();
      setIdentity(null);
      notify(error.message);
      openLogin();
    } else {
      $("errorMessage").textContent = error.message;
      $("queryError").hidden = false;
    }
  } finally {
    if (epoch === state.epoch) busy(false);
  }
}
function openLogin() {
  $("loginError").hidden = true;
  $("loginDialog").showModal();
}
async function accountAction() {
  if (!state.user) {
    openLogin();
    return;
  }
  clearPrivateState();
  try {
    await request("/api/logout", { method: "POST" });
    setIdentity(null);
    await refresh();
    notify("Signed out. You’re now browsing public knowledge.");
  } catch (error) {
    notify("Could not sign out. Please retry.");
  }
}
$("workspaceLogin").onsubmit = async (event) => {
  event.preventDefault();
  $("loginSubmit").disabled = true;
  $("loginError").hidden = true;
  try {
    const fields = new FormData(event.currentTarget);
    const data = await request("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: fields.get("username"),
        password: fields.get("password"),
      }),
    });
    clearPrivateState();
    setIdentity(data.user);
    state.csrf = data.csrf_token;
    $("workspaceLogin").reset();
    $("loginDialog").close();
    await loadDocuments();
    notify(`Signed in as ${data.user.username}.`);
  } catch (error) {
    $("loginError").textContent =
      error.status === 401
        ? "Username or password is incorrect."
        : error.message;
    $("loginError").hidden = false;
  } finally {
    $("loginSubmit").disabled = false;
  }
};
$("closeLogin").onclick = () => $("loginDialog").close();
$("signInTop").onclick = accountAction;
$("accountAction").onclick = accountAction;
$("scopeLogin").onclick = openLogin;
$("askTab").onclick = () => tab();
$("libraryTab").onclick = () => {
  tab(true);
  loadDocuments();
};
$("newQuestion").onclick = () => {
  reset();
  tab();
  $("question").focus();
};
$("documentSearch").oninput = renderLibrary;
$("questionForm").onsubmit = (event) => {
  event.preventDefault();
  ask($("question").value);
};
$("question").oninput = () => {
  $("questionLength").textContent =
    `${$("question").value.length.toLocaleString()} / 4,000`;
};
$("question").onkeydown = (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("questionForm").requestSubmit();
  }
};
document.querySelectorAll("[data-question]").forEach((button) => {
  button.onclick = () => ask(button.dataset.question);
});
$("retryButton").onclick = () => ask(lastQuestion);
$("copyAnswer").onclick = async () => {
  try {
    await navigator.clipboard.writeText(currentAnswer);
    notify("Answer copied.");
  } catch {
    notify("Could not copy. Select the answer to copy it manually.");
  }
};
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
refresh();
