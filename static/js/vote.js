// Progressive enhancement for voting: submits the vote as JSON and reveals
// results in place. Without JS, the same form posts normally and the server
// redirects to the poll's detail page.
(function () {
  "use strict";

  function csrfToken(form) {
    const input = form.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Mirrors templates/polls/_results.html
  function renderResults(form, data) {
    const items = Array.from(form.querySelectorAll(".option"));
    const byId = new Map(data.options.map(function (o) { return [String(o.id), o]; }));
    const list = el("ol", "options options--results");
    list.setAttribute("aria-label", "Sonuçlar");
    const fills = [];

    items.forEach(function (item) {
      const button = item.querySelector(".option__button");
      const result = byId.get(button.value);
      if (!result) return;
      const selected = String(data.voted_option_id) === button.value;

      // Only keep the color class (option--N): the form may already be a results list (owner view).
      const colorClass = Array.from(item.classList).find(function (c) { return /^option--\d+$/.test(c); });
      const labelNode = item.querySelector(".option__label");
      const labelText = (labelNode || button).textContent.trim();

      const li = el("li", "option " + colorClass + " option--result" + (selected ? " is-selected" : ""));
      const fill = el("span", "option__fill");
      fill.setAttribute("aria-hidden", "true");
      fill.style.width = "0%";
      fills.push([fill, result.percent]);

      const label = el("span", "option__label", labelText);
      if (selected) {
        label.append(" ");
        const check = el("span", "option__check", "✓");
        check.setAttribute("aria-hidden", "true");
        label.append(check, el("span", "visually-hidden", "(senin seçimin)"));
      }

      const value = el("span", "option__value");
      value.append(el("strong", null, "%" + result.percent), " · " + result.votes + " oy");

      li.append(fill, label, value);
      list.append(li);
    });

    form.replaceWith(list);

    // Next frame(s): grow the bars from 0 so the CSS transition animates.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        fills.forEach(function (pair) { pair[0].style.width = pair[1] + "%"; });
      });
    });
    return list;
  }

  function showError(card, message) {
    const box = card.querySelector("[data-poll-error]");
    if (!box) return;
    box.textContent = message;
    box.hidden = false;
  }

  function setFooter(card, total) {
    const footer = card.querySelector("[data-poll-footer]");
    if (footer) footer.textContent = total + " oy" + (footer.hasAttribute("data-owner") ? " · Senin anketin" : "");
  }

  async function submitVote(form, button) {
    const card = form.closest("[data-poll]");
    const buttons = form.querySelectorAll(".option__button");
    buttons.forEach(function (b) { b.disabled = true; });
    card.querySelector("[data-poll-error]").hidden = true;

    let response;
    let data = {};
    try {
      response = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-CSRFToken": csrfToken(form),
        },
        body: JSON.stringify({ option_id: Number(button.value) }),
      });
      data = await response.json().catch(function () { return {}; });
    } catch (error) {
      buttons.forEach(function (b) { b.disabled = false; });
      showError(card, "Bağlantı hatası. Lütfen tekrar dene.");
      return;
    }

    if ((response.status === 200 || response.status === 409) && Array.isArray(data.options)) {
      const list = renderResults(form, data);
      setFooter(card, data.total);
      if (response.status === 409) showError(card, "Bu ankete zaten oy vermiştin.");
      list.setAttribute("tabindex", "-1");
      list.focus({ preventScroll: true });
      return;
    }

    buttons.forEach(function (b) { b.disabled = false; });
    showError(card, data.error || "Bir şeyler ters gitti. Lütfen tekrar dene.");
  }

  document.addEventListener("submit", function (event) {
    const form = event.target.closest("[data-vote-form]");
    if (!form || !window.fetch) return;
    const button = event.submitter;
    if (!button || !button.matches(".option__button")) return;
    event.preventDefault();
    submitVote(form, button);
  });
})();
