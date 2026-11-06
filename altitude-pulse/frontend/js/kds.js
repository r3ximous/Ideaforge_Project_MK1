import {
  $,
  $$,
  api,
  esc,
  initShell,
  setupAlerts,
  alertUser,
  showError,
  toast,
  dateLabel,
  cupLabel,
} from "./shared.js";
initShell("/kds.html");
setupAlerts($("#kds-alerts"));
let staffKey = "";
let orders = [];
let interval;
let busy = false;
let generation = 0;
let knownIds = null;
let lastSignature = "";
let pendingCancel = null;
const changing = new Set();
const nextStatus = {
  pending: "preparing",
  preparing: "ready",
  ready: "completed",
};
const actionLabel = {
  pending: "Start preparing ↗",
  preparing: "Mark ready ✓",
  ready: "Complete handoff ✓",
};
function disconnect(message = "") {
  generation++;
  clearInterval(interval);
  staffKey = "";
  orders = [];
  knownIds = null;
  lastSignature = "";
  busy = false;
  changing.clear();
  $("#staff-key").value = "";
  $("#kds-board").hidden = true;
  $("#kds-locked").hidden = false;
  $("#disconnect-kds").hidden = true;
  $("#refresh-kds").hidden = true;
  $("#kds-loading").hidden = true;
  $("#kds-count").textContent = "0 active orders";
  $("#kds-connection").textContent = "Staff access required";
  ["pending", "preparing", "ready"].forEach((status) => {
    $(`#${status}-orders`).replaceChildren();
    $(`#${status}-count`).textContent = "0";
  });
  if ($("#cancel-dialog").open) $("#cancel-dialog").close();
  showError($("#kds-error"), message);
}
async function refreshBoard() {
  if (!staffKey || busy || changing.size) return;
  const requestGeneration = generation;
  const key = staffKey;
  busy = true;
  try {
    const data = await api("/api/kds/active", { staffKey: key });
    if (requestGeneration !== generation || changing.size) return;
    orders = (Array.isArray(data.orders) ? data.orders : []).filter((order) =>
      ["pending", "preparing", "ready"].includes(order.status),
    );
    orders.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    const ids = new Set(orders.map((order) => String(order.order_id)));
    if (knownIds) {
      const added = orders.filter(
        (order) => !knownIds.has(String(order.order_id)),
      );
      if (added.length)
        alertUser(
          `${added.length} new kitchen order${added.length === 1 ? "" : "s"}.`,
          "Ready to start the next good moment.",
        );
    }
    knownIds = ids;
    $("#kds-board").hidden = false;
    $("#kds-locked").hidden = true;
    $("#disconnect-kds").hidden = false;
    $("#refresh-kds").hidden = false;
    $("#kds-count").textContent =
      `${orders.length} active order${orders.length === 1 ? "" : "s"}`;
    $("#kds-connection").textContent =
      `Connected · updated ${new Date().toLocaleTimeString("en-AE", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    showError($("#kds-error"), "");
    const signature = JSON.stringify(orders);
    if (signature !== lastSignature) {
      lastSignature = signature;
      renderBoard();
    }
    $$("[data-age]").forEach((node) => {
      const order = orders.find(
        (order) => String(order.order_id) === node.dataset.age,
      );
      if (order) node.textContent = ageLabel(order.created_at);
    });
  } catch (error) {
    if (requestGeneration !== generation) return;
    if ([401, 403].includes(error.status)) {
      disconnect(
        "Staff access was rejected. Enter a valid staff key to reconnect.",
      );
      return;
    }
    showError(
      $("#kds-error"),
      `${error.message} The board may be stale. Retrying every 3 seconds.`,
    );
    $("#kds-connection").textContent = "Connection interrupted · retrying";
  } finally {
    if (requestGeneration === generation) {
      busy = false;
      $("#kds-loading").hidden = true;
    }
  }
}
function ageLabel(created) {
  const age = Math.max(
    0,
    Math.floor((Date.now() - new Date(created).getTime()) / 60000),
  );
  return Number.isFinite(age) ? `${age} min ago` : "Time unavailable";
}
function renderBoard() {
  for (const status of ["pending", "preparing", "ready"]) {
    const column = orders.filter((order) => order.status === status);
    $(`#${status}-count`).textContent = column.length;
    $(`#${status}-orders`).innerHTML = column.length
      ? column
          .map(
            (order) =>
              `<article class="kds-order"><div class="row"><span class="order-number">${esc(order.order_id)}</span><span class="kds-age" data-age="${esc(order.order_id)}">${ageLabel(order.created_at)}</span></div><h3>${esc(order.customer_name)}</h3><span class="badge ${order.order_type === "table" ? "lime" : ""}">${order.order_type === "table" ? `Table ${esc(order.table_number || "—")}` : order.order_type === "takeaway" ? "Takeaway" : "Service details not provided"}</span><span class="small muted" style="display:block;margin-top:8px">${esc(dateLabel(order.created_at))}</span>${(order.items || []).map((item, index) => `<div class="receipt-line"><div class="small muted">${esc(cupLabel(order, index))}</div><strong>${esc(item.item_name)}</strong><div class="small muted">${esc(item.item_size)}</div>${item.customization ? `<div class="notice" style="margin:8px 0">${esc(item.customization)}</div>` : ""}${item.item_code ? `<span class="item-code">${esc(item.item_code)}</span>` : ""}</div>`).join("")}<div class="actions"><button class="btn full" type="button" data-advance="${esc(order.order_id)}"${changing.has(String(order.order_id)) ? " disabled" : ""}>${actionLabel[status]}</button>${status !== "ready" ? `<button class="btn danger small" type="button" data-cancel="${esc(order.order_id)}"${changing.has(String(order.order_id)) ? " disabled" : ""}>Cancel order</button>` : ""}</div></article>`,
          )
          .join("")
      : '<div class="empty">All clear. The next good cup is on its way.</div>';
  }
}
async function changeStatus(id, status) {
  const key = String(id);
  if (changing.has(key) || !staffKey) return;
  const order = orders.find((order) => String(order.order_id) === key);
  if (!order) return;
  if (
    status !== nextStatus[order.status] &&
    !(status === "cancelled" && ["pending", "preparing"].includes(order.status))
  ) {
    toast("This order has changed. Refresh the board first.", true);
    return;
  }
  const requestGeneration = generation;
  changing.add(key);
  renderBoard();
  try {
    await api("/api/kds/status", {
      method: "POST",
      staffKey,
      body: { order_id: order.order_id, status },
    });
    if (requestGeneration !== generation) return;
    toast(`Order ${order.order_id} marked ${status}.`);
  } catch (error) {
    if (requestGeneration !== generation) return;
    if ([401, 403].includes(error.status)) {
      disconnect("Your staff key was rejected. Reconnect to continue.");
      return;
    }
    toast(error.message, true);
    showError(
      $("#kds-error"),
      `${error.message} Refresh to confirm the current status before retrying.`,
    );
  } finally {
    if (requestGeneration === generation) {
      changing.delete(key);
      lastSignature = "";
      renderBoard();
      await refreshBoard();
    }
  }
}
$("#staff-form").onsubmit = async (event) => {
  event.preventDefault();
  const entered = $("#staff-key").value.trim();
  if (!entered) return;
  disconnect();
  staffKey = entered;
  $("#kds-loading").hidden = false;
  $("#kds-connection").textContent = "Connecting…";
  await refreshBoard();
  if (staffKey) interval = setInterval(refreshBoard, 3000);
};
$("#disconnect-kds").onclick = () => disconnect();
$("#refresh-kds").onclick = refreshBoard;
$("#kds-board").onclick = (event) => {
  const advance = event.target.closest("[data-advance]");
  const cancel = event.target.closest("[data-cancel]");
  if (advance) {
    const order = orders.find(
      (order) => String(order.order_id) === advance.dataset.advance,
    );
    if (order) changeStatus(order.order_id, nextStatus[order.status]);
  }
  if (cancel) {
    const order = orders.find(
      (order) => String(order.order_id) === cancel.dataset.cancel,
    );
    if (!order) return;
    pendingCancel = order.order_id;
    $("#cancel-description").textContent =
      `Order ${order.order_id} for ${order.customer_name}. This removes all ${order.items?.length || 0} individual items from the active queue.`;
    $("#cancel-dialog").showModal();
  }
};
$("#close-cancel").onclick = $("#keep-order").onclick = () =>
  $("#cancel-dialog").close();
$("#confirm-cancel").onclick = () => {
  $("#cancel-dialog").close();
  if (pendingCancel != null) changeStatus(pendingCancel, "cancelled");
};
window.addEventListener("pagehide", () => {
  clearInterval(interval);
  staffKey = "";
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted)
    disconnect("Reconnect with your staff key to resume live updates.");
});
