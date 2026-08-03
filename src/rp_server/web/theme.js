/* ═══════════════════════════════════════════════════════════
   RoboParty Theme Manager  v1.0
   Persists to localStorage, syncs <html data-theme>, emits events.
   ═══════════════════════════════════════════════════════════ */
window.RP = window.RP || {};

(function () {
  const KEY = "rp_theme";
  const DARK = "dark";
  const LIGHT = "light";

  /** read stored preference, fallback to OS preference, fallback to dark */
  function resolveTheme() {
    const stored = localStorage.getItem(KEY);
    if (stored === DARK || stored === LIGHT) return stored;
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) return LIGHT;
    return DARK;
  }

  /** apply theme to <html> */
  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
  }

  /** toggle between dark <-> light */
  function toggle() {
    const current = document.documentElement.getAttribute("data-theme") || DARK;
    const next = current === DARK ? LIGHT : DARK;
    apply(next);
    document.dispatchEvent(new CustomEvent("rp:themechange", { detail: next }));
    return next;
  }

  /** set explicitly */
  function set(theme) {
    if (theme !== DARK && theme !== LIGHT) return;
    apply(theme);
    document.dispatchEvent(new CustomEvent("rp:themechange", { detail: theme }));
    return theme;
  }

  /** get current theme name */
  function current() {
    return document.documentElement.getAttribute("data-theme") || DARK;
  }

  // ── init on load ──
  apply(resolveTheme());

  // ── listen for OS changes ──
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function (e) {
      // only auto-follow if user hasn't explicitly picked
      if (!localStorage.getItem(KEY)) {
        apply(e.matches ? DARK : LIGHT);
      }
    });
  }

  // ── expose ──
  RP.theme = { toggle, set, current, DARK, LIGHT };
})();
