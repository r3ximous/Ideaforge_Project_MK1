import {
  $,
  api,
  esc,
  initShell,
  getProfile,
  orderToken,
  rememberOrder,
  readStore,
  receiptHTML,
  setupAlerts,
  alertUser,
  showError,
  dateLabel,
} from "./shared.js";
initShell("/track.html");
setupAlerts($("#enable-alerts"));
const params = new URLSearchParams(location.search);
let id = params.get("id") || readStore("ap.latestOrder");
let token = params.get("token") || (id ? orderToken(id) : null);
// Strip a supplied private token from the visible URL as soon as it is consumed.
if (params.has("token")) {
  params.delete("token");
  history.replaceState(null, "", `${location.pathname}?${params}`);
}
let current = null;
let socket = null;
let reconnectTimer;
let pollTimer;
let retryDelay = 1500;
let lastSnapshot = 0;
let revision = 0;
let stopped = false;
let fetching = false;
let generation = 0;
let controller = null;
const terminal = (status) => ["completed", "cancelled"].includes(status);
const statusCopy = {
  pending: [
    "You’re in good company.",
    "Your order is in the queue. The team will get started soon.",
  ],
  preparing: [
    "A little craft. A lot of care.",
    "Your order is being made. We’ll let you know when it’s ready.",
  ],
  ready: [
    "Your little lift is ready.",
    "Your order is ready. Check the item badges with the team for pickup or table service.",
  ],
  completed: [
    "A good moment, delivered.",
    "Your order is complete. Your earned points are now part of your coffee story.",
  ],
  cancelled: [
    "This order was cancelled.",
    "No loyalty points are awarded for cancelled orders. Speak to the team if you need help.",
  ],
};
function connection(text) {
  $("#connection").textContent = text;
}
function render(order) {
  if (!order || String(order.order_id) !== String(id)) return;
  const previous = current?.status;
  current = order;
  revision++;
  lastSnapshot = Date.now();
  rememberOrder(order);
  token = order.access_token || token;
  $("#order-view").hidden = false;
  $("#lookup-panel").hidden = true;
  $("#track-loading").hidden = true;
  $("#retry-track").hidden = true;
  showError($("#track-error"), "");
  const status = order.status;
  const [title, copy] = statusCopy[status] || [
    "Your order",
    "Waiting for the next update.",
  ];
  const stages = ["pending", "preparing", "ready", "completed"];
  const index = stages.indexOf(status);
  $("#order-view").innerHTML =
    `<section class="panel" aria-labelledby="order-status-title"><div class="row" style="flex-wrap:wrap"><span class="order-number">ORDER ${esc(order.order_id)}</span><span class="status-pill ${status === "cancelled" ? "cancelled" : ""}">${esc(status)}</span></div><h2 id="order-status-title" style="margin:25px 0 10px">${title}</h2><p class="muted small">${copy}</p>${status !== "cancelled" ? `<ol class="progress" aria-label="Order progress">${stages.map((stage, i) => `<li class="${i <= index ? "active" : ""}"${i === index ? ' aria-current="step"' : ""}>${["Queued", "Preparing", "Ready", "Completed"][i]}</li>`).join("")}</ol>` : ""}${["pending", "preparing"].includes(status) ? `<div class="queue-details"><div><div class="queue-number">${esc(order.queue_position ?? "—")}</div><span class="small muted">Queue position</span></div><div><div class="queue-number">${esc(order.orders_ahead ?? "—")}</div><span class="small muted">Orders ahead</span></div></div><p class="small muted">Queue positions update as the team works. They are not a promised wait time.</p>` : ""}<div class="notice">${esc(order.customer_name)} · ${order.order_type === "table" ? `Table ${esc(order.table_number || "—")}` : order.order_type === "takeaway" ? "Takeaway" : "Service details not provided"}<br>${esc(dateLabel(order.created_at))}</div></section><section class="panel" aria-labelledby="receipt-heading"><div class="section-top"><h2 id="receipt-heading">Your order, cup by cup.</h2></div><p class="small muted">Each badge identifies one individual item, even if you ordered the same drink twice.</p>${receiptHTML(order)}</section><div class="row" style="flex-wrap:wrap;margin:20px 0"><a href="/history.html" class="btn">Receipts & reorder ↗</a><button id="find-another" class="btn ghost" type="button">Find another order</button></div>`;
  $("#find-another").onclick = () => {
    $("#lookup-panel").hidden = false;
    $("#lookup-id").focus();
    $("#lookup-panel").scrollIntoView({ block: "center" });
  };
  if (previous && previous !== status)
    alertUser(
      status === "ready" ? "Your order is ready!" : `Order ${status}.`,
      status === "ready" ? "Your next good moment is waiting." : copy,
    );
  if (terminal(status)) {
    stopConnections();
    connection("Final order status · no further live updates needed");
  }
}
async function fetchOrder() {
  if (!id || fetching) return;
  fetching = true;
  const startedRevision = revision;
  const requestGeneration = generation;
  controller = new AbortController();
  try {
    const order = await api(
      `/api/orders/queue/${encodeURIComponent(id)}${token ? `?token=${encodeURIComponent(token)}` : ""}`,
      {
        customer: true,
        signal: AbortSignal.any([
          controller.signal,
          AbortSignal.timeout(15000),
        ]),
      },
    );
    if (requestGeneration !== generation) return;
    if (startedRevision === revision) render(order);
    if (!terminal(current?.status) && !socket) connectSocket();
  } catch (error) {
    if (requestGeneration !== generation || error.name === "AbortError") return;
    showError(
      $("#track-error"),
      `${error.message}${current ? " Showing the last received snapshot; retrying automatically." : " Check the order ID and private token, or open your history on the browser where you ordered."}`,
    );
    $("#retry-track").hidden = false;
    $("#lookup-panel").hidden = !!current;
    $("#track-loading").hidden = true;
    connection("Updates interrupted");
  } finally {
    if (requestGeneration === generation) fetching = false;
  }
}
function connectSocket() {
  if (stopped || socket || !id || !token || terminal(current?.status)) return;
  const ws = new WebSocket(
    `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/orders/${encodeURIComponent(id)}?token=${encodeURIComponent(token)}`,
  );
  socket = ws;
  ws.onopen = () => {
    retryDelay = 1500;
    connection("Live connection · updates as they happen");
  };
  ws.onmessage = (event) => {
    try {
      render(JSON.parse(event.data));
    } catch {
      connection("Waiting for a valid update · polling available");
    }
  };
  ws.onerror = () => {
    connection("Live connection interrupted · polling every 5 seconds");
    ws.close();
  };
  ws.onclose = () => {
    if (socket === ws) socket = null;
    if (stopped || terminal(current?.status)) return;
    connection("Polling every 5 seconds · reconnecting live updates");
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connectSocket, retryDelay);
    retryDelay = Math.min(30000, retryDelay * 2);
  };
}
function stopConnections() {
  clearTimeout(reconnectTimer);
  clearInterval(pollTimer);
  stopped = true;
  if (socket) {
    const ws = socket;
    socket = null;
    ws.onclose = null;
    ws.close();
  }
}
async function start() {
  stopConnections();
  controller?.abort();
  generation++;
  fetching = false;
  stopped = false;
  current = null;
  revision++;
  const startGeneration = generation;
  $("#track-loading").hidden = false;
  $("#order-view").hidden = true;
  $("#lookup-id").value = id || "";
  connection("Connecting to your order…");
  await fetchOrder();
  if (startGeneration === generation && !terminal(current?.status))
    pollTimer = setInterval(() => {
      if (
        !socket ||
        socket.readyState !== WebSocket.OPEN ||
        Date.now() - lastSnapshot > 15000
      )
        fetchOrder();
    }, 5000);
}
$("#retry-track").onclick = () => fetchOrder();
$("#lookup-form").onsubmit = (event) => {
  event.preventDefault();
  id = $("#lookup-id").value.trim();
  token = $("#lookup-token").value.trim() || orderToken(id);
  $("#lookup-token").value = "";
  history.replaceState(null, "", `/track.html?id=${encodeURIComponent(id)}`);
  start();
};
window.addEventListener("pagehide", stopConnections);
window.addEventListener("pageshow", (event) => {
  if (event.persisted && id) start();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && id && !terminal(current?.status)) fetchOrder();
});
if (id) start();
else {
  $("#lookup-panel").hidden = false;
  connection(
    getProfile()
      ? "Choose an order from your history or enter its ID"
      : "No order saved on this browser",
  );
}
