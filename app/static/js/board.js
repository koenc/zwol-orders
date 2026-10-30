/**
 * ZWOL Orders - Week Kanban Board & Order Detail Modal
 */

let activeOrder = null;

document.addEventListener("DOMContentLoaded", () => {
  loadOrdersBoard();
});

async function loadOrdersBoard() {
  const container = document.getElementById("kanban-wrapper");
  if (!container) return;

  try {
    const res = await fetch("/api/orders");
    const data = await res.json();

    if (!data.success) {
      container.innerHTML = `
        <div class="empty-state" style="width: 100%;">
          <div class="empty-state-icon">⚠️</div>
          <h3>Kon orders niet laden</h3>
          <p>${data.error || "Onbekende fout"}</p>
        </div>
      `;
      return;
    }

    const weeks = data.weeks || [];

    if (weeks.length === 0) {
      container.innerHTML = `
        <div class="empty-state" style="width: 100%;">
          <div class="empty-state-icon">🍻</div>
          <h3>Geen openstaande orders!</h3>
          <p>Alle bieren zijn geleverd of er zijn nog geen nieuwe orders met status 'Bevestigd'.</p>
          <a href="/create" class="btn-primary-action" style="max-width: 240px; margin: 20px auto 0 auto; text-decoration: none;">
            ➕ Nieuwe Order Maken
          </a>
        </div>
      `;
      return;
    }

    // Bouw de kolommen per week
    let html = "";
    weeks.forEach(weekGroup => {
      const orders = weekGroup.orders || [];
      if (orders.length === 0) return; // Weken zonder orders overslaan

      let totalColli = 0;
      orders.forEach(o => {
        // Bereken totaal colli indien gewenst
        const lines = o.order_lines || [];
        lines.forEach(l => {
          totalColli += parseInt(l.Quantity || l.quantity || 0) || 0;
        });
      });

      html += `
        <div class="kanban-column" id="week-col-${weekGroup.year}-${weekGroup.week}">
          <div class="column-header">
            <div>
              <div class="column-title">Week ${weekGroup.week}</div>
              <div style="font-size: 0.75rem; opacity: 0.85;">${weekGroup.date_range_label || ""}</div>
            </div>
            <div class="column-badge">${orders.length} orders${totalColli > 0 ? ` (${totalColli} colli)` : ''}</div>
          </div>
          <div class="column-cards">
      `;

      orders.forEach(order => {
        html += `
          <div class="order-card" id="card-${order.order_number}" onclick="openOrderDetail('${order.order_number}')">
            <div class="order-card-customer">${escapeHtml(order.customer_name || 'Onbekende Klant')}</div>
            <div class="order-card-products">🏷️ ${escapeHtml(order.products_summary || 'Geen producten')}</div>
            <div class="order-card-footer">
              <span class="date-pill">📅 ${escapeHtml(order.delivery_date_formatted || order.delivery_date)}</span>
              <span class="status-pill status-bevestigd">Bevestigd</span>
            </div>
          </div>
        `;
      });

      html += `
          </div>
        </div>
      `;
    });

    container.innerHTML = html;

  } catch (err) {
    console.error("Fout bij laden orders bord:", err);
    container.innerHTML = `
      <div class="empty-state" style="width: 100%;">
        <div class="empty-state-icon">⚠️</div>
        <h3>Fout bij laden van orders</h3>
        <p>Controleer de serververbinding of probeer te synchroniseren.</p>
      </div>
    `;
  }
}

async function openOrderDetail(orderNumber) {
  try {
    const res = await fetch(`/api/orders/${orderNumber}`);
    const data = await res.json();
    if (!data.success || !data.order) {
      showToast("Kon orderdetails niet ophalen.", "error");
      return;
    }

    const order = data.order;
    activeOrder = order;

    document.getElementById("modal-customer-name").textContent = order.customer_name || "Klant";
    document.getElementById("modal-order-number").textContent = `Order #${order.order_number}`;
    document.getElementById("modal-contact-person").textContent = order.contact_person || "Geen contactpersoon bekend";
    
    // Adres
    const fullAddress = [
      order.address_street ? `${order.address_street} ${order.address_unit || ''}`.trim() : '',
      order.address_postal_code || '',
      order.address_city || ''
    ].filter(Boolean).join(", ");

    document.getElementById("modal-address").textContent = fullAddress || "Geen adres bekend";

    // Navigeer knop
    const navBtn = document.getElementById("btn-navigate");
    if (fullAddress) {
      navBtn.style.display = "inline-flex";
      navBtn.href = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(fullAddress)}`;
    } else {
      navBtn.style.display = "none";
    }

    // Telefoon knop
    const phoneBtn = document.getElementById("btn-call");
    const phoneEl = document.getElementById("modal-phone");
    if (order.phone) {
      phoneEl.textContent = order.phone;
      phoneBtn.style.display = "inline-flex";
      phoneBtn.href = `tel:${order.phone.replace(/[^0-9+]/g, '')}`;
    } else {
      phoneEl.textContent = "Geen telefoonnummer";
      phoneBtn.style.display = "none";
    }

    // Datum & Referentie
    document.getElementById("modal-delivery-date").textContent = order.delivery_date_formatted || order.delivery_date || "-";
    document.getElementById("modal-reference").textContent = order.reference || "-";

    // Artikelen tabel
    const tbody = document.getElementById("modal-items-tbody");
    tbody.innerHTML = "";
    const lines = order.order_lines || [];
    if (lines.length === 0) {
      tbody.innerHTML = `<tr><td colspan="2" style="text-align:center;color:#888;">Geen artikelen gespecificeerd</td></tr>`;
    } else {
      lines.forEach(item => {
        const desc = item.Description || item.name || item.DescriptionPlainText || "Artikel";
        const qty = item.Quantity || item.quantity || 1;
        tbody.innerHTML += `
          <tr>
            <td><strong>${escapeHtml(desc)}</strong></td>
            <td style="text-align: right; font-weight: 800; color: var(--zwol-green); font-size: 1.05rem;">
              ${qty}x
            </td>
          </tr>
        `;
      });
    }

    // Reset knop status
    const btnDeliver = document.getElementById("btn-mark-delivered");
    btnDeliver.disabled = false;
    btnDeliver.innerHTML = `<span>✅</span> Markeer als Geleverd`;

    // Toon modal
    document.getElementById("order-modal").style.display = "flex";

  } catch (err) {
    console.error("Fout bij ophalen order details:", err);
    showToast("Fout bij openen order.", "error");
  }
}

function closeOrderModal(event) {
  if (event && event.target && event.target.id !== "order-modal" && !event.target.classList.contains("btn-icon")) {
    return;
  }
  document.getElementById("order-modal").style.display = "none";
  activeOrder = null;
}

async function confirmDeliverOrder() {
  if (!activeOrder) return;
  const orderNumber = activeOrder.order_number;
  const btn = document.getElementById("btn-mark-delivered");
  btn.disabled = true;
  btn.innerHTML = `<span>⏳</span> Bezig met bijwerken in Silvasoft...`;

  try {
    const res = await fetch(`/api/orders/${orderNumber}/deliver`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" }
    });

    const data = await res.json();
    if (data.success) {
      // Sluit modal
      document.getElementById("order-modal").style.display = "none";
      showToast(`✅ Order #${orderNumber} (${activeOrder.customer_name}) is gemarkeerd als Geleverd!`, "success");

      // Verwijder kaartje met animatie van het bord
      const card = document.getElementById(`card-${orderNumber}`);
      if (card) {
        card.style.opacity = "0";
        card.style.transform = "scale(0.85)";
        card.style.transition = "all 0.25s ease-out";
        setTimeout(() => {
          card.remove();
          // Indien kolom nu leeg is, herlaad bord
          loadOrdersBoard();
        }, 260);
      } else {
        loadOrdersBoard();
      }
    } else {
      showToast(`⚠️ Fout bij afvinken: ${data.error || "Probeer opnieuw"}`, "error");
      btn.disabled = false;
      btn.innerHTML = `<span>✅</span> Markeer als Geleverd`;
    }
  } catch (err) {
    console.error("Fout bij markeren als geleverd:", err);
    showToast("⚠️ Serverfout bij afvinken van de order.", "error");
    btn.disabled = false;
    btn.innerHTML = `<span>✅</span> Markeer als Geleverd`;
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
