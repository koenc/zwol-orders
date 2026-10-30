/**
 * ZWOL Orders - Nieuwe Order Invoeren (Screen 1)
 */

let debounceTimer = null;
let allActiveProducts = [];
let manualReferenceEdited = false;

document.addEventListener("DOMContentLoaded", () => {
  initDateDefaults();
  loadProducts();

  // Luister of de gebruiker handmatig de referentie aanpast
  const refInput = document.getElementById("reference");
  if (refInput) {
    refInput.addEventListener("input", () => {
      manualReferenceEdited = true;
    });
  }

  // Sluit autocomplete bij klik buiten het veld
  document.addEventListener("click", (e) => {
    const wrapper = document.querySelector(".autocomplete-wrapper");
    const dropdown = document.getElementById("customer-suggestions");
    if (wrapper && !wrapper.contains(e.target) && dropdown) {
      dropdown.style.display = "none";
    }
  });
});

// -----------------------------------------------------------------------------
// Datums & Referentie Helpers
// -----------------------------------------------------------------------------
function initDateDefaults() {
  const today = new Date();
  const todayIso = toIsoDate(today);

  const orderDateInput = document.getElementById("order-date");
  if (orderDateInput) {
    orderDateInput.value = todayIso;
  }

  const deliveryDateInput = document.getElementById("delivery-date");
  if (deliveryDateInput) {
    deliveryDateInput.value = todayIso;
    updateReferenceFromDate(todayIso);
  }
}

function handleDeliveryDateChange(isoDate) {
  if (!manualReferenceEdited) {
    updateReferenceFromDate(isoDate);
  }
}

function updateReferenceFromDate(isoDate) {
  if (!isoDate) return;
  const parts = isoDate.split("-");
  if (parts.length === 3) {
    const nlDate = `${parts[2]}-${parts[1]}-${parts[0]}`;
    const refInput = document.getElementById("reference");
    if (refInput) {
      refInput.value = `Levering ${nlDate}`;
    }
  }
}

function setQuickDate(type) {
  const now = new Date();
  let target = new Date();

  if (type === "today") {
    target = now;
  } else if (type === "tomorrow") {
    target.setDate(now.getDate() + 1);
  } else if (type === "friday") {
    // Vind eerstvolgende vrijdag (5)
    const day = now.getDay();
    const diff = (5 - day + 7) % 7 || 7;
    target.setDate(now.getDate() + diff);
  } else if (type === "next_week") {
    // Volgende week vrijdag
    const day = now.getDay();
    const diff = ((5 - day + 7) % 7 || 7) + 7;
    target.setDate(now.getDate() + diff);
  }

  const iso = toIsoDate(target);
  const deliveryInput = document.getElementById("delivery-date");
  if (deliveryInput) {
    deliveryInput.value = iso;
    updateReferenceFromDate(iso);
  }

  // Active chip styling
  document.querySelectorAll(".chip-btn").forEach(btn => btn.classList.remove("active"));
  if (event && event.target) {
    event.target.classList.add("active");
  }
}

function toIsoDate(d) {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// -----------------------------------------------------------------------------
// Klant Autocomplete
// -----------------------------------------------------------------------------
function handleCustomerInput(query) {
  clearTimeout(debounceTimer);
  const dropdown = document.getElementById("customer-suggestions");
  if (!dropdown) return;

  query = query.trim();
  if (query.length < 2) {
    dropdown.style.display = "none";
    dropdown.innerHTML = "";
    return;
  }

  debounceTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/api/customers?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      const customers = data.customers || [];

      if (customers.length === 0) {
        dropdown.innerHTML = `<div style="padding:12px;color:#888;font-size:0.85rem;">Geen klanten gevonden voor "${escapeHtml(query)}"</div>`;
        dropdown.style.display = "block";
        return;
      }

      let html = "";
      customers.forEach(c => {
        const address = [c.street, c.city].filter(Boolean).join(", ");
        html += `
          <div class="suggestion-item" onclick="selectCustomer('${c.customer_number}', '${escapeJs(c.name)}', '${escapeJs(c.contact_person || '')}', '${escapeJs(address)}')">
            <span class="suggestion-name">${escapeHtml(c.name)}</span>
            <span class="suggestion-details">${escapeHtml(address)} ${c.contact_person ? `(Contact: ${escapeHtml(c.contact_person)})` : ''}</span>
          </div>
        `;
      });

      dropdown.innerHTML = html;
      dropdown.style.display = "block";
    } catch (err) {
      console.error("Fout bij zoeken klanten:", err);
    }
  }, 220);
}

function selectCustomer(number, name, contact, address) {
  document.getElementById("selected-customer-number").value = number;
  document.getElementById("selected-customer-name").value = name;
  document.getElementById("customer-search").value = name;

  // Verberg dropdown
  const dropdown = document.getElementById("customer-suggestions");
  if (dropdown) dropdown.style.display = "none";

  // Toon badge
  const badge = document.getElementById("selected-customer-badge");
  document.getElementById("badge-name").textContent = name;
  document.getElementById("badge-details").textContent = [address, contact].filter(Boolean).join(" • ");
  badge.style.display = "flex";
}

function clearSelectedCustomer() {
  document.getElementById("selected-customer-number").value = "";
  document.getElementById("selected-customer-name").value = "";
  document.getElementById("customer-search").value = "";
  document.getElementById("customer-search").focus();
  document.getElementById("selected-customer-badge").style.display = "none";
}

// -----------------------------------------------------------------------------
// Producten & Steppers
// -----------------------------------------------------------------------------
async function loadProducts() {
  const container = document.getElementById("products-container");
  if (!container) return;

  try {
    const res = await fetch("/api/products");
    const data = await res.json();
    allActiveProducts = data.products || [];

    if (allActiveProducts.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <p>Geen producten gevonden met custom veld 'Tonen in ZWOL order app'.</p>
          <button type="button" class="btn-icon" style="margin-top:8px;background:var(--zwol-green);" onclick="triggerSync()">🔄 Synchroniseer nu</button>
        </div>
      `;
      return;
    }

    let html = "";
    allActiveProducts.forEach(p => {
      const shortBadge = p.short_name ? `<span class="product-badge">${escapeHtml(p.short_name)}</span>` : "";
      const priceFormatted = parseFloat(p.price || 0) > 0 ? `€ ${parseFloat(p.price).toFixed(2)}` : "";
      const unit = p.unit ? `per ${p.unit}` : "";
      const priceText = [priceFormatted, unit].filter(Boolean).join(" ");

      html += `
        <div class="product-row" id="row-${p.article_number}">
          <div class="product-info">
            <div>${shortBadge}<span class="product-name">${escapeHtml(p.name)}</span></div>
            <div class="product-sub">${escapeHtml(priceText)}</div>
          </div>
          <div class="stepper-control">
            <button type="button" class="stepper-btn" onclick="adjustQty('${p.article_number}', -1)">−</button>
            <input 
              type="number" 
              id="qty-${p.article_number}" 
              class="stepper-value" 
              value="0" 
              min="0" 
              max="999"
              onchange="onQtyInputChange('${p.article_number}')"
            >
            <button type="button" class="stepper-btn" onclick="adjustQty('${p.article_number}', 1)">+</button>
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  } catch (err) {
    console.error("Fout bij laden producten:", err);
    container.innerHTML = `<p style="color:var(--zwol-danger);">Fout bij laden producten.</p>`;
  }
}

function adjustQty(articleNumber, delta) {
  const input = document.getElementById(`qty-${articleNumber}`);
  if (!input) return;
  let val = parseInt(input.value) || 0;
  val = Math.max(0, val + delta);
  input.value = val;
  updateRowState(articleNumber, val);
}

function onQtyInputChange(articleNumber) {
  const input = document.getElementById(`qty-${articleNumber}`);
  if (!input) return;
  let val = parseInt(input.value) || 0;
  if (val < 0) val = 0;
  input.value = val;
  updateRowState(articleNumber, val);
}

function updateRowState(articleNumber, qty) {
  const row = document.getElementById(`row-${articleNumber}`);
  if (row) {
    if (qty > 0) {
      row.classList.add("selected");
    } else {
      row.classList.remove("selected");
    }
  }
  updateSubmitButtonLabel();
}

function updateSubmitButtonLabel() {
  let totalItems = 0;
  allActiveProducts.forEach(p => {
    const input = document.getElementById(`qty-${p.article_number}`);
    if (input) {
      totalItems += parseInt(input.value) || 0;
    }
  });

  const label = document.getElementById("btn-submit-label");
  if (label) {
    if (totalItems > 0) {
      label.textContent = `Order Opslaan in Silvasoft (${totalItems} ${totalItems === 1 ? 'collo' : 'colli'})`;
    } else {
      label.textContent = "Order Opslaan in Silvasoft";
    }
  }
}

// -----------------------------------------------------------------------------
// Order Opslaan Formulier Verzenden
// -----------------------------------------------------------------------------
async function submitNewOrder(e) {
  e.preventDefault();

  const customerNumber = document.getElementById("selected-customer-number").value;
  const customerName = document.getElementById("selected-customer-name").value || document.getElementById("customer-search").value.trim();
  const orderDate = document.getElementById("order-date").value;
  const deliveryDate = document.getElementById("delivery-date").value;
  const reference = document.getElementById("reference").value.trim();

  if (!customerName) {
    showToast("Vul a.u.b. een klant in.", "error");
    document.getElementById("customer-search").focus();
    return;
  }

  // Verzamel alle producten met aantal > 0
  const items = [];
  allActiveProducts.forEach(p => {
    const input = document.getElementById(`qty-${p.article_number}`);
    if (input) {
      const qty = parseInt(input.value) || 0;
      if (qty > 0) {
        items.push({
          article_number: p.article_number,
          name: p.name,
          short_name: p.short_name || "",
          quantity: qty,
          price: p.price || 0.0
        });
      }
    }
  });

  if (items.length === 0) {
    showToast("Voer ten minste 1 bier of artikel in met de + knop.", "error");
    return;
  }

  const submitBtn = document.getElementById("btn-submit-order");
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span>⏳</span> Bezig met opslaan in Silvasoft...`;

  try {
    const res = await fetch("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_number: customerNumber,
        customer_name: customerName,
        order_date: orderDate,
        delivery_date: deliveryDate,
        reference: reference,
        items: items
      })
    });

    const data = await res.json();
    if (data.success) {
      showToast(`🍻 Order succesvol aangemaakt in Silvasoft!`, "success");
      // Direct doorsturen naar het orders bord
      setTimeout(() => {
        window.location.href = "/";
      }, 700);
    } else {
      showToast(`⚠️ Fout bij aanmaken order: ${data.error || "Onbekende fout"}`, "error");
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span>🛒</span> <span id="btn-submit-label">Order Opslaan in Silvasoft</span>`;
    }
  } catch (err) {
    console.error("Fout bij order aanmaken:", err);
    showToast("⚠️ Kon geen verbinding maken met de server.", "error");
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<span>🛒</span> <span id="btn-submit-label">Order Opslaan in Silvasoft</span>`;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeJs(str) {
  if (!str) return "";
  return String(str).replace(/'/g, "\\'").replace(/"/g, '\\"');
}
