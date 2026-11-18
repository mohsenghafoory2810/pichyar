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

  /* SMS code inputs: <input autocomplete="one-time-code" data-otp-length="6"> in a form with the
     "verify" button. Android Chrome reads the code from the SMS itself (Web OTP API; the SMS ends
     with "@domain #code"); iPhone Safari offers it above the keyboard (one tap). As soon as the
     whole code is in the box (filled, typed or pasted) the form is submitted. */
  function latinDigits(s) {
    return String(s)
      .replace(/[۰-۹]/g, function (d) { return d.charCodeAt(0) - 0x06f0; })
      .replace(/[٠-٩]/g, function (d) { return d.charCodeAt(0) - 0x0660; })
      .replace(/\D/g, "");
  }

  function initOtpInputs(root) {
    root.querySelectorAll("input[data-otp-length]").forEach(function (input) {
      if (input._otp) return;
      input._otp = true;
      var length = Number(input.dataset.otpLength) || 6;
      var form = input.form;
      var verify = form && form.querySelector('button[name="action"][value="verify"]');
      if (!verify) return;
      var sent = latinDigits(input.value); // a re-shown wrong code is not sent again by itself

      function submitIfComplete() {
        var code = latinDigits(input.value);
        if (code.length !== length || code === sent || !input.isConnected || verify.disabled) return;
        sent = code;
        input.value = code;
        verify.click(); // a click (not form.submit) so HTMX sends action=verify
      }
      input.addEventListener("input", submitIfComplete);

      if ("OTPCredential" in window && window.AbortController) {
        var ac = new AbortController();
        form.addEventListener("submit", function () { ac.abort(); });
        navigator.credentials
          .get({ otp: { transport: ["sms"] }, signal: ac.signal })
          .then(function (otp) {
            if (!otp || !otp.code || !input.isConnected) return;
            input.value = otp.code;
            submitIfComplete();
          })
          .catch(function () {}); // aborted, refused by the user or not supported: type it in
      }
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

  /* Floating support button: the button shows/hides the panel (aria-expanded kept in sync);
     Escape closes it and puts focus back on the button, a click outside closes it. */
  function initSupportButton() {
    var box = document.querySelector("[data-support-fab]");
    if (!box) return;
    var toggle = box.querySelector(".support-fab__toggle");
    var panel = document.getElementById(toggle.getAttribute("aria-controls"));
    if (!panel) return;
    function setOpen(open) {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
    toggle.addEventListener("click", function () {
      var open = panel.hidden;
      setOpen(open);
      if (open) {
        var first = panel.querySelector("a");
        if (first) first.focus();
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !panel.hidden) {
        setOpen(false);
        toggle.focus();
      }
    });
    document.addEventListener("click", function (e) {
      if (!panel.hidden && !box.contains(e.target)) setOpen(false);
    });
  }

  /* Picture code (accounts/_captcha.html): the "another picture" button loads a new one
     (every load of the picture is a new code on the server). */
  function initCaptchas(root) {
    root.querySelectorAll("[data-captcha]").forEach(function (box) {
      var button = box.querySelector("[data-captcha-refresh]");
      var image = box.querySelector("[data-captcha-image]");
      var input = box.querySelector("input");
      if (!button || !image || button._captcha) return;
      button._captcha = true;
      button.hidden = false;
      var base = image.getAttribute("src").split("?")[0];
      button.addEventListener("click", function () {
        image.src = base + "?t=" + Date.now();
        if (input) { input.value = ""; input.focus(); }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAgeGate();
    initSupportButton();
    initCountdowns(document);
    initOtpInputs(document);
    initCaptchas(document);
  });
  document.addEventListener("htmx:load", function (e) {
    initCountdowns(e.detail.elt);
    initOtpInputs(e.detail.elt);
    initCaptchas(e.detail.elt);
  });
})();
