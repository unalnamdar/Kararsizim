// Progressive enhancement for voting: submits the vote as JSON and reveals
// results in place. Without JS, the same form posts normally and the server
// redirects to the poll's detail page.
// In the first minutes after voting the result bars stay buttons, so the vote can be changed (data.can_change).
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

  // The option's own text, without the check mark or screen reader text of a previous result view.
  function optionText(item, button) {
    const labelNode = item.querySelector(".option__label");
    if (!labelNode) return button.textContent.trim();
    const copy = labelNode.cloneNode(true);
    copy.querySelectorAll(".option__check, .visually-hidden").forEach(function (n) { n.remove(); });
    return copy.textContent.trim();
  }

  // Mirrors templates/polls/_results.html
  function renderResults(form, data) {
    const clickable = data.can_change === true;
    const items = Array.from(form.querySelectorAll(".option"));
    const byId = new Map(data.options.map(function (o) { return [String(o.id), o]; }));
    const list = el("ol", "options options--results");
    list.setAttribute(
      "aria-label",
      clickable ? "Sonuçlar — oyunu değiştirmek için başka bir seçeneğe dokunabilirsin" : "Sonuçlar"
    );
    const fills = [];
    let chosen = null;

    items.forEach(function (item) {
      const button = item.querySelector(".option__button");
      const result = byId.get(button.value);
      if (!result) return;
      const selected = String(data.voted_option_id) === button.value;

      // Only keep the color class (option--N): the form may already be a results list (owner view).
      const colorClass = Array.from(item.classList).find(function (c) { return /^option--\d+$/.test(c); });
      const labelText = optionText(item, button);

      const li = el("li", "option " + colorClass + " option--result" + (selected ? " is-selected" : ""));
      const fill = el("span", "option__fill");
      fill.setAttribute("aria-hidden", "true");
      fill.style.width = "0%";
      fills.push([fill, result.percent]);

      const label = el("span", "option__label", labelText);
      if (selected) {
        chosen = { text: labelText, percent: result.percent };
        label.append(" ");
        const check = el("span", "option__check", "✓");
        check.setAttribute("aria-hidden", "true");
        label.append(check);
        if (!clickable) label.append(el("span", "visually-hidden", "(senin seçimin)"));
      }

      const value = el("span", "option__value");
      value.append(el("strong", null, "%" + result.percent), " · " + result.votes + " oy");

      if (clickable) {
        const choice = el("button", "option__button option__button--result");
        choice.type = "submit";
        choice.name = "option_id";
        choice.value = button.value;
        choice.setAttribute(
          "aria-label",
          labelText + ", %" + result.percent + ", " + result.votes + " oy" + (selected ? " (senin seçimin)" : "")
        );
        choice.append(label, value);
        li.append(fill, choice);
      } else {
        li.append(fill, label, value);
      }
      list.append(li);
    });

    if (clickable) {
      // Same form again (same action and attributes), now holding the result bars as buttons.
      const fresh = form.cloneNode(false);
      const token = form.querySelector("input[name=csrfmiddlewaretoken]");
      if (token) fresh.append(token.cloneNode());
      fresh.append(list);
      form.replaceWith(fresh);
    } else {
      form.replaceWith(list);
    }

    // Next frame(s): grow the bars from 0 so the CSS transition animates.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        fills.forEach(function (pair) { pair[0].style.width = pair[1] + "%"; });
      });
    });
    return { list: list, chosen: chosen };
  }

  // Polite screen reader announcement. Clearing first and setting on the next tick makes
  // readers announce the text even if the same message was set before.
  function announce(card, message) {
    const live = card.querySelector("[data-poll-live]");
    if (!live) return;
    live.textContent = "";
    setTimeout(function () { live.textContent = message; }, 50);
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

  function setNote(card, data) {
    const note = card.querySelector("[data-poll-note]");
    if (!note) return;
    if (data.can_change) {
      note.textContent = "Oyunu " + Math.ceil(data.change_seconds / 60) + " dakika daha değiştirebilirsin.";
      note.hidden = false;
    } else {
      note.textContent = "";
      note.hidden = true;
    }
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
      const rendered = renderResults(form, data);
      setFooter(card, data.total);
      setNote(card, data);
      if (response.status === 409) {
        showError(card, data.message || "Bu ankete zaten oy vermiştin.");  // role="alert" announces it
      } else if (rendered.chosen) {
        announce(
          card,
          (data.changed ? "Oyun değişti. " : "Oyun kaydedildi. ") + "Seçimin: " + rendered.chosen.text + ", %" +
            rendered.chosen.percent + ". Toplam " + data.total + " oy."
        );
      }
      rendered.list.setAttribute("tabindex", "-1");
      rendered.list.focus({ preventScroll: true });
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
