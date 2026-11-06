export const money = (value) =>
  new Intl.NumberFormat("en-AE", { style: "currency", currency: "AED" }).format(
    Number(value) || 0,
  );
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [
  ...root.querySelectorAll(selector),
];
export const dateLabel = (value) => {
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? "Date to be confirmed"
    : d.toLocaleString("en-AE", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
};
export function readStore(key, fallback = null) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}
export function store(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    toast(
      "Browser storage is unavailable. Keep this page open; your details may not survive a refresh.",
      true,
    );
    return false;
  }
}
export function removeStore(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    /* Storage may be blocked. */
  }
}
let profile = readStore("ap.profile");
if (!profile?.user_id || !profile?.access_token) profile = null;
export const getProfile = () => profile;
export function saveProfile(value) {
  profile = value;
  store("ap.profile", value);
  document.dispatchEvent(new CustomEvent("profilechange"));
}
export async function refreshProfile() {
  if (!profile) return null;
  const old = profile;
  const next = await api(`/api/users/${encodeURIComponent(old.user_id)}`, {
    customer: true,
  });
  saveProfile({
    ...old,
    ...next,
    access_token: next.access_token || old.access_token,
  });
  return profile;
}
export async function api(
  path,
  { method = "GET", body, customer = false, staffKey, signal } = {},
) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (customer && profile?.access_token)
    headers["X-Customer-Token"] = profile.access_token;
  if (staffKey) headers["X-Staff-Key"] = staffKey;
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: signal || AbortSignal.timeout(15000),
    });
  } catch (error) {
    if (error.name === "AbortError" && signal?.aborted) throw error;
    throw new Error(
      error.name === "TimeoutError"
        ? "The server took too long. Please try again."
        : "Unable to reach Altitude Pulse. Check your connection and try again.",
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Request failed (${response.status}). Please try again.`,
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
export function toast(message, error = false) {
  let container = $("#toasts");
  if (!container) {
    container = document.createElement("div");
    container.id = "toasts";
    container.className = "toasts";
    container.setAttribute("role", "status");
    container.setAttribute("aria-live", "polite");
    document.body.append(container);
  }
  const node = document.createElement("div");
  node.className = `toast${error ? " error" : ""}`;
  node.textContent = message;
  container.append(node);
  setTimeout(() => node.remove(), 6500);
}
export function showError(node, message) {
  node.textContent = message;
  node.hidden = !message;
}
export function cupSVG(pastry = false) {
  if (pastry)
    return '<svg class="cup-svg" viewBox="0 0 180 180" aria-hidden="true"><ellipse cx="90" cy="146" rx="70" ry="12" fill="#191e16" opacity=".4"/><path d="M24 117Q19 87 46 73Q52 42 78 55Q97 35 117 57Q150 51 151 84Q177 102 151 126Q124 145 98 126Q60 146 43 124Z" fill="#d2a36b"/><path d="M58 66Q48 100 63 128M84 55Q73 97 88 129M112 61Q103 100 118 130M138 72Q126 99 137 128" fill="none" stroke="#95683e" stroke-width="6"/><path d="M38 104Q64 82 145 96" fill="none" stroke="#f2c78c" stroke-width="5"/></svg>';
  return '<svg class="cup-svg" viewBox="0 0 180 210" aria-hidden="true"><ellipse cx="91" cy="191" rx="49" ry="9" fill="#141a12" opacity=".3"/><path d="M37 48L50 176Q91 196 132 176L145 48Z" fill="#e9e3cf"/><path d="M43 88L49 151Q91 169 135 151L141 88Q92 105 43 88Z" fill="#c9e989"/><path d="M43 88Q91 103 141 88M49 151Q91 168 135 151" fill="none" stroke="#b2cd77"/><ellipse cx="91" cy="47" rx="58" ry="17" fill="#31392b"/><path d="M33 46V54Q91 76 149 54V46" fill="#353d2e"/><ellipse cx="91" cy="45" rx="58" ry="15" fill="#4b5540"/><ellipse cx="91" cy="42" rx="47" ry="10" fill="#39442f"/><path d="M85 110L72 137H85L96 115L108 139H120L99 107Z" fill="#283821"/><text x="93" y="151" text-anchor="middle" fill="#283821" font-size="6" font-family="sans-serif" letter-spacing="2">ALTITUDE PULSE</text></svg>';
}
export function rememberOrder(order, latest = true) {
  if (!order?.order_id || !order?.access_token) return;
  const orders = readStore("ap.orderKeys", {});
  orders[order.order_id] = order.access_token;
  store("ap.orderKeys", orders);
  if (latest) store("ap.latestOrder", order.order_id);
}
export const orderToken = (id) => readStore("ap.orderKeys", {})[id];
export const trackURL = (id) => `/track.html?id=${encodeURIComponent(id)}`;
export function cupLabel(order, index) {
  return `#${order.order_id} | ${String(order.customer_name).toUpperCase()} | ${index + 1} of ${order.items.length}`;
}
export function receiptHTML(order) {
  return `<div>${(order.items || []).map((item, index) => `<div class="receipt-line"><div class="small muted">${esc(cupLabel(order, index))}</div><div class="row"><div><strong>${esc(item.item_name)}</strong><div class="small muted">${esc(item.item_size)}${item.customization ? ` · ${esc(item.customization)}` : ""}</div>${item.item_code ? `<span class="item-code">${esc(item.item_code)}</span>` : ""}</div><span class="small">${money(item.price)}</span></div></div>`).join("")}</div><div class="receipt-totals"><div class="row muted"><span>Subtotal</span><span>${money(order.subtotal_amount ?? order.total_amount)}</span></div><div class="row muted"><span>Discount</span><span>−${money(order.discount_amount)}</span></div><div class="row grand"><span>Total</span><span>${money(order.total_amount)}</span></div></div><p class="small muted">${order.payment_status === "mock_paid" ? "Demo payment · no money was charged" : esc(order.payment_status || "Payment status unavailable")}<br>${order.status === "completed" ? "Points earned" : order.status === "cancelled" ? "No points awarded" : "Anticipated points (awarded on completion)"}: ${order.status === "cancelled" ? 0 : esc(order.points_earned ?? 0)}</p>`;
}
const nav = [
  ["/", "Menu", "⌂"],
  ["/track.html", "Track order", "◉"],
  ["/history.html", "History", "↺"],
];
export function initShell(page) {
  const links = (mobile) =>
    nav
      .map(
        ([href, label, icon]) =>
          `<a href="${href}"${page === href ? ' aria-current="page"' : ""}>${mobile ? `<span aria-hidden="true">${icon}</span>` : ""}${label}</a>`,
      )
      .join("");
  $("#site-header").innerHTML =
    `<a class="skip-link" href="#main">Skip to content</a><div class="wrap header-inner"><a href="/" class="brand" aria-label="Altitude Pulse home"><span class="brand-mark" aria-hidden="true">↗</span><span>ALTITUDE PULSE<small>RIT DUBAI · CAMPUS COFFEE</small></span></a><nav class="desktop-nav" aria-label="Main navigation">${links(false)}</nav><div class="header-actions"><button class="btn ghost small" id="profile-button" type="button">Your club ↗</button></div></div>`;
  $("#site-footer").innerHTML =
    '<div class="wrap footer-inner"><span>Good coffee. Higher possibilities. © Altitude Pulse · RIT Dubai</span><a href="/kds.html">Staff kitchen display ↗</a></div>';
  const mobile = document.createElement("nav");
  mobile.className = "mobile-nav";
  mobile.setAttribute("aria-label", "Mobile navigation");
  mobile.innerHTML = links(true);
  document.body.append(mobile);
  const dialog = document.createElement("dialog");
  dialog.id = "profile-dialog";
  dialog.setAttribute("aria-labelledby", "profile-title");
  dialog.innerHTML = `<div class="dialog-head"><h2 id="profile-title">Your campus coffee club.</h2><button type="button" class="icon-btn" data-close aria-label="Close profile">×</button></div><div id="profile-content"></div>`;
  document.body.append(dialog);
  $("[data-close]", dialog).addEventListener("click", () => dialog.close());
  $("#profile-button").addEventListener("click", () => openProfile());
  const updateName = () => {
    $("#profile-button").textContent = profile
      ? `${profile.name.split(" ")[0]} · ${profile.loyalty_points ?? 0} pts`
      : "Your club ↗";
  };
  document.addEventListener("profilechange", updateName);
  updateName();
  if ("serviceWorker" in navigator)
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  window.addEventListener("offline", () =>
    toast("You’re offline. Ordering and live updates need a connection.", true),
  );
  if (!navigator.onLine)
    toast(
      "Offline mode: the app shell is available, but live data and ordering need a connection.",
      true,
    );
}
let profileWaiter = null;
export async function requireProfile() {
  if (profile) return profile;
  return openProfile(true);
}
export function openProfile(required = false) {
  const dialog = $("#profile-dialog");
  if (dialog.open) return profileWaiter || Promise.resolve(profile);
  const content = $("#profile-content");
  if (profile) {
    content.innerHTML = `<p class="eyebrow">${esc(profile.tier || "Campus member")}</p><h3>${esc(profile.name)}</h3><p class="muted small">${esc(profile.phone_number)}</p><div class="loyalty-points">${esc(profile.loyalty_points ?? 0)} <span class="small">pts</span></div><p class="small muted">Points arrive when your order is completed, not at checkout.</p>${profile.return_discount_eligible ? '<div class="notice success">Your next eligible order gets 20% off automatically. Event and return discounts do not stack; the server applies the better discount.</div>' : ""}<div class="notice">Your profile and access token are saved on this browser. Don’t use a shared device. This demo has no sign-in recovery; clearing browser data loses access.</div><button class="btn full" type="button" id="refresh-profile">Refresh points</button><p id="profile-error" class="notice error" role="alert" hidden></p>`;
    $("#refresh-profile").onclick = async (e) => {
      e.target.disabled = true;
      try {
        await refreshProfile();
        dialog.close();
        openProfile();
      } catch (error) {
        showError($("#profile-error"), error.message);
        e.target.disabled = false;
      }
    };
    dialog.showModal();
    return Promise.resolve(profile);
  }
  content.innerHTML = `<p class="muted small">${required ? "Create a profile to continue. " : ""}One campus. Your own coffee ritual. Earn loyalty points on completed orders.</p><form id="profile-form"><label for="customer-name">Your name</label><input id="customer-name" name="name" autocomplete="name" maxlength="60" required><label for="customer-phone">Phone number (with country code)</label><input id="customer-phone" name="phone" type="tel" autocomplete="tel" placeholder="+971 50 123 4567" minlength="7" maxlength="24" required><p class="notice small">Saved only in this browser. This demo cannot recover an existing account by phone. A number already registered will be rejected; keep your browser data to retain access.</p><p id="profile-error" class="notice error" role="alert" hidden></p><button class="btn full" type="submit">Join & continue ↗</button></form>`;
  $("#profile-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    const button = $("button[type=submit]", form);
    const name = form.elements.name.value.trim().slice(0, 60);
    const phone = form.elements.phone.value.trim().slice(0, 24);
    if (!name || phone.replace(/\D/g, "").length < 7) {
      showError(
        $("#profile-error"),
        "Enter your name and a valid phone number with country code.",
      );
      return;
    }
    button.disabled = true;
    try {
      saveProfile(
        await api("/api/users", {
          method: "POST",
          body: { name, phone_number: phone },
        }),
      );
      dialog.close("created");
      toast("Welcome to the club. Make yourself at home.");
    } catch (error) {
      showError(
        $("#profile-error"),
        error.status === 409
          ? "This number already has a profile. Use the original browser where you registered; this demo has no login recovery. You can also register a different number you own."
          : error.message,
      );
    } finally {
      button.disabled = false;
    }
  };
  dialog.showModal();
  profileWaiter = new Promise((resolve) =>
    dialog.addEventListener(
      "close",
      () => {
        profileWaiter = null;
        resolve(profile);
      },
      { once: true },
    ),
  );
  return profileWaiter;
}
let audioContext = null;
let alertsEnabled = false;
export function setupAlerts(button) {
  button.addEventListener("click", async () => {
    if (alertsEnabled) {
      alertsEnabled = false;
      button.textContent = "Enable alerts";
      button.setAttribute("aria-pressed", "false");
      return;
    }
    const Audio = window.AudioContext || window.webkitAudioContext;
    try {
      if (Audio) {
        audioContext ||= new Audio();
        await audioContext.resume();
      }
    } catch {
      /* Visual alerts still work. */
    }
    if ("Notification" in window && Notification.permission === "default") {
      try {
        await Notification.requestPermission();
      } catch {
        /* Not supported in all browsers. */
      }
    }
    alertsEnabled = true;
    button.textContent = "Alerts enabled ✓";
    button.setAttribute("aria-pressed", "true");
    toast(
      "Alerts enabled while this page stays open. This is not background push.",
    );
  });
}
export function alertUser(title, body) {
  toast(`${title} ${body}`);
  if (!alertsEnabled) return;
  if (audioContext?.state === "running") {
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.frequency.setValueAtTime(660, audioContext.currentTime);
    oscillator.frequency.setValueAtTime(880, audioContext.currentTime + 0.15);
    gain.gain.setValueAtTime(0.08, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(
      0.001,
      audioContext.currentTime + 0.5,
    );
    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.5);
  }
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      new Notification(title, {
        body,
        icon: "/assets/icon.svg",
        tag: "altitude-status",
      });
    } catch {
      /* Toast is the mobile fallback. */
    }
  }
}
