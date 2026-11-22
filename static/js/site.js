// Closes the user menu (<details>) on outside click, Escape and when focus leaves it.
// Without JS the menu still works: it just stays open until toggled again.
(function () {
  "use strict";

  const menus = Array.from(document.querySelectorAll("[data-menu]"));
  if (!menus.length) return;

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
})();
