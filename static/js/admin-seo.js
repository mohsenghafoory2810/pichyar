/* Length counter under SEO title/description fields: <input data-seo-counter="60">. */
(function () {
  "use strict";
  var FA = "۰۱۲۳۴۵۶۷۸۹";
  function faDigits(n) {
    return String(n).replace(/\d/g, function (d) { return FA[d]; });
  }
  function attach(input) {
    var limit = Number(input.dataset.seoCounter);
    var out = document.createElement("div");
    out.className = "help seo-counter";
    out.setAttribute("aria-live", "polite");
    input.insertAdjacentElement("afterend", out);
    function update() {
      var n = input.value.length;
      out.textContent = faDigits(n) + " از " + faDigits(limit) + " نویسه" + (n > limit ? " — بیشتر از حد پیشنهادی؛ در نتایج جستجو کوتاه می‌شود." : "");
      out.style.color = n > limit ? "#b45309" : "";
    }
    input.addEventListener("input", update);
    update();
  }
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-seo-counter]").forEach(attach);
  });
})();
