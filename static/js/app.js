/* Site-wide helpers. Everything here is optional: pages work without JavaScript. */
(function () {
  "use strict";

  var FA = "۰۱۲۳۴۵۶۷۸۹";
  function faDigits(n) {
    return String(n).replace(/\d/g, function (d) { return FA[d]; });
  }

  /* "Resend code" buttons: <button data-countdown="45" disabled>… <span data-countdown-label></span></button> */
  function initCountdowns(root) {
    root.querySelectorAll("[data-countdown]").forEach(function (btn) {
      var left = Number(btn.dataset.countdown) || 0;
      var label = btn.querySelector("[data-countdown-label]");
      if (btn._countdown || left <= 0) return;
      btn._countdown = setInterval(function () {
        left -= 1;
        if (left <= 0) {
          clearInterval(btn._countdown);
          btn.disabled = false;
          if (label) label.textContent = "";
          return;
        }
        if (label) label.textContent = " (" + faDigits(left) + " ثانیه)";
      }, 1000);
    });
  }

  /* Age gate: the server always renders the whole page; while the overlay is shown the page
     behind it is made inert (no focus/clicks, hidden from screen readers) and does not scroll. */
  function initAgeGate() {
    var gate = document.getElementById("age-gate");
    var page = document.getElementById("page");
    if (!gate || !page) return;
    page.inert = true;
    page.setAttribute("aria-hidden", "true");
    document.documentElement.style.overflow = "hidden";
    var confirm = gate.querySelector("button[type=submit]");
    if (confirm) confirm.focus();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAgeGate();
    initCountdowns(document);
  });
  document.addEventListener("htmx:load", function (e) { initCountdowns(e.detail.elt); });
})();
