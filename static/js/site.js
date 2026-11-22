// Small accessibility helpers shared by every page. Everything here is progressive
// enhancement: without JS the menu still toggles and the error summary is still on the page.
(function () {
  "use strict";

  // --- User menu (<details>): close on outside click, Escape and when focus leaves it. ---
  const menus = Array.from(document.querySelectorAll("[data-menu]"));

  if (menus.length) {
    document.addEventListener("click", function (event) {
      menus.forEach(function (menu) {
        if (menu.open && !menu.contains(event.target)) menu.open = false;
      });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      menus.forEach(function (menu) {
        if (!menu.open) return;
        menu.open = false;
        menu.querySelector("summary").focus();
      });
    });

    menus.forEach(function (menu) {
      menu.addEventListener("focusout", function (event) {
        if (menu.open && event.relatedTarget && !menu.contains(event.relatedTarget)) menu.open = false;
      });
    });
  }

  // --- Form error summary: announce it by moving focus there after a failed submit. ---
  const summary = document.querySelector("[data-error-summary]");

  if (summary) {
    // Forms drop their `autofocus` after a failed submit, so nothing competes for focus here.
    summary.focus();
    summary.scrollIntoView({ block: "nearest" });

    // A link in the summary should land on the field itself, not just scroll near it.
    summary.addEventListener("click", function (event) {
      const link = event.target.closest("a[href^='#']");
      if (!link) return;
      const target = document.getElementById(link.getAttribute("href").slice(1));
      if (!target) return;
      event.preventDefault();
      target.focus();
      target.scrollIntoView({ block: "center" });
    });
  }
})();
