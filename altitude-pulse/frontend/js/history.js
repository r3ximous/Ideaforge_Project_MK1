import {
  $,
  api,
  esc,
  money,
  initShell,
  getProfile,
  requireProfile,
  refreshProfile,
  receiptHTML,
  rememberOrder,
  trackURL,
  store,
  toast,
  showError,
  dateLabel,
} from "./shared.js";
initShell("/history.html");
let orders = [];
let loading = false;
let loadedUser = null;
function renderMember() {
  const profile = getProfile();
  $("#history-member").hidden = !profile;
  $("#history-gate").hidden = !!profile;
  if (!profile) return;
  $("#history-member").innerHTML =
    `<div class="row"><div><p class="eyebrow">${esc(profile.tier || "Campus member")}</p><h2 style="margin:0">Good to see you, ${esc(profile.name)}.</h2></div><div><strong style="font-size:1.7rem;color:var(--lime)">${esc(profile.loyalty_points ?? 0)}</strong><span class="small muted"> pts</span></div></div><p class="small muted" style="margin:15px 0 0">${profile.return_discount_eligible ? "Your 20% return offer is ready for an eligible order. It never stacks with event offers." : "Points are awarded on completed orders. Pending orders show anticipated points only."}</p>`;
}
async function loadHistory() {
  const profile = getProfile();
  renderMember();
  if (!profile || loading) return;
  loading = true;
  $("#refresh-history").disabled = true;
  $("#history-loading").hidden = false;
  showError($("#history-error"), "");
  try {
    const data = await api(
      `/api/users/${encodeURIComponent(profile.user_id)}/history`,
      { customer: true },
    );
    orders = Array.isArray(data.orders) ? data.orders : [];
    loadedUser = profile.user_id;
    orders.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    orders.forEach((order) => rememberOrder(order, false));
    renderOrders();
    refreshProfile().catch(() => {});
  } catch (error) {
    showError(
      $("#history-error"),
      `${error.message}${orders.length ? " These are the last receipts loaded; they may not reflect recent updates." : ""}`,
    );
  } finally {
    loading = false;
    $("#refresh-history").disabled = false;
    $("#history-loading").hidden = true;
  }
}
function renderOrders() {
  $("#history-empty").hidden = orders.length > 0;
  $("#history-orders").innerHTML = orders
    .map(
      (order, index) =>
        `<article class="history-card"><div class="row" style="align-items:start"><div><p class="eyebrow">${esc(dateLabel(order.created_at))}</p><h3>${money(order.total_amount)}</h3><div class="order-number muted" style="margin-top:8px">${esc(order.order_id)}</div></div><span class="status-pill ${order.status === "cancelled" ? "cancelled" : ""}">${esc(order.status)}</span></div><p class="small muted" style="margin:17px 0 0">${esc((order.items || []).map((item) => `${item.item_name} (${item.item_size})`).join(" · "))}</p><div class="actions"><a class="btn secondary small" href="${trackURL(order.order_id)}">${["completed", "cancelled"].includes(order.status) ? "View order" : "Track live"} ↗</a><button type="button" class="btn small" data-reorder="${index}"${order.items?.length ? "" : " disabled"}>Order again +</button></div><details><summary>View itemized receipt</summary>${receiptHTML(order)}<p class="small muted">${order.order_type === "table" ? `Table ${esc(order.table_number || "—")}` : order.order_type === "takeaway" ? "Takeaway" : "Service details not provided"} · ${esc(order.customer_name)}</p></details></article>`,
    )
    .join("");
}
$("#history-orders").onclick = (event) => {
  const button = event.target.closest("[data-reorder]");
  if (!button) return;
  const order = orders[Number(button.dataset.reorder)];
  if (
    store("ap.reorder", {
      items: order.items.map((item) => ({
        item_id: item.item_id,
        item_name: item.item_name,
        item_size: item.item_size,
        customization: item.customization,
      })),
    })
  )
    location.assign("/");
  else
    toast(
      "Reordering requires browser storage. You can add your favourites from the menu.",
      true,
    );
};
$("#refresh-history").onclick = loadHistory;
$("#join-history").onclick = async () => {
  await requireProfile();
  loadHistory();
};
document.addEventListener("profilechange", () => {
  renderMember();
  if (getProfile()?.user_id !== loadedUser) loadHistory();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) loadHistory();
});
renderMember();
loadHistory();
