// Dynamic 2–5 option inputs for the poll creation form.
// The server validates the same rules; this is only a convenience.
(function () {
  "use strict";

  const form = document.querySelector("[data-poll-form]");
  if (!form) return;

  const list = form.querySelector("[data-option-list]");
  const template = form.querySelector("[data-option-template]");
  const addButton = form.querySelector("[data-add-option]");
  const min = Number(form.dataset.minOptions) || 2;
  const max = Number(form.dataset.maxOptions) || 5;

  function rows() {
    return Array.from(list.querySelectorAll("[data-option-row]"));
  }

  function refresh() {
    const all = rows();
    all.forEach(function (row, index) {
      const number = index + 1;
      const id = "option-" + number;
      const label = row.querySelector("label");
      const input = row.querySelector("input");
      const remove = row.querySelector("[data-remove-option]");

      row.className = "option-input option--" + index;
      label.textContent = "Seçenek " + number;
      label.htmlFor = id;
      input.id = id;
      remove.hidden = all.length <= min;
      remove.setAttribute("aria-label", "Kaldır: Seçenek " + number);
    });
    addButton.hidden = all.length >= max;
  }

  addButton.addEventListener("click", function () {
    if (rows().length >= max) return;
    const row = template.content.firstElementChild.cloneNode(true);
    list.appendChild(row);
    refresh();
    row.querySelector("input").focus();
  });

  list.addEventListener("click", function (event) {
    const remove = event.target.closest("[data-remove-option]");
    if (!remove || rows().length <= min) return;
    const row = remove.closest("[data-option-row]");
    const all = rows();
    const index = all.indexOf(row);
    row.remove();
    refresh();
    // Keep keyboard focus nearby instead of losing it to <body>.
    const next = rows()[Math.min(index, rows().length - 1)];
    if (next) next.querySelector("input").focus();
  });

  refresh();
})();
