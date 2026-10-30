/**
 * ZWOL Orders - Algemene functies, Toasts & Sync
 */

function showToast(message, type = "success", duration = 3500) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${message}</span>
    <button style="background:none;border:none;cursor:pointer;font-weight:bold;margin-left:8px;" onclick="this.parentElement.remove()">✕</button>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(-10px)";
    toast.style.transition = "all 0.25s ease-out";
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

async function triggerSync() {
  const btn = document.getElementById("btn-sync");
  if (btn) {
    btn.style.animation = "spin 1s linear infinite";
    btn.disabled = true;
  }

  showToast("Synchroniseren met Silvasoft...", "info", 2000);

  try {
    const res = await fetch("/api/sync", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      if (data.skipped) {
        showToast(`ℹ️ ${data.message || ""}`, "info", 5000);
      } else {
        showToast(`✅ Gesynchroniseerd! ${data.message || ""}`, "success");
      }
      // Herlaad bord of producten indien de functie bestaat
      if (typeof loadOrdersBoard === "function") {
        loadOrdersBoard();
      }
      if (typeof loadProducts === "function") {
        loadProducts();
      }
    } else {
      showToast(`⚠️ Sync fout: ${data.error || "Onbekende fout"}`, "error");
    }
  } catch (err) {
    console.error("Sync fout:", err);
    showToast("⚠️ Kon niet verbinden met de server voor sync.", "error");
  } finally {
    if (btn) {
      btn.style.animation = "";
      btn.disabled = false;
    }
  }
}

// Draai CSS animatie voor sync knop
const style = document.createElement('style');
style.textContent = `
  @keyframes spin { 100% { transform: rotate(360deg); } }
`;
document.head.appendChild(style);
