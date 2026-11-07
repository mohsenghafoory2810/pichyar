// Packing slip: the "print" button (no inline script, so the Content-Security-Policy stays strict).
document.addEventListener("click", function (event) {
  if (event.target.closest("[data-print]")) window.print();
});
