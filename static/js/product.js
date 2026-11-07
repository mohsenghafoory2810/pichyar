/* Product page: gallery thumbnails and the quantity stepper. Works without it too. */
(function () {
  "use strict";

  function initGallery(root) {
    var track = root.querySelector("[data-gallery-track]");
    var thumbs = root.querySelectorAll("[data-gallery-thumb]");
    if (!track || !thumbs.length) return;
    function mark(i) {
      thumbs.forEach(function (t, j) {
        t.classList.toggle("border-ink", i === j);
        t.classList.toggle("border-line", i !== j);
      });
    }
    thumbs.forEach(function (thumb) {
      thumb.addEventListener("click", function () {
        var i = Number(thumb.dataset.galleryThumb);
        var slide = track.children[i];
        if (slide) track.scrollTo({ left: slide.offsetLeft - track.offsetLeft, behavior: "smooth" });
        mark(i);
      });
    });
    track.addEventListener("scroll", function () {
      var w = track.clientWidth || 1;
      mark(Math.round(Math.abs(track.scrollLeft) / w));
    }, { passive: true });
  }

  function initQty(root) {
    var input = root.querySelector("input");
    root.querySelectorAll("[data-qty-step]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var min = Number(input.min) || 1;
        var max = Number(input.max) || Infinity;
        var next = (Number(input.value) || min) + Number(btn.dataset.qtyStep);
        input.value = Math.min(max, Math.max(min, next));
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-gallery]").forEach(initGallery);
    document.querySelectorAll("[data-qty]").forEach(initQty);
  });
})();
