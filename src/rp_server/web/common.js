/* ═══════════════════════════════════════════════════════════
   RoboParty Shared Helpers  v2.0
   Lightweight helpers used by all pages.
   ═══════════════════════════════════════════════════════════ */
window.RP = window.RP || {};

(function () {
  var RP = window.RP;

  /** Generic fetch helper. */
  RP.api = async function (path, opts) {
    opts = opts || {};
    var r = await fetch(path, Object.assign({}, opts, {
      headers: Object.assign({ "Content-Type": "application/json" }, opts.headers || {}),
    }));
    var text = await r.text();
    var data;
    try { data = JSON.parse(text); } catch (_) { data = text; }
    if (!r.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
    return data;
  };

  /** Set pill element text + class. */
  RP.setPill = function (el, text, kind) {
    if (!el) return;
    el.className = "pill" + (kind ? " " + kind : "");
    // keep the dot span if present
    var dot = el.querySelector(".dot");
    if (dot) {
      el.innerHTML = "";
      el.appendChild(dot);
      el.appendChild(document.createTextNode(text));
    } else {
      el.innerHTML = '<span class="dot"></span>' + text;
    }
  };

  /** Show a toast notification. Automatically removed after 3s.
   *  @param {string} message
   *  @param {'info'|'ok'|'error'|'warn'} [kind='info']
   */
  RP.toast = function (message, kind) {
    kind = kind || "info";
    var container = document.querySelector(".rp-toast-container");
    if (!container) {
      container = document.createElement("div");
      container.className = "rp-toast-container";
      document.body.appendChild(container);
    }
    var el = document.createElement("div");
    el.className = "rp-toast " + kind;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(function () {
      el.style.opacity = "0";
      el.style.transform = "translateY(-8px)";
      el.style.transition = "opacity 0.2s, transform 0.2s";
      setTimeout(function () { el.remove(); }, 200);
    }, 3000);
  };

})();
