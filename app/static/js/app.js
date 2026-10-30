/**
 * ZWOL Orders - Algemene functies, Toasts & Sync
 */

function showToast(message, type = "success", duration = null) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  if (duration === null || duration === undefined) {
    duration = type === "error" ? 20000 : 4000;
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  const messageSpan = document.createElement("div");
  messageSpan.className = "toast-message";
  messageSpan.textContent = message;

  const actions = document.createElement("div");
  actions.className = "toast-actions";

  // Kopieer-knop voor fouten of lange berichten
  if (type === "error" || message.length > 50) {
    const copyBtn = document.createElement("button");
    copyBtn.className = "toast-copy-btn";
    copyBtn.type = "button";
    copyBtn.title = "Kopieer foutmelding naar klembord";
    copyBtn.textContent = "📋 Kopieer";
    copyBtn.onclick = (e) => {
      e.stopPropagation();
      const textToCopy = message;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(textToCopy).then(() => {
          copyBtn.textContent = "✅ Gekopieerd!";
          setTimeout(() => { copyBtn.textContent = "📋 Kopieer"; }, 2500);
        }).catch(() => fallbackCopy(textToCopy, copyBtn));
      } else {
        fallbackCopy(textToCopy, copyBtn);
      }
    };
    actions.appendChild(copyBtn);
  }

  const closeBtn = document.createElement("button");
  closeBtn.className = "toast-close-btn";
  closeBtn.type = "button";
  closeBtn.innerHTML = "✕";
  closeBtn.title = "Sluiten";
  closeBtn.onclick = () => removeToast();
  actions.appendChild(closeBtn);

  toast.appendChild(messageSpan);
  toast.appendChild(actions);
  container.appendChild(toast);

  let timer = null;
  let remaining = duration;
  let startTime = Date.now();

  function startTimer() {
    if (remaining > 0) {
      timer = setTimeout(() => {
        removeToast();
      }, remaining);
    }
  }

  function removeToast() {
    if (timer) clearTimeout(timer);
    toast.style.opacity = "0";
    toast.style.transform = "translateY(-10px)";
    toast.style.transition = "all 0.25s ease-out";
    setTimeout(() => toast.remove(), 250);
  }

  function fallbackCopy(text, btn) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      btn.textContent = "✅ Gekopieerd!";
      setTimeout(() => { btn.textContent = "📋 Kopieer"; }, 2500);
    } catch (e) {
      btn.textContent = "❌ Mislukt";
      setTimeout(() => { btn.textContent = "📋 Kopieer"; }, 2500);
    }
  }

  // Pauzeer auto-dismiss zolang de muis over de melding beweegt
  toast.addEventListener("mouseenter", () => {
    if (timer) {
      clearTimeout(timer);
      remaining -= (Date.now() - startTime);
    }
  });
  toast.addEventListener("mouseleave", () => {
    startTime = Date.now();
    startTimer();
  });

  startTimer();
}

async function triggerSync() {
  const btn = document.getElementById("btn-sync");
  if (btn) {
    btn.style.animation = "spin 1s linear infinite";
    btn.disabled = true;
  }

  showToast("Synchroniseren met Silvasoft...", "info", 2000);

  try {
    const res = await fetch("/api/sync?force=1", { method: "POST" });
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
