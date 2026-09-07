const state = { users: [], departments: [], csrf: "" };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) {
    headers["Content-Type"] = "application/json";
  }
  if (state.csrf) {
    headers["X-CSRF-Token"] = state.csrf;
  }
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(data.message || data.error || "Request failed");
  return data;
}
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.remove("hidden");
  setTimeout(() => node.classList.add("hidden"), 2600);
}
function showLogin() {
  $("#adminAccount").hidden = true;
  $("#adminAccount").textContent = "";
  $("#loginView").classList.remove("hidden");
  $("#dashboardView").classList.add("hidden");
  $("#logoutButton").classList.add("hidden");
}
function showDashboard(user) {
  $("#adminAccount").hidden = false;
  $("#adminAccount").textContent = `${user.username} · Administrator`;
  $("#loginView").classList.add("hidden");
  $("#dashboardView").classList.remove("hidden");
  $("#logoutButton").classList.remove("hidden");
}
async function load() {
  const [users, departments] = await Promise.all([
    api("/api/admin/users"),
    api("/api/admin/departments"),
  ]);
  state.users = users.users;
  state.departments = departments.departments;
  render();
}
function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>'"]/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        char
      ],
  );
}
function render() {
  const search = $("#userSearch").value.toLowerCase();
  const role = $("#roleFilter").value;
  const users = state.users.filter(
    (user) =>
      (!role || user.role === role) &&
      [user.username, user.client_id, user.department].some((value) =>
        (value || "").toLowerCase().includes(search),
      ),
  );
  $("#usersTable").innerHTML = users
    .map(
      (user) =>
        `<tr><td class="user-cell"><strong>${escapeHtml(user.username)}</strong><small>${escapeHtml(user.id.slice(0, 10))}</small></td><td><span class="badge">${user.role}</span>${user.is_admin ? ' <span class="badge">admin</span>' : ""}</td><td class="scope">${escapeHtml(user.client_id || user.department || (user.role === "internal" ? "Explicit permissions" : "Public"))}</td><td class="permissions">${user.permissions.length ? user.permissions.map(escapeHtml).join("<br>") : "—"}</td><td><span class="status ${user.active ? "" : "off"}">${user.active ? "Active" : "Disabled"}</span></td><td><div class="actions"><button class="quiet" data-token="${user.id}">Token</button><button class="quiet" data-edit="${user.id}">Edit</button></div></td></tr>`,
    )
    .join("");
  $("#emptyUsers").classList.toggle("hidden", users.length > 0);
  $("#departmentList").innerHTML = state.departments
    .map(
      (department) =>
        `<article class="department-item"><div><h3>${escapeHtml(department.name)}</h3><p>${escapeHtml(department.id)} · ${department.user_count} users${department.description ? " · " + escapeHtml(department.description) : ""}</p></div><button class="quiet" data-delete-department="${escapeHtml(department.id)}" ${department.user_count ? "disabled" : ""}>Delete</button></article>`,
    )
    .join("");
  $("#userCount").textContent = state.users.length;
  $("#activeCount").textContent = state.users.filter(
    (user) => user.active,
  ).length;
  $("#departmentCount").textContent = state.departments.length;
  $("#clientCount").textContent = new Set(
    state.users.map((user) => user.client_id).filter(Boolean),
  ).size;
  bindRows();
}
function bindRows() {
  $$("[data-edit]").forEach(
    (button) =>
      (button.onclick = () =>
        openUser(state.users.find((user) => user.id === button.dataset.edit))),
  );
  $$("[data-token]").forEach(
    (button) => (button.onclick = () => issueToken(button.dataset.token)),
  );
  $$("[data-delete-department]").forEach(
    (button) =>
      (button.onclick = () =>
        deleteDepartment(button.dataset.deleteDepartment)),
  );
}
function roleFields() {
  const role = $("#userForm [name=role]").value;
  $("#clientField").classList.toggle("hidden", role !== "client");
  $("#departmentField").classList.toggle("hidden", role !== "internal");
  $("#permissionsField").classList.toggle("hidden", role !== "internal");
}
function openUser(user = null) {
  const form = $("#userForm");
  form.reset();
  $("#userDialogTitle").textContent = user ? "Edit user" : "Add user";
  form.elements.id.value = user?.id || "";
  form.elements.username.value = user?.username || "";
  form.elements.password.required = !user;
  form.elements.role.value = user?.role || "guest";
  form.elements.client_id.value = user?.client_id || "";
  form.elements.department.innerHTML =
    '<option value="">No department</option>' +
    state.departments
      .map(
        (department) =>
          `<option value="${escapeHtml(department.id)}">${escapeHtml(department.name)}</option>`,
      )
      .join("");
  form.elements.department.value = user?.department || "";
  form.elements.permissions.value = (user?.permissions || []).join("\n");
  form.elements.active.checked = user?.active ?? true;
  form.elements.is_admin.checked = user?.is_admin ?? false;
  $("#userError").classList.add("hidden");
  roleFields();
  $("#userDialog").showModal();
}
async function saveUser(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const data = {
    username: form.elements.username.value,
    password: form.elements.password.value || undefined,
    role: form.elements.role.value,
    client_id: form.elements.client_id.value || null,
    department: form.elements.department.value || null,
    permissions: form.elements.permissions.value
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean),
    active: form.elements.active.checked,
    is_admin: form.elements.is_admin.checked,
  };
  try {
    await api(id ? `/api/admin/users/${id}` : "/api/admin/users", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(data),
    });
    $("#userDialog").close();
    await load();
    toast(id ? "User updated" : "User created");
  } catch (error) {
    $("#userError").textContent = error.message;
    $("#userError").classList.remove("hidden");
  }
}
async function issueToken(id) {
  try {
    const data = await api(`/api/admin/users/${id}/token`, {
      method: "POST",
      body: "{}",
    });
    $("#issuedToken").textContent = data.token;
    $("#tokenExpiry").textContent =
      `Expires ${new Date(data.expires_at).toLocaleString()}`;
    $("#tokenDialog").showModal();
  } catch (error) {
    toast(error.message);
  }
}
async function deleteDepartment(id) {
  if (!confirm(`Delete department ${id}?`)) return;
  try {
    await api(`/api/admin/departments/${id}`, { method: "DELETE" });
    await load();
    toast("Department deleted");
  } catch (error) {
    toast(error.message);
  }
}
$("#loginForm").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        username: form.elements.username.value,
        password: form.elements.password.value,
      }),
    });
    if (!data.user.is_admin)
      throw new Error("This account is not an administrator");
    state.csrf = data.csrf_token;
    showDashboard(data.user);
    await load();
  } catch (error) {
    $("#loginError").textContent = error.message;
    $("#loginError").classList.remove("hidden");
  }
};
$("#logoutButton").onclick = async () => {
  await api("/api/logout", { method: "POST", body: "{}" });
  state.csrf = "";
  showLogin();
};
$("#newUserButton").onclick = () => openUser();
$("#userForm").onsubmit = saveUser;
$("#userForm [name=role]").onchange = roleFields;
$$("[data-close]").forEach(
  (button) => (button.onclick = () => $("#userDialog").close()),
);
$$("[data-close-token]").forEach(
  (button) => (button.onclick = () => $("#tokenDialog").close()),
);
$("#copyTokenButton").onclick = async () => {
  await navigator.clipboard.writeText($("#issuedToken").textContent);
  toast("Token copied");
};
$("#departmentForm").onsubmit = async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/admin/departments", {
      method: "POST",
      body: JSON.stringify({
        id: form.elements.id.value,
        name: form.elements.name.value,
        description: form.elements.description.value,
      }),
    });
    form.reset();
    await load();
    toast("Department created");
  } catch (error) {
    toast(error.message);
  }
};
$("#userSearch").oninput = render;
$("#roleFilter").onchange = render;
$$(".tab").forEach(
  (tab) =>
    (tab.onclick = () => {
      $$(".tab,.panel").forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      $(`#${tab.dataset.panel}`).classList.add("active");
    }),
);
(async () => {
  try {
    const data = await api("/api/me");
    state.csrf = data.csrf_token;
    showDashboard(data.user);
    await load();
  } catch {
    showLogin();
  }
})();
