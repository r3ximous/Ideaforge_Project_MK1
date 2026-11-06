import {
  $,
  $$,
  api,
  esc,
  money,
  cupSVG,
  initShell,
  getProfile,
  requireProfile,
  openProfile,
  refreshProfile,
  readStore,
  store,
  removeStore,
  toast,
  showError,
  rememberOrder,
  trackURL,
  dateLabel,
} from "./shared.js";
initShell("/");
$("#hero-cup").innerHTML = cupSVG();
const drinkCategories = new Set(["coffee", "tea", "cold drinks", "special"]);
const isDrink = (item) =>
  drinkCategories.has(String(item.category).trim().toLowerCase());
const priceFor = (item, size) =>
  Number(item.price) - (isDrink(item) && size === "12oz" ? 2 : 0);
let menu = [];
let cart = [];
let category = "All";
let selectedItem = null;
let activePreview = null;
let submitting = false;
const itemDialog = $("#item-dialog");
const checkoutDialog = $("#checkout-dialog");
const arDialog = $("#ar-dialog");
$$("dialog:not(#profile-dialog) [data-close]").forEach((button) =>
  button.addEventListener("click", () => button.closest("dialog").close()),
);
checkoutDialog.addEventListener("cancel", (event) => {
  if (submitting) event.preventDefault();
});
$("#loyalty-button").onclick = () => openProfile();
document.addEventListener("profilechange", updateLoyalty);
function updateLoyalty() {
  const profile = getProfile();
  $("#loyalty-points").innerHTML =
    `${esc(profile?.loyalty_points ?? 0)} <span class="small">pts</span>`;
  $("#loyalty-tier").textContent = profile?.tier || "Campus coffee";
  $("#loyalty-caption").textContent = profile
    ? `${profile.name}, your next good ritual is waiting.${profile.return_discount_eligible ? " Your 20% return offer is ready." : ""}`
    : "A little more altitude with every completed order.";
}
updateLoyalty();
if (getProfile()) refreshProfile().catch(() => {});

async function loadMenu() {
  $("#menu-loading").hidden = false;
  $("#retry-menu").hidden = true;
  showError($("#menu-error"), "");
  try {
    const data = await api("/api/menu");
    menu = Array.isArray(data.items) ? data.items : [];
    const popularItems = Array.isArray(data.popular) ? data.popular : [];
    const popular = new Set(popularItems.map((item) => String(item.item_id)));
    $("#popular-now").hidden = popularItems.length === 0;
    $("#popular-grid").innerHTML = popularItems
      .slice(0, 3)
      .map(productCard)
      .join("");
    menu.forEach((item) => {
      if (popular.has(String(item.item_id))) item.is_popular = true;
    });
    const categories = [
      "All",
      ...new Set(menu.map((item) => item.category).filter(Boolean)),
    ];
    $("#category-filters").innerHTML = categories
      .map(
        (name) =>
          `<button class="chip" type="button" data-category="${esc(name)}" aria-pressed="${category === name}">${esc(name)}</button>`,
      )
      .join("");
    const saved = readStore("ap.cart", []);
    const valid = Array.isArray(saved)
      ? saved.filter(
          (line) =>
            menu.some(
              (item) => String(item.item_id) === String(line.item_id),
            ) && ["12oz", "16oz", "Standard"].includes(line.item_size),
        )
      : [];
    cart = valid.map((line) => ({
      item_id: line.item_id,
      item_size: normalizeSize(
        menu.find((item) => String(item.item_id) === String(line.item_id)),
        line.item_size,
      ),
      customization: String(line.customization || "").slice(0, 200),
    }));
    if (Array.isArray(saved) && saved.length !== valid.length)
      toast(
        "Some items are no longer available and were removed from your bag.",
      );
    applyReorder();
    renderMenu();
    renderCart();
    if (data.promotion) {
      const item = data.promotion;
      $("#promotion").hidden = false;
      $("#promotion").innerHTML =
        `<div class="promo-banner"><p class="eyebrow">In the spotlight ↗</p><h3>${esc(item.name)}</h3><p>${esc(item.description || "A fresh reason to take a break.")}</p>${menu.some((m) => String(m.item_id) === String(item.item_id)) ? `<button type="button" class="btn ghost small" data-featured="${esc(item.item_id)}" style="color:var(--ink);border-color:#20261950;margin-top:16px">Make it yours +</button>` : ""}</div>`;
    }
  } catch (error) {
    showError($("#menu-error"), error.message);
    $("#retry-menu").hidden = false;
  } finally {
    $("#menu-loading").hidden = true;
  }
}
function normalizeSize(item, size) {
  return isDrink(item) ? (size === "12oz" ? "12oz" : "16oz") : "Standard";
}
function applyReorder() {
  const draft = readStore("ap.reorder");
  if (!Array.isArray(draft?.items)) return;
  removeStore("ap.reorder");
  let missing = 0;
  for (const line of draft.items) {
    const match = menu.find((item) =>
      line.item_id != null
        ? String(item.item_id) === String(line.item_id)
        : item.name === line.item_name,
    );
    if (!match) {
      missing++;
      continue;
    }
    cart.push({
      item_id: match.item_id,
      item_size: normalizeSize(match, line.item_size),
      customization: String(line.customization || "").slice(0, 200),
    });
  }
  toast(
    missing
      ? `Available items added. ${missing} unavailable item(s) were skipped. Current menu prices apply.`
      : "Your favourites are back in the bag. Current menu prices apply.",
  );
}
function renderMenu() {
  const search = $("#menu-search").value.trim().toLowerCase();
  const filtered = menu.filter(
    (item) =>
      (category === "All" || item.category === category) &&
      `${item.name} ${item.description || ""}`.toLowerCase().includes(search),
  );
  $("#menu-count").textContent = `${filtered.length} good reasons to pause`;
  $("#menu-empty").hidden = filtered.length > 0;
  $("#menu-grid").innerHTML = filtered.map(productCard).join("");
}
function productCard(item) {
  return `<article class="product"><div class="product-art">${item.is_promo ? '<span class="badge lime">In the spotlight</span>' : item.is_popular ? '<span class="badge lime">Campus favourite</span>' : ""}${cupSVG(!isDrink(item))}${isDrink(item) ? `<button type="button" class="ar-mini" data-ar="${esc(item.item_id)}" aria-label="Preview ${esc(item.name)} cup in 3D">3D / AR ↗</button>` : ""}</div><div class="product-body"><h3>${esc(item.name)}</h3><p>${esc(item.description || item.category)}</p><div class="product-bottom"><span class="price">${money(item.price)} <small>${isDrink(item) ? "16 oz · 12 oz −2 AED" : "Standard"}</small></span><button class="add-btn" type="button" data-add="${esc(item.item_id)}" aria-label="Customize and add ${esc(item.name)}">+</button></div></div></article>`;
}
$("#category-filters").onclick = (event) => {
  const button = event.target.closest("[data-category]");
  if (!button) return;
  category = button.dataset.category;
  $$("#category-filters button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b === button)),
  );
  renderMenu();
};
$("#menu-search").addEventListener("input", renderMenu);
function handleProductClick(event) {
  const add = event.target.closest("[data-add]");
  const preview = event.target.closest("[data-ar]");
  if (add) openItem(add.dataset.add);
  if (preview) openAR(preview.dataset.ar);
}
$("#menu-grid").onclick = handleProductClick;
$("#popular-grid").onclick = handleProductClick;
$("#promotion").onclick = (event) => {
  const button = event.target.closest("[data-featured]");
  if (button) openItem(button.dataset.featured);
};
function openItem(id) {
  selectedItem = menu.find((item) => String(item.item_id) === String(id));
  if (!selectedItem) return;
  $("#item-title").textContent = selectedItem.name;
  $("#item-description").textContent = selectedItem.description || "";
  $("#item-art").innerHTML = cupSVG(!isDrink(selectedItem));
  $("#item-size").innerHTML = (
    isDrink(selectedItem) ? ["16oz", "12oz"] : ["Standard"]
  )
    .map(
      (size) =>
        `<option value="${size}">${size === "Standard" ? "Standard" : size.replace("oz", " oz")} · ${money(priceFor(selectedItem, size))}</option>`,
    )
    .join("");
  $("#item-customization").value = "";
  $("#item-quantity").value = "1";
  updateAddLabel();
  itemDialog.showModal();
}
function updateAddLabel() {
  if (selectedItem)
    $("#item-add").textContent =
      `Add to bag · ${money(priceFor(selectedItem, $("#item-size").value) * Math.max(1, Number($("#item-quantity").value) || 1))}`;
}
$("#item-size").onchange = updateAddLabel;
$("#item-quantity").oninput = updateAddLabel;
$("#item-form").onsubmit = (event) => {
  event.preventDefault();
  if (!selectedItem) return;
  const quantity = Number($("#item-quantity").value);
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 20) return;
  for (let i = 0; i < quantity; i++)
    cart.push({
      item_id: selectedItem.item_id,
      item_size: $("#item-size").value,
      customization: $("#item-customization").value.trim().slice(0, 200),
    });
  renderCart();
  itemDialog.close();
  toast(
    `${quantity === 1 ? selectedItem.name : `${quantity} items`} added to your bag.`,
  );
};
function itemFor(line) {
  return menu.find((item) => String(item.item_id) === String(line.item_id));
}
function cartSubtotal() {
  return cart.reduce(
    (sum, line) => sum + priceFor(itemFor(line), line.item_size),
    0,
  );
}
function renderCart() {
  store("ap.cart", cart);
  $("#cart-count").textContent = `(${cart.length})`;
  $("#cart-items").innerHTML = cart.length
    ? cart
        .map(
          (line, index) =>
            `<div class="cart-line"><div><strong>${esc(itemFor(line).name)}</strong><small>${esc(line.item_size)}${line.customization ? ` · ${esc(line.customization)}` : ""}</small><small>${money(priceFor(itemFor(line), line.item_size))}</small></div><button class="remove" type="button" data-remove="${index}" aria-label="Remove ${esc(itemFor(line).name)} item ${index + 1}">Remove</button></div>`,
        )
        .join("")
    : '<div class="empty"><span class="empty-icon" aria-hidden="true">♧</span>A little empty in here.<br>Find something that lifts your day.</div>';
  $("#cart-subtotal").textContent = money(cartSubtotal());
  $("#checkout-button").disabled = !cart.length;
  $("#mobile-cart").hidden = !cart.length;
  $("#mobile-cart-label").textContent =
    `Your bag · ${cart.length} ${cart.length === 1 ? "item" : "items"}`;
  $("#mobile-cart-total").textContent = `${money(cartSubtotal())} ↗`;
}
$("#cart-items").onclick = (event) => {
  const button = event.target.closest("[data-remove]");
  if (button) {
    cart.splice(Number(button.dataset.remove), 1);
    renderCart();
  }
};
$("#mobile-cart").onclick = () => {
  $("#cart-panel").classList.add("expanded");
  $("#cart-panel").scrollIntoView({ behavior: "smooth", block: "center" });
  $("#checkout-button").focus({ preventScroll: true });
};
$("#close-cart").onclick = () => {
  $("#cart-panel").classList.remove("expanded");
  $("#mobile-cart").focus();
};
function renderCheckoutEstimate(profile, promo, profileFresh) {
  const subtotal = cartSubtotal();
  const qualifyingLine = cart.find(
    (line) => line.item_size === "16oz" && isDrink(itemFor(line)),
  );
  const upgradeSaving =
    profile.monthly_upgrade_available === true && qualifyingLine ? 2 : 0;
  const adjustedSubtotal = subtotal - upgradeSaving;
  const eventPercent = Number(promo?.discount_percent) || 0;
  const discountPercent = Math.min(
    100,
    Math.max(profile.return_discount_eligible ? 20 : 0, eventPercent, 0),
  );
  const discountEstimate =
    Math.round(
      ((adjustedSubtotal * discountPercent) / 100 + Number.EPSILON) * 100,
    ) / 100;
  const totalEstimate =
    Math.round((adjustedSubtotal - discountEstimate + Number.EPSILON) * 100) /
    100;
  const availability = profile.monthly_upgrade_available;
  $("#checkout-upgrade").textContent =
    availability === true
      ? `Platinum monthly upgrade available. ${qualifyingLine ? `Estimated AED 2 saving on one 16oz ${itemFor(qualifyingLine).name}, charged at its 12oz price.` : "Add a qualifying 16oz drink for an estimated AED 2 saving; 12oz drinks and pastries do not qualify."} This benefit is reserved while an order using it is active and consumed only when that order is completed.`
      : availability === false
        ? "Platinum monthly upgrade is not currently available. It may already be used this month, reserved by an active order, or require Platinum membership. No upgrade saving is included in this estimate."
        : "Monthly upgrade availability has not been confirmed. No upgrade saving is included in this estimate.";
  $("#checkout-discount").textContent =
    `${profileFresh ? "" : "Profile refresh unavailable; estimates use your saved membership. "}${profile.return_discount_eligible ? "Your 20% return offer is eligible. " : ""}${promo ? `Your ${promo.discount_percent}% event offer will be submitted. ` : ""}The better return/event discount is estimated after any monthly-upgrade saving; return and event discounts never stack. Estimates only: the server rechecks upgrade availability, reservations, and offer eligibility and determines the final prices and total on your receipt.`;
  $("#checkout-summary").innerHTML =
    `<div class="receipt-totals"><div class="row"><span>${cart.length} individual item${cart.length === 1 ? "" : "s"} · menu subtotal</span><strong>${money(subtotal)}</strong></div><div class="row muted"><span>Monthly upgrade estimate · one drink</span><span>${upgradeSaving ? "−" : ""}${money(upgradeSaving)}</span></div><div class="row muted"><span>Subtotal after upgrade estimate</span><span>${money(adjustedSubtotal)}</span></div><div class="row muted"><span>Best offer estimate (${discountPercent}%)</span><span>${discountEstimate ? "−" : ""}${money(discountEstimate)}</span></div><div class="row grand"><span>Estimated total</span><span>${money(totalEstimate)}</span></div></div>`;
}
$("#checkout-button").onclick = async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const profile = await requireProfile();
    if (!profile || !cart.length) return;
    let profileFresh = true;
    try {
      await refreshProfile();
    } catch {
      profileFresh = false;
      toast(
        "Could not refresh your membership. The server will still confirm any eligible discount.",
      );
    }
    $("#checkout-customer").textContent = `Ordering as ${getProfile().name}`;
    const promo = activePromo();
    renderCheckoutEstimate(getProfile(), promo, profileFresh);
    showError($("#checkout-error"), "");
    checkoutDialog.showModal();
  } finally {
    button.disabled = !cart.length;
  }
};
$$("input[name=order_type]").forEach(
  (input) =>
    (input.onchange = () => {
      const table = input.form.elements.order_type.value === "table";
      $("#table-field").hidden = !table;
      $("#table-number").required = table;
    }),
);
$("#checkout-form").onsubmit = async (event) => {
  event.preventDefault();
  if (submitting || !cart.length || !getProfile()) return;
  const form = event.currentTarget;
  const table = form.elements.order_type.value === "table";
  const tableNumber = form.elements.table_number.value.trim().slice(0, 12);
  if (table && !tableNumber) {
    showError($("#checkout-error"), "Please enter your table number.");
    return;
  }
  const profile = getProfile();
  const promo = activePromo();
  const payload = {
    user_id: profile.user_id,
    customer_name: String(profile.name).slice(0, 60),
    order_type: table ? "table" : "takeaway",
    table_number: table ? tableNumber : null,
    items: cart.map((line) => ({
      item_id: line.item_id,
      item_size: line.item_size,
      customization: String(line.customization || "").slice(0, 200),
    })),
    payment_method: form.elements.payment_method.value,
    ...(promo ? { promo_token: promo.token } : {}),
  };
  submitting = true;
  $("#place-order").disabled = true;
  $("#place-order").textContent = "Sending your order…";
  $("[data-close]", checkoutDialog).disabled = true;
  showError($("#checkout-error"), "");
  try {
    const order = await api("/api/orders", {
      method: "POST",
      customer: true,
      body: payload,
    });
    rememberOrder(order);
    cart = [];
    store("ap.cart", []);
    removeStore("ap.promo");
    // The order token is only stored locally, not exposed in the navigation URL.
    location.assign(trackURL(order.order_id));
  } catch (error) {
    showError(
      $("#checkout-error"),
      `${error.message}${!error.status ? " Your order may have reached the server. Check History before placing it again to avoid duplicates." : ""}`,
    );
    if (!error.status) {
      const link = document.createElement("a");
      link.href = "/history.html";
      link.className = "inline-link";
      link.textContent = " Open order history";
      $("#checkout-error").append(link);
    }
  } finally {
    submitting = false;
    $("#place-order").disabled = false;
    $("#place-order").textContent = "Place demo order ↗";
    $("[data-close]", checkoutDialog).disabled = false;
  }
};
function activePromo() {
  const promo = readStore("ap.promo");
  return promo && String(promo.user_id) === String(getProfile()?.user_id)
    ? promo
    : null;
}
function showPromoNote() {
  const promo = activePromo();
  $("#promo-token-note").hidden = !promo;
  if (promo)
    $("#promo-token-note").textContent =
      `${promo.discount_percent}% event offer saved for your next checkout. The server checks eligibility and applies the better discount. RSVP codes are not a payment.`;
}
async function loadEvents() {
  $("#events-loading").hidden = false;
  $("#retry-events").hidden = true;
  showError($("#events-error"), "");
  try {
    const data = await api("/api/events");
    $("#events-grid").innerHTML = data.events?.length
      ? data.events
          .map(
            (event) =>
              `<article class="event-card"><span class="eyebrow">${esc(event.club_name)}</span><time>${esc(dateLabel(event.event_date))}</time><h3>${esc(event.title)}</h3><p>${esc(event.description)}</p>${event.promo_code ? `<span class="small muted">Club code · ${esc(event.promo_code)}</span>` : ""}<button class="btn secondary" type="button" data-rsvp="${esc(event.event_id)}">RSVP${Number(event.discount_percent) > 0 ? ` · ${esc(event.discount_percent)}% offer` : ""} ↗</button></article>`,
          )
          .join("")
      : '<p class="muted small">No events on the board yet. Come back for your next campus connection.</p>';
  } catch (error) {
    showError($("#events-error"), error.message);
    $("#retry-events").hidden = false;
  } finally {
    $("#events-loading").hidden = true;
  }
}
$("#events-grid").onclick = async (event) => {
  const button = event.target.closest("[data-rsvp]");
  if (!button) return;
  button.disabled = true;
  try {
    const profile = await requireProfile();
    if (!profile) return;
    const result = await api(
      `/api/events/${encodeURIComponent(button.dataset.rsvp)}/rsvp`,
      { method: "POST", customer: true, body: { user_id: profile.user_id } },
    );
    store("ap.promo", { ...result, user_id: profile.user_id });
    showPromoNote();
    button.textContent = "RSVP confirmed ✓";
    toast("You’re on the list. Your latest event offer is saved for checkout.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
};
document.addEventListener("profilechange", showPromoNote);
let arTimeout;
function openAR(id) {
  activePreview = menu.find((item) => String(item.item_id) === String(id));
  $("#ar-size").value = "16oz";
  arDialog.showModal();
  renderAR();
}
function renderAR() {
  clearTimeout(arTimeout);
  $("#ar-state").textContent = "Loading the to-scale cup model…";
  const size = $("#ar-size").value;
  let source = `/assets/models/cup_${size}.glb`;
  // Only accept same-origin GLB URLs. The explicit size assets remain the fallback.
  if (size === "16oz" && activePreview?.model_3d_url) {
    try {
      const url = new URL(activePreview.model_3d_url, location.origin);
      if (url.origin === location.origin && url.pathname.endsWith(".glb"))
        source = url.href;
    } catch {
      /* Use the standard cup. */
    }
  }
  const viewer = document.createElement("model-viewer");
  viewer.className = "ar-viewer";
  viewer.setAttribute("src", source);
  viewer.setAttribute(
    "alt",
    `To-scale ${size.replace("oz", " ounce")} Altitude Pulse cup`,
  );
  viewer.setAttribute("camera-controls", "");
  viewer.setAttribute("touch-action", "pan-y");
  viewer.setAttribute("ar", "");
  viewer.setAttribute("ar-modes", "webxr scene-viewer quick-look");
  viewer.setAttribute("ar-scale", "fixed");
  viewer.setAttribute("shadow-intensity", "1");
  const arButton = document.createElement("button");
  arButton.type = "button";
  arButton.className = "btn";
  arButton.slot = "ar-button";
  arButton.style.cssText = "position:absolute;bottom:16px;left:16px";
  arButton.textContent = "View in your space ↗";
  viewer.append(arButton);
  viewer.addEventListener("load", () => {
    clearTimeout(arTimeout);
    $("#ar-state").textContent =
      "3D preview ready. Drag to rotate; pinch or scroll to zoom. AR is offered only on compatible devices.";
  });
  viewer.addEventListener("error", () => {
    clearTimeout(arTimeout);
    $("#ar-state").textContent =
      "The 3D asset is not available yet. You can still choose a size and order normally.";
  });
  viewer.addEventListener("ar-status", (event) => {
    if (event.detail.status === "failed")
      $("#ar-state").textContent =
        "AR could not start on this device. You can still explore the 3D cup here.";
  });
  $("#ar-container").replaceChildren(viewer);
  arTimeout = setTimeout(() => {
    $("#ar-state").textContent = customElements.get("model-viewer")
      ? "The model is still loading or unavailable. Check your connection; ordering does not require AR."
      : "The 3D viewer could not load. It needs a connection to the model-viewer CDN. Ordering works without it.";
  }, 12000);
}
$("#ar-size").onchange = renderAR;
arDialog.addEventListener("close", () => {
  clearTimeout(arTimeout);
  $("#ar-container").replaceChildren();
});
$("#retry-menu").onclick = loadMenu;
$("#retry-events").onclick = loadEvents;
showPromoNote();
loadMenu();
loadEvents();
