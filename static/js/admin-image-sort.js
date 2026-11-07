/* Product images inline: drag rows to reorder (the first row is the main image),
   and preview a newly chosen file before saving. No dependencies. */
(function () {
  "use strict";

  function init() {
    var group = document.querySelector(".sortable-images");
    if (!group) return;
    var tbody = group.querySelector("table tbody");
    if (!tbody) return;
    var dragged = null;

    function rows() {
      return Array.prototype.filter.call(tbody.querySelectorAll("tr.form-row"), function (tr) {
        return !tr.classList.contains("empty-form");
      });
    }

    function hasImage(tr) {
      var file = tr.querySelector('input[type="file"]');
      return tr.querySelector(".field-preview img") || (file && file.files && file.files.length);
    }

    // Only renumber rows that hold an image, so empty extra rows stay "unchanged".
    function renumber() {
      var n = 0;
      rows().forEach(function (tr) {
        var order = tr.querySelector('input[name$="-order"]');
        if (order && hasImage(tr)) order.value = n++;
      });
    }

    function showPreview(tr, file) {
      var cell = tr.querySelector(".field-preview");
      if (!cell || !file.files || !file.files[0]) return;
      var img = document.createElement("img");
      img.className = "catalog-thumb";
      img.style.height = "72px";
      img.alt = "";
      img.src = URL.createObjectURL(file.files[0]);
      var p = cell.querySelector("p");
      (p || cell).replaceChildren(img);
    }

    function prepare(tr) {
      if (tr.dataset.sortReady) return;
      tr.dataset.sortReady = "1";
      tr.draggable = true;
      var first = tr.querySelector("td");
      if (first) {
        var handle = document.createElement("span");
        handle.className = "drag-handle";
        handle.title = "برای جابه‌جایی بکشید";
        handle.textContent = "⠿";
        first.insertBefore(handle, first.firstChild);
      }
      var file = tr.querySelector('input[type="file"]');
      if (file) {
        file.addEventListener("change", function () {
          showPreview(tr, file);
          renumber();
        });
      }
    }

    tbody.addEventListener("dragstart", function (e) {
      dragged = e.target.closest("tr.form-row");
      if (dragged) {
        dragged.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
      }
    });
    tbody.addEventListener("dragover", function (e) {
      if (!dragged) return;
      e.preventDefault();
      var target = e.target.closest("tr.form-row");
      if (!target || target === dragged || target.classList.contains("empty-form")) return;
      var rect = target.getBoundingClientRect();
      var after = e.clientY > rect.top + rect.height / 2;
      tbody.insertBefore(dragged, after ? target.nextSibling : target);
    });
    tbody.addEventListener("dragend", function () {
      if (dragged) dragged.classList.remove("dragging");
      dragged = null;
      renumber();
    });

    rows().forEach(prepare);
    // Django fires this when "add another image" inserts a row.
    document.addEventListener("formset:added", function (e) {
      if (e.target && tbody.contains(e.target)) prepare(e.target);
    });
    group.classList.add("js-sortable");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
